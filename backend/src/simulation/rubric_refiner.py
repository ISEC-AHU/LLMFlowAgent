"""
Rubric Refiner.
Refines rubric criteria and weights from discrepancy-analysis results.
"""
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from ..rubric_generator.simple_rubric import Rubric, RubricDimension
from .discrepancy_analyzer import DiscrepancyReport
from ..llm_factory.factory import LLMFactory
from ..llm_factory.base import Message, run_sync
import json
import asyncio
import aiohttp
@dataclass
class RefinementConfig:
    """Rubric-refinement configuration."""
    high_discrimination_multiplier: float = 1.5  # High-discrimination weight.
    low_discrimination_multiplier: float = 0.5   # Low-discrimination weight.
    error_point_multiplier: float = 2.0          # Error-point weight.
    add_error_tips: bool = True                  # Whether to add error guidance.


class RubricRefiner:
    """
    Rubric refiner.

    Adjusts weights by discriminatory power, adds detailed checks for highly
    discriminating steps, adds guidance for common errors, and produces a
    refined rubric.
    """

    def __init__(self,
                 provider: Optional[str] = None,
                 model: Optional[str] = None,
                 config: Optional[RefinementConfig] = None,
                 use_llm: bool = True):

        """
        Initialize the refiner.

        Args:
            provider: LLM provider.
            model: Model name.
            config: Refinement configuration.
            use_llm: When false, adjust weights without generating detailed guidance.
        """
        self.use_llm = use_llm

        if use_llm:
            if provider is None and model is None:
                self.llm = LLMFactory.get_rubric_client('refinement')
            else:
                role_config = LLMFactory.get_rubric_generator_config("refinement")
                selected_provider = provider or role_config["provider"]
                selected_model = model or role_config.get("model")
                self.llm = LLMFactory.get_client(selected_provider, selected_model)
        else:
            self.llm = None


        self.config = config or RefinementConfig()

    async def _call_refinement_llm_direct(
            self,
            prompt: str,
            temperature: float = 0.3,
            max_completion_tokens: int = 2000
    ) -> str:
        """
        Invoke the LLM specifically for rubric refinement.

        This path deliberately avoids ``self.llm.acomplete()``, omits
        ``max_tokens``, and sends only ``max_completion_tokens`` so it does not
        alter the shared ``openai_client.py`` behavior.
        """
        if self.llm is None:
            raise ValueError("self.llm is None")

        api_key = getattr(self.llm, "api_key", None)
        base_url = getattr(self.llm, "base_url", None)
        model = getattr(self.llm, "model", None)

        if not api_key or not base_url or not model:
            raise ValueError("Invalid LLM client: missing api_key/base_url/model")

        if max_completion_tokens is None or max_completion_tokens <= 0:
            max_completion_tokens = 2000

        url = f"{base_url}/chat/completions"

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a strict rubric refinement expert. You must return valid JSON only."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens
        }

        timeout = getattr(self.llm, "timeout", aiohttp.ClientTimeout(total=180))
        max_retries = getattr(self.llm, "max_retries", 3)

        for attempt in range(max_retries):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            raise Exception(f"API error (status {resp.status}): {error_text}")

                        data = await resp.json()
                        return data["choices"][0]["message"]["content"]

            except asyncio.TimeoutError:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise Exception("Request timeout during rubric refinement")

            except Exception as e:
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise e

    # ------------------------------------------------------------------
    # Generate a task-specific rubric directly from warning edges.
    # ------------------------------------------------------------------

    @staticmethod
    def _is_warn_edge(item: Dict[str, Any]) -> bool:
        """Treat an edge as a warning when any evidence source warns.

        Evidence comes from model consensus, log conformance, or manual review.
        The legacy ``model_status or status`` expression masked log or manual
        warnings whenever model_status was pass, preventing the downstream
        remove_edge repair path in Workflow 191.
        """
        return any(
            str(item.get(field) or "").strip().lower() == "warn"
            for field in ("model_status", "status", "log_status")
        )

    async def generate_rubric_from_warnings(
            self,
            sim_results: Dict[str, Any],
            task: Dict
    ) -> Rubric:
        """
        Generate a task-specific rubric directly from Stage 3 warning edges,
        without using a draft rubric.

        Args:
            sim_results: {"task_links": [{"source", "target", "status"}, ...]}
            task: Task data.

        Returns:
            Generated task-specific rubric.
        """
        # Select an edge when any model, manual, or log status warns.
        warn_links = [
            item for item in sim_results.get("task_links", []) or []
            if RubricRefiner._is_warn_edge(item)
        ]

        task_id = str(task.get("id", ""))
        task_desc = task.get("user_request", "") or task.get("instruction", "")

        if not warn_links:
            return Rubric(
                task_id=task_id,
                task_description=task_desc,
                dimensions=[],
                metadata={"reason": "No warn items found in sim_results."}
            )

        # Generate rubric dimensions directly from warning edges with an LLM.
        log_reduced_edges = sim_results.get("log_reduced_edges", []) or []
        dimensions = await self._generate_dimensions_from_warn_links(
            warn_links, task, log_reduced_edges
        )

        return Rubric(
            task_id=task_id,
            task_description=task_desc,
            dimensions=dimensions,
            metadata={
                "refinement": True,
                "refinement_source": "warn_edges_direct",
                "warn_count": len(warn_links),
            }
        )

    async def _generate_dimensions_from_warn_links(
            self,
            warn_links: List[Dict[str, Any]],
            task: Dict,
            log_reduced_edges: Optional[List[Dict[str, Any]]] = None,
    ) -> List[RubricDimension]:
        """
        Generate rubric dimensions directly from warning edges with an LLM.
        """
        # Format warning edges.
        warn_edges_str = json.dumps(
            [
                {
                    "source": e.get("source", ""),
                    "target": e.get("target", ""),
                    "reviewed_status": e.get("status", "warn"),
                    "log_edge_type": e.get("log_edge_type", ""),
                    "expected_relation": self._expected_relation(e),
                    "log_path": self._shortest_log_path(
                        log_reduced_edges,
                        e.get("source", ""),
                        e.get("target", ""),
                    ),
                }
                for e in warn_links
            ],
            ensure_ascii=False,
            indent=2,
        )

        # Format the candidate-tool list.
        candidates = task.get("candidates", []) or task.get("api_list", []) or []
        if candidates:
            tools_str = json.dumps(
                [
                    {
                        "name": t.get("name", ""),
                        "description": t.get("description", ""),
                    }
                    for t in candidates
                    if isinstance(t, dict)
                ],
                ensure_ascii=False,
                indent=2,
            )
        else:
            tools_str = "N/A"

        task_desc = task.get("user_request", "") or task.get("instruction", "")
        task_steps = task.get("task_steps", []) or []

        prompt = f"""
        You are a rubric generation expert for workflow DAG evaluation.

        You are given:
        1. The original workflow task description.
        2. The task steps.
        3. The list of available tools/APIs.
        4. A list of dependency edges marked as "warn" — these are discrepancies found by multi-agent DAG analysis. At least one model disagreed on these edges, or the edges exist in model DAGs but not in the original DAG.

        Your job is to generate **task-specific rubric dimensions** that specifically evaluate whether a generated DAG correctly handles these problematic dependency areas.

        User Task:
        {task_desc}

        Task Steps:
        {json.dumps(task_steps, ensure_ascii=False, indent=2)}

        Available Tools/APIs:
        {tools_str}

        Warn Dependency Edges (human-confirmed discrepancies):
        {warn_edges_str}

        Generation requirements:

        1. Every dimension must be strictly task-specific and professionally named.
           * Refer to concrete tools, dependencies, or workflow logic in this task.
           * Do NOT generate generic dimensions such as "accuracy", "completeness", or "consistency".
           * Do NOT use the repetitive pattern "X dependency on Y" — vary naming style across ALL dimensions.
           * Use diverse, professional naming styles. Mix different patterns across dimensions, for example:
             - Quality attribute + context: "Customer Data Completeness for Quote Generation"
             - Source-Target integrity: "Quote-to-Order Data Integrity"
             - Validation focus: "Selection Input Validation"
             - Process gate: "Concern Resolution Prerequisite Check"
             - Correctness criterion: "Product Selection Accuracy in Quote"
           * Each theme should be unique and immediately convey WHAT aspect of the workflow is evaluated.

        2. Generate exactly {len(warn_links)} dimensions: one dimension for each warn edge.
           * Never merge, group, skip, or duplicate warn edges.
           * Preserve input order: output item N must evaluate warn edge N.
           * Copy that edge's source and target verbatim into the output object.
           * Follow expected_relation exactly:
             - required_direct: the direct edge must exist.
             - transitive_only: the source must reach the target through intermediate nodes, while the redundant direct edge must not exist.
             - forbidden: the direct edge must not exist.
           * Never describe a transitive_only or forbidden edge as a required direct edge.

        3. For each dimension, provide 1-3 concrete and actionable tips with varied focus:
           * Verify execution order — is the source step guaranteed to complete before the target step?
           * Check data compatibility — does the output type/format of the source tool match the target tool's input expectation?
           * Assess necessity — is this connection essential, or could it be redundant or misplaced?
           * Evaluate alternatives — would a different tool or step ordering produce a more robust workflow?
           * Consider edge cases — what happens if the source output is empty, malformed, or delayed?
           * Use diverse phrasing across tips (avoid starting every tip with the same verb).

        4. Weights must be between 0.1 and 3.0.
           * Dimensions covering critical workflow dependencies should have higher weights (1.5-3.0).
           * Dimensions covering minor issues should have lower weights (0.5-1.5).

        5. Output requirements:
           * Return only valid JSON — no markdown, no extra explanation.
           * The output must be a JSON list of rubric dimension objects.
           * Each object must contain exactly: source, target, expected_relation, theme, description, tips (array of strings), weight (number).

        Output format:

        [
        {{
            "source": "dependency source",
            "target": "dependency target",
            "expected_relation": "required_direct | transitive_only | forbidden",
            "theme": "dimension theme",
            "description": "dimension description",
            "tips": ["tip 1", "tip 2", "tip 3"],
            "weight": 1.5
        }}
        ]
        """

        try:
            raw_text = await self._call_refinement_llm_direct(
                prompt=prompt,
                temperature=0.3,
                max_completion_tokens=2000,
            )
            print("[generate_rubric_from_warnings] raw_text:", raw_text)

            raw_text = raw_text.strip()
            parsed = self._safe_parse_json(raw_text)

            if not isinstance(parsed, list):
                print("[generate_rubric_from_warnings] LLM did not return a list; using edge-specific fallbacks.")
                parsed = []

            return self._normalize_warn_dimensions(
                parsed, warn_links, log_reduced_edges
            )

        except Exception as e:
            print(f"[generate_rubric_from_warnings] Failed: {e}")
            return self._normalize_warn_dimensions(
                [], warn_links, log_reduced_edges
            )

    @staticmethod
    def _expected_relation(edge: Dict[str, Any]) -> str:
        reviewed_status = str(edge.get("status", "warn")).lower()
        edge_type = str(edge.get("log_edge_type", "")).lower()
        if reviewed_status == "pass":
            return "required_direct"
        if edge_type == "transitive":
            return "transitive_only"
        return "forbidden"

    @staticmethod
    def _shortest_log_path(
            log_reduced_edges: Any,
            source: str,
            target: str,
    ) -> List[Dict[str, str]]:
        """Find the authoritative shortest path in the reduced XES log graph.

        Return hops connecting source to target as ``[{"source": a,
        "target": b}, ...]`` or an empty list when no path or endpoint exists.
        Recording this authoritative path on the rubric lets evaluation and
        repair deterministically identify missing bridge edges in Workflow 199
        instead of relying on LLM inference.
        """
        source = str(source or "").strip()
        target = str(target or "").strip()
        if not source or not target or source == target:
            return []
        adjacency: Dict[str, List[str]] = {}
        for edge in log_reduced_edges or []:
            if not isinstance(edge, dict):
                continue
            edge_source = str(edge.get("source", "")).strip()
            edge_target = str(edge.get("target", "")).strip()
            if not edge_source or not edge_target or edge_source == edge_target:
                continue
            adjacency.setdefault(edge_source, []).append(edge_target)
        queue = [(source, [])]
        visited = {source}
        while queue:
            node, path = queue.pop(0)
            for neighbor in adjacency.get(node, []):
                hop_path = path + [{"source": node, "target": neighbor}]
                if neighbor == target:
                    return hop_path
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, hop_path))
        return []

    @staticmethod
    def _normalize_warn_dimensions(
            parsed: List[Dict[str, Any]],
            warn_links: List[Dict[str, Any]],
            log_reduced_edges: Optional[List[Dict[str, Any]]] = None,
    ) -> List[RubricDimension]:
        """Enforce one ordered rubric dimension per multi-model WARN edge."""
        dimensions: List[RubricDimension] = []
        for index, edge in enumerate(warn_links):
            item = (
                parsed[index]
                if index < len(parsed) and isinstance(parsed[index], dict)
                else {}
            )
            source = str(edge.get("source", "")).strip()
            target = str(edge.get("target", "")).strip()
            expected_relation = RubricRefiner._expected_relation(edge)
            path_edges = []
            if expected_relation == "transitive_only":
                # F4: Record the complete authoritative log path for a
                # transitive_only dependency so repair can add bridge edges.
                path_edges = RubricRefiner._shortest_log_path(
                    log_reduced_edges, source, target
                )
            relation_descriptions = {
                "required_direct": (
                    f"The direct dependency {source} -> {target} must be present."
                ),
                "transitive_only": (
                    f"{source} must reach {target} through intermediate steps, "
                    "and the redundant direct edge must be absent."
                ),
                "forbidden": (
                    f"The unsupported direct dependency {source} -> {target} "
                    "must be absent."
                ),
            }
            tips = item.get("tips")
            if not isinstance(tips, list) or not tips:
                tips = [
                    f"Verify whether {source} must complete before {target}.",
                    f"Check whether the DAG contains exactly the required {source} to {target} dependency.",
                ]
            tips = [
                f"Expected relation: {expected_relation.replace('_', ' ')}.",
                *[str(tip) for tip in tips],
            ][:3]
            try:
                weight = min(3.0, max(0.1, float(item.get("weight", 1.5))))
            except (TypeError, ValueError):
                weight = 1.5
            dimensions.append(
                RubricDimension(
                    source=source,
                    target=target,
                    expected_relation=expected_relation,
                    path_edges=path_edges,
                    theme=str(
                        item.get("theme")
                        or f"{source} to {target} Dependency Correctness"
                    ),
                    description=(
                        f"{relation_descriptions[expected_relation]} "
                        + str(
                            item.get("description")
                            or "Evaluate this dependency according to the user request."
                        )
                    ),
                    tips=tips,
                    weight=weight,
                )
            )
        return dimensions

    def _safe_parse_json(self, text: str):
        """
        Safely parse JSON returned by an LLM.
        """
        import json
        import re

        if not text:
            return None

        text = text.strip()

        # Remove Markdown code fences.
        text = re.sub(r"^```json", "", text)
        text = re.sub(r"^```", "", text)
        text = re.sub(r"```$", "", text)
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try to extract an array.
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        # Try to extract an object.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass

        return None
