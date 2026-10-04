"""
DAG Evaluator - Core Phase 4 component.
Evaluates DAG quality with a refined rubric.
"""

from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import json
import math
from pathlib import Path

import json_repair

from src.llm_factory import LLMFactory, Message
from src.rubric_generator import Rubric, RubricDimension
from src.evaluation.dag_evidence_tool import evaluate_dag_evidence
from src.utils import (
    ToolDescriptionLoader,
    format_selected_api_metadata,
    get_prompt_manager,
)


@dataclass
class DimensionScore:
    """Score for one rubric dimension."""
    dimension_name: str
    score: float  # Scale from 1 to 5.
    weight: float
    weighted_score: float  # score * weight
    reasoning: str  # Rationale for the score.
    evidence_checks: List[Dict[str, Any]] = field(default_factory=list)
    evidence_verification: str = "not_checked"


@dataclass
class EvaluationResult:
    """Evaluation result."""
    task_id: str
    task_description: str

    # Scores by dimension.
    dimension_scores: List[DimensionScore]

    # Aggregate scores.
    total_weighted_score: float
    normalized_score: float  # Normalized to the 1-5 scale.

    # Evaluation metadata.
    rubric_metadata: Optional[Dict] = None
    evaluator_model: Optional[str] = None
    evaluation_timestamp: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert the result to a dictionary."""
        return {
            'task_id': self.task_id,
            'task_description': self.task_description,
            'dimension_scores': [
                {
                    'dimension_name': ds.dimension_name,
                    'score': ds.score,
                    'weight': ds.weight,
                    'weighted_score': ds.weighted_score,
                    'reasoning': ds.reasoning,
                    'evidence_checks': ds.evidence_checks,
                    'evidence_verification': ds.evidence_verification,
                }
                for ds in self.dimension_scores
            ],
            'total_weighted_score': self.total_weighted_score,
            'normalized_score': self.normalized_score,
            'rubric_metadata': self.rubric_metadata,
            'evaluator_model': self.evaluator_model,
            'evaluation_timestamp': self.evaluation_timestamp
        }


class DAGEvaluator:
    """DAG evaluator."""

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        stage: str = 'evaluation',
        tool_desc_path: Optional[str] = None,
        prompts_dir: str = "prompts"
    ):
        """
        Initialize the evaluator.

        Args:
            provider: LLM provider, or ``None`` to use configuration.
            model: Model name, or ``None`` to use configuration.
            stage: Configuration stage; defaults to ``evaluation``.
            tool_desc_path: Path to the tool-description file.
            prompts_dir: Prompt directory path.
        """
        # Create the LLM client.
        if provider is None and model is None:
            self.llm = LLMFactory.get_rubric_client(stage)
            config = LLMFactory.get_rubric_generator_config(stage)
            self.provider = config['provider']
            self.model = config['model']
        else:
            self.llm = LLMFactory.get_client(provider, model)
            self.provider = provider
            self.model = model

        # Load tool descriptions.
        self.tool_loader = ToolDescriptionLoader(tool_desc_path)
        self.tools = self.tool_loader.get_all_tools()

        # Initialize the prompt manager.
        self.prompt_manager = get_prompt_manager(prompts_dir)

    async def evaluate_dag(
        self,
        task: Dict,
        rubric: Rubric,
        include_reasoning: bool = True,
        conformance_results: Optional[Dict] = None,
        prompt_type: str = 'task_specific'
    ) -> EvaluationResult:
        """
        Evaluate one DAG task.

        Args:
            task: Task data including user_request, task_steps, and task_nodes.
            rubric: Refined Rubric
            include_reasoning: Whether to include scoring rationale.

        Returns:
            Evaluation result.
        """
        from datetime import datetime

        dimension_scores = []

        # Evaluate one dimension per LLM call to improve quality and consistency.
        for i, dim in enumerate(rubric.dimensions):
            print(f"  [Evaluating] Dimension {i+1}/{len(rubric.dimensions)}: {dim.theme}")

            deterministic_score = (
                self._evaluate_expected_dependency(task, dim, include_reasoning)
                if prompt_type == 'task_specific'
                else None
            )
            if deterministic_score is not None:
                dimension_scores.append(deterministic_score)
                continue

            prompt = self._build_evaluation_prompt(
                task, rubric, conformance_results, single_dimension=dim,
                prompt_type=prompt_type
            )

            verified_score = None
            last_score = None
            last_errors = []
            evaluation_prompt = prompt
            for attempt in range(2):
                messages = [Message(role="user", content=evaluation_prompt)]
                try:
                    response = await self.llm.acomplete(
                        messages,
                        temperature=0.0,
                        max_tokens=2000,
                    )
                    scores = self._parse_evaluation_response(
                        response.content,
                        [dim],
                        include_reasoning,
                    )
                    last_score = scores[0] if scores else None
                    if last_score is not None:
                        verified, last_errors = self._verify_score_evidence(
                            task, last_score
                        )
                        if verified:
                            verified_score = last_score
                            break
                    else:
                        last_errors = [
                            "The evaluation response could not be parsed."
                        ]
                except Exception as exc:
                    print(
                        f"  [ERROR] Dimension '{dim.theme}' evaluation attempt "
                        f"{attempt + 1} failed: {exc}"
                    )
                    last_errors = [f"Evaluation error: {exc}"]

                if attempt == 0:
                    evaluation_prompt = (
                        prompt + self._evidence_retry_instruction(last_errors)
                    )

            if verified_score is not None:
                dimension_scores.append(verified_score)
            else:
                print(
                    f"  [WARN] Dimension '{dim.theme}' failed deterministic "
                    "DAG evidence verification; using neutral score 3.0"
                )
                dimension_scores.append(
                    DimensionScore(
                        dimension_name=dim.theme,
                        score=3.0,
                        weight=dim.weight,
                        weighted_score=3.0 * dim.weight,
                        reasoning=(
                            "The evaluation could not be accepted because its DAG "
                            "evidence conflicted with the authoritative workflow "
                            "structure. A neutral score is used for this dimension."
                        ),
                        evidence_checks=(
                            last_score.evidence_checks if last_score else []
                        ),
                        evidence_verification="failed",
                    )
                )

        # Calculate totals from the dimensions that were actually evaluated.
        if dimension_scores:
            normalized_score = sum(ds.score for ds in dimension_scores) / len(dimension_scores)
        else:
            normalized_score = 0

        # Preserve source data in the evaluation metadata.
        total_weight = sum(dim.weight for dim in rubric.dimensions)
        total_weighted_score = sum(ds.weighted_score for ds in dimension_scores)

        # Build the result.
        result = EvaluationResult(
            task_id=task['id'],
            task_description=task.get('user_request', ''),
            dimension_scores=dimension_scores,
            total_weighted_score=total_weighted_score,
            normalized_score=normalized_score,
            rubric_metadata=rubric.metadata,
            evaluator_model=f"{self.provider}/{self.model}",
            evaluation_timestamp=datetime.now().isoformat()
        )

        return result

    @staticmethod
    def _has_indirect_path(
        edges: set[Tuple[str, str]], source: str, target: str
    ) -> bool:
        """Return whether source reaches target without using their direct edge."""
        adjacency: Dict[str, List[str]] = {}
        for edge_source, edge_target in edges:
            if (edge_source, edge_target) == (source, target):
                continue
            adjacency.setdefault(edge_source, []).append(edge_target)
        frontier = list(adjacency.get(source, []))
        visited = {source}
        while frontier:
            node = frontier.pop(0)
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            frontier.extend(adjacency.get(node, []))
        return False

    @staticmethod
    def _reasoning_graph_conflicts(
        task: Dict[str, Any], reasoning: str
    ) -> List[str]:
        """Catch explicit edge claims that contradict the authoritative DAG.

        Structured evidence is the primary contract.  This small text guard is
        a second line of defence for an LLM that supplies a harmless evidence
        check but writes a contradictory missing/present edge claim in prose.
        """
        import re

        text = str(reasoning or "")
        if not text:
            return []
        lowered = text.lower()
        nodes = sorted(
            {
                str(
                    node.get("task")
                    or node.get("name")
                    or node.get("label")
                    or node.get("id")
                    or ""
                ).strip()
                for node in task.get("task_nodes", [])
                if isinstance(node, dict)
            }
            - {""},
            key=len,
            reverse=True,
        )
        edges = {
            (
                str(link.get("source", "")).strip(),
                str(link.get("target", "")).strip(),
            )
            for link in task.get("task_links", [])
            if isinstance(link, dict)
            and link.get("source")
            and link.get("target")
        }
        negative_terms = re.compile(
            r"\b(missing|absent|lacks?|omits?|omitted|without|not present|"
            r"does not (?:contain|include|have)|no direct)\b"
        )
        positive_terms = re.compile(
            r"\b(exists?|present|contains?|includes?|has|listed)\b"
        )
        conflicts = []
        for source in nodes:
            for target in nodes:
                if source == target:
                    continue
                source_pattern = re.escape(source.lower())
                target_pattern = re.escape(target.lower())
                patterns = (
                    rf"{source_pattern}\s*(?:-|=)?(?:>|→)\s*{target_pattern}",
                    rf"(?:edge|dependency|link|path)\s+from\s+{source_pattern}"
                    rf"\s+to\s+{target_pattern}",
                )
                for pattern in patterns:
                    for match in re.finditer(pattern, lowered):
                        window = lowered[
                            max(0, match.start() - 110):
                            min(len(lowered), match.end() + 110)
                        ]
                        claims_absent = bool(negative_terms.search(window))
                        claims_present = (
                            not claims_absent
                            and bool(positive_terms.search(window))
                        )
                        matched_text = match.group(0)
                        preceding = lowered[max(0, match.start() - 30):match.start()]
                        is_path_claim = (
                            "path" in matched_text
                            or bool(re.search(r"\bpath\s*$", preceding))
                        )
                        actual = (
                            (source, target) in edges
                            or DAGEvaluator._has_indirect_path(
                                edges, source, target
                            )
                            if is_path_claim
                            else (source, target) in edges
                        )
                        if claims_absent and actual:
                            conflicts.append(
                                f"The reasoning says {source} -> {target} is absent, "
                                "but the authoritative DAG contains that relation."
                            )
                        elif claims_present and not actual:
                            conflicts.append(
                                f"The reasoning says {source} -> {target} is present, "
                                "but the authoritative DAG does not contain that relation."
                            )
        return list(dict.fromkeys(conflicts))

    @classmethod
    def _verify_score_evidence(
        cls,
        task: Dict[str, Any],
        score: DimensionScore,
    ) -> Tuple[bool, List[str]]:
        """Run the deterministic DAG Evidence Tool for one LLM score."""
        verification = evaluate_dag_evidence(task, score.evidence_checks)
        score.evidence_checks = verification["checks"]
        errors: List[str] = []
        if not verification["checks"]:
            errors.append(
                "No structured DAG evidence was supplied for this evaluation."
            )
        for check in verification["checks"]:
            if check.get("valid"):
                continue
            if check.get("error"):
                errors.append(
                    f"Evidence check {check.get('index')} is invalid: "
                    f"{check.get('error')}."
                )
            else:
                subject = check.get("node") or (
                    f"{check.get('source')} -> {check.get('target')}"
                )
                errors.append(
                    f"{check.get('predicate')} for {subject} is "
                    f"{check.get('actual')}, not {check.get('observed')}."
                )
        errors.extend(cls._reasoning_graph_conflicts(task, score.reasoning))
        score.evidence_verification = "verified" if not errors else "failed"
        return not errors, list(dict.fromkeys(errors))

    @staticmethod
    def _evidence_retry_instruction(errors: List[str]) -> str:
        return (
            "\n\n## DAG Evidence Verification Tool Feedback\n\n"
            "The previous evaluation contained graph facts that could not be "
            "verified. Re-evaluate the same rubric dimension using these "
            "deterministic corrections:\n- "
            + "\n- ".join(errors)
            + "\nReturn the complete JSON object again. Every graph fact in the "
            "reasoning must have a matching evidence_checks entry whose observed "
            "value agrees with the authoritative DAG."
        )

    @classmethod
    def _evaluate_expected_dependency(
        cls,
        task: Dict,
        dimension: RubricDimension,
        include_reasoning: bool = True,
    ) -> Optional[DimensionScore]:
        """Deterministically score a dependency fixed by the v1 review."""
        relation = str(dimension.expected_relation or "").lower()
        if relation not in {"required_direct", "transitive_only", "forbidden"}:
            return None
        source = str(dimension.source).strip()
        target = str(dimension.target).strip()
        if not source or not target:
            return None
        edges = {
            (
                str(link.get("source", "")).strip(),
                str(link.get("target", "")).strip(),
            )
            for link in task.get("task_links", [])
            if link.get("source") and link.get("target")
        }
        direct_present = (source, target) in edges
        indirect_present = cls._has_indirect_path(edges, source, target)

        if relation == "required_direct":
            passed = direct_present
            score = 5.0 if passed else 1.0
            reasoning = (
                f"The fixed v1 rubric requires the direct dependency {source} -> "
                f"{target}. The current DAG {'contains' if passed else 'does not contain'} "
                "that exact edge, so the reviewed ordering requirement is "
                f"{'fully satisfied' if passed else 'violated'}."
            )
        elif relation == "transitive_only":
            passed = indirect_present and not direct_present
            if passed:
                score = 5.0
                outcome = (
                    "contains an indirect path through intermediate steps and omits "
                    "the redundant direct edge"
                )
            elif direct_present:
                score = 2.0
                outcome = "still contains the redundant direct edge"
            else:
                score = 1.0
                outcome = "contains neither the required indirect path nor a valid ordering"
            reasoning = (
                f"The fixed v1 rubric requires {source} to precede {target} only "
                f"transitively. The current DAG {outcome}, so the reviewed dependency "
                f"is {'represented correctly' if passed else 'represented incorrectly'}."
            )
        else:
            passed = not direct_present
            score = 5.0 if passed else 1.0
            reasoning = (
                f"The fixed v1 rubric marks the direct dependency {source} -> {target} "
                f"as unsupported. The current DAG {'omits' if passed else 'contains'} "
                f"that edge, so the requirement is {'fully satisfied' if passed else 'violated'}."
            )

        raw_evidence = [
            {
                "predicate": "direct_edge_exists",
                "source": source,
                "target": target,
                "observed": direct_present,
            }
        ]
        if relation == "transitive_only":
            raw_evidence.append(
                {
                    "predicate": "path_exists",
                    "source": source,
                    "target": target,
                    "observed": direct_present or indirect_present,
                }
            )
        verified_evidence = evaluate_dag_evidence(task, raw_evidence)
        return DimensionScore(
            dimension_name=dimension.theme,
            score=score,
            weight=dimension.weight,
            weighted_score=score * dimension.weight,
            reasoning=reasoning if include_reasoning else "",
            evidence_checks=verified_evidence["checks"],
            evidence_verification="deterministic",
        )

    def _build_evaluation_prompt(self, task: Dict, rubric: Rubric, conformance_results: Optional[Dict] = None, single_dimension: Optional[RubricDimension] = None, prompt_type: str = 'task_specific') -> str:
        """Build an evaluation prompt, optionally for one dimension.

        Args:
            prompt_type: ``task_specific`` uses the full prompt with log and
                tool validation; ``generic`` evaluates only workflow content.
        """

        # Extract task information.
        user_request = task.get('user_request', '')
        task_steps = task.get('task_steps', [])
        task_nodes = task.get('task_nodes', [])
        task_links = task.get('task_links', [])

        # Select either the requested dimension or every dimension.
        eval_dimensions = [single_dimension] if single_dimension else rubric.dimensions

        # Build rubric description
        rubric_desc = "## Evaluation Criteria (Rubric)\n\n"
        for i, dim in enumerate(eval_dimensions, 1):
            rubric_desc += f"### {i}. {dim.theme} (Weight: {dim.weight})\n\n"
            if dim.source and dim.target:
                rubric_desc += (
                    f"**Target Dependency**: {dim.source} -> {dim.target}\n\n"
                )
            if dim.expected_relation:
                rubric_desc += (
                    f"**Expected Relation**: {dim.expected_relation}\n\n"
                )
            rubric_desc += f"**Evaluation Focus**: {dim.description}\n\n"
            if dim.tips:
                rubric_desc += "**Checklist**:\n"
                for tip in dim.tips:
                    rubric_desc += f"- {tip}\n"
            rubric_desc += "\n"

        # Build DAG description
        dag_desc = "## DAG Task Structure\n\n"
        dag_desc += f"**User Request**: {user_request}\n\n"
        dag_desc += f"**Task Steps**: {len(task_steps)}\n"
        dag_desc += f"**Nodes**: {len(task_nodes)}\n"
        dag_desc += f"**Links**: {len(task_links)}\n\n"

        dag_desc += "### Task Step Details\n\n"
        for i, step in enumerate(task_steps, 1):
            if isinstance(step, dict):
                step_name = step.get('name', f'Step {i}')
                step_desc = step.get('description', 'N/A')
                step_tool = step.get('tool', 'N/A')
                step_input = step.get('input_types', [])
                step_output = step.get('output_types', [])

                dag_desc += f"{i}. **{step_name}**\n"
                dag_desc += f"   - Description: {step_desc}\n"
                dag_desc += f"   - Tool: {step_tool}\n"
                dag_desc += f"   - Input: {step_input}\n"
                dag_desc += f"   - Output: {step_output}\n\n"
            elif isinstance(step, str):
                # The step is represented as a string.
                dag_desc += f"{i}. {step}\n\n"
            else:
                dag_desc += f"{i}. (Unknown format)\n\n"

        # Generic mode uses workflow content without log or tool validation.
        dag_desc += "### DAG Nodes (Authoritative)\n\n"
        for i, node in enumerate(task_nodes, 1):
            if isinstance(node, dict):
                node_name = node.get('task') or node.get('name') or f'Node {i}'
                arguments = node.get('arguments', [])
                dag_desc += f"{i}. **{node_name}**; arguments={arguments}\n"
            else:
                dag_desc += f"{i}. {node}\n"

        dag_desc += "\n### Dependency Links (Authoritative)\n\n"
        if task_links:
            for link in task_links:
                dag_desc += (
                    f"- **{link.get('source', '')} -> {link.get('target', '')}**\n"
                )
        else:
            dag_desc += "- (no dependency links)\n"
        dag_desc += (
            "\nOnly the dependency links explicitly listed above exist in the "
            "current DAG. Do not infer missing or additional edges.\n\n"
        )

        if prompt_type == 'generic':
            api_metadata = format_selected_api_metadata(
                task.get('api_list')
                or task.get('candidate_api_list')
                or task.get('sampled_nodes'),
                task_nodes,
            )
            return self.prompt_manager.get_generic_evaluation_prompt(
                rubric_description=rubric_desc,
                dag_description=dag_desc,
                api_metadata=api_metadata,
                num_dimensions=len(eval_dimensions),
            )

        # Task-specific mode includes tool validation, log conformance, and
        # dependency discrepancy analysis.
        tool_validation = self._validate_tool_usage(task)

        # Build log conformance description with dependency gap analysis (Stage 2 validate-with-log results)
        conformance_desc = self._build_conformance_description(conformance_results, task_links)

        # Prepare dimension-name parameters.
        dimension_params = {}
        for i, dim in enumerate(eval_dimensions):
            dimension_params[f'dimension_{i+1}'] = dim.theme

        # Build the prompt through PromptManager.
        return self.prompt_manager.get_evaluation_prompt(
            rubric_description=rubric_desc,
            dag_description=dag_desc,
            tool_validation=tool_validation,
            conformance_analysis=conformance_desc,
            num_dimensions=len(eval_dimensions),
            **dimension_params
        )

    def _build_conformance_description(self, conformance_results: Optional[Dict], workflow_links: List[Dict] = None) -> str:
        """Format log conformance validation results (validate-with-log) into readable text for the prompt.

        Includes a Dependency Gap Analysis that compares ground-truth pass edges
        (from execution logs) against the actual edges present in the workflow
        being evaluated. This ensures the LLM can detect MISSING critical dependencies.
        """
        if not conformance_results:
            return "(No log conformance validation results provided)"

        conf_links = conformance_results.get("task_links", [])
        trace_count = conformance_results.get("trace_count", 0)

        if not conf_links:
            return "(Log conformance validation results are empty)"

        pass_count = sum(1 for e in conf_links if e.get("status") == "pass")
        warn_count = sum(1 for e in conf_links if e.get("status") == "warn")

        type_map = {"direct": "Direct Support", "transitive": "Transitive Redundancy", "unsupported": "Unsupported"}

        # ---- Part 1: Edge Validation Table ----
        desc = "### Log Conformance Validation (Ground Truth from Execution Logs)\n\n"
        desc += f"**Total execution log traces**: {trace_count}\n"
        desc += f"**Validated edges**: {len(conf_links)} (pass={pass_count}, warn={warn_count})\n\n"
        desc += "#### Edge Validation Details\n\n"
        desc += "| Source | Target | Status | Log Support Rate | Supporting Traces | Edge Type |\n"
        desc += "|--------|--------|--------|-----------------|-------------------|-----------|\n"
        for edge in conf_links:
            source = edge.get("source", "")
            target = edge.get("target", "")
            status = edge.get("status", "")
            support_rate = edge.get("log_support_rate", "")
            trace_cnt = edge.get("log_trace_count", "")
            edge_type = edge.get("log_edge_type", "")
            edge_type_label = type_map.get(edge_type, edge_type)
            desc += f"| {source} | {target} | {status} | {support_rate} | {trace_cnt} | {edge_type_label} |\n"

        desc += "\n> **Edge Status Legend**:\n"
        desc += "> - **pass**: The log directly supports this dependency — this dependency is CONFIRMED as required by ground truth\n"
        desc += "> - **warn (Transitive Redundancy)**: The edge exists in the precedence graph but was removed by transitive reduction — it is an indirect dependency\n"
        desc += "> - **warn (Unsupported)**: No execution evidence for this dependency was found in the log\n"

        # ---- Part 2: Dependency Gap Analysis ----
        if workflow_links:
            # Build sets for comparison
            wf_edge_set = {
                (e.get("source", ""), e.get("target", ""))
                for e in workflow_links
            }
            gt_pass_edges = [
                (e.get("source", ""), e.get("target", ""))
                for e in conf_links if e.get("status") == "pass"
            ]
            gt_all_set = {
                (e.get("source", ""), e.get("target", ""))
                for e in conf_links
            }

            # Missing: ground truth pass edges NOT present in the workflow being evaluated
            missing_edges = [(s, t) for s, t in gt_pass_edges if (s, t) not in wf_edge_set]
            # Matched: ground truth pass edges that ARE present in the workflow
            matched_edges = [(s, t) for s, t in gt_pass_edges if (s, t) in wf_edge_set]
            # Extra: workflow edges NOT validated by ground truth at all
            extra_edges = [(s, t) for s, t in wf_edge_set if (s, t) not in gt_all_set]

            desc += f"\n### Dependency Gap Analysis (Ground Truth vs Evaluated Workflow)\n\n"
            desc += f"- **Ground-truth confirmed dependencies (pass)**: {len(gt_pass_edges)}\n"
            desc += f"- **Matched (present in workflow)**: {len(matched_edges)}\n"
            desc += f"- **MISSING (required but absent)**: {len(missing_edges)}\n"
            desc += f"- **Extra (in workflow but not ground-truth)**: {len(extra_edges)}\n"

            if missing_edges:
                desc += "\n#### ⚠️ CRITICAL: Missing Required Dependencies\n\n"
                desc += "The following dependencies are **confirmed by execution logs (ground truth)** "
                desc += "but are **ABSENT from the workflow being evaluated**. "
                desc += "These missing edges represent **critical structural defects**:\n\n"
                for s, t in missing_edges:
                    desc += f"- **{s} → {t}** (confirmed by logs, but NOT in workflow)\n"

            if extra_edges:
                desc += "\n#### Extra Dependencies (Not Validated by Logs)\n\n"
                desc += "The following edges exist in the workflow but were **not validated by execution logs**. "
                desc += "They may be unnecessary or incorrectly inferred:\n\n"
                for s, t in extra_edges:
                    desc += f"- {s} → {t}\n"

            # Explicit scoring guidance
            desc += "\n### Scoring Guidance Based on Dependency Gap\n\n"
            if missing_edges:
                desc += "**⚠️ CRITICAL DEFECT DETECTED**: The workflow is missing "
                desc += f"{len(missing_edges)} ground-truth confirmed "
                desc += ("dependency" if len(missing_edges) == 1 else "dependencies") + ".\n\n"
                desc += "When scoring, you MUST:\n"
                desc += "- **Heavily deduct** from **Structural Integrity & Dependency Logic** (missing a confirmed dependency is a severe structural flaw)\n"
                desc += "- **Deduct** from any dimension related to the missing dependency's data flow "
                desc += "(e.g., if a data-integrity dimension covers the missing edge's source→target flow, "
                desc += "score it at most 2)\n"
                desc += "- A workflow missing confirmed dependencies **cannot score above 3** "
                desc += "on dependency-related dimensions regardless of other qualities\n"
            else:
                desc += "All ground-truth confirmed dependencies are present in the workflow. "
                desc += "This is a positive signal for structural integrity.\n"

        return desc

    def _validate_tool_usage(self, task: Dict) -> str:
        """Validate tool usage."""
        task_nodes = task.get('task_nodes', [])
        task_links = task.get('task_links', [])

        validation_results = []
        total_links = len(task_links)
        valid_links = 0
        invalid_links = 0
        missing_tools = []

        # Validate type compatibility for every edge.
        for link in task_links:
            source_tool = link.get('source', '')
            target_tool = link.get('target', '')

            # Resolve source and target nodes by task name.
            source_node = next((node for node in task_nodes if node.get('task') == source_tool), None)
            target_node = next((node for node in task_nodes if node.get('task') == target_tool), None)

            if not source_node:
                invalid_links += 1
                validation_results.append(f"[!] Source tool not found in nodes: {source_tool}")
                continue

            if not target_node:
                invalid_links += 1
                validation_results.append(f"[!] Target tool not found in nodes: {target_tool}")
                continue

            # Check whether both tools exist in the description registry.
            if source_tool not in self.tools:
                missing_tools.append(source_tool)
                validation_results.append(f"[!] Tool description missing: {source_tool}")

            if target_tool not in self.tools:
                missing_tools.append(target_tool)
                validation_results.append(f"[!] Tool description missing: {target_tool}")

            # Validate type compatibility.
            if source_tool in self.tools and target_tool in self.tools:
                source_desc = self.tools[source_tool]
                target_desc = self.tools[target_tool]

                # Check whether source outputs match target inputs.
                is_compatible = False
                for output_type in source_desc.output_types:
                    if target_desc.accepts_input(output_type):
                        is_compatible = True
                        break

                if is_compatible:
                    valid_links += 1
                else:
                    invalid_links += 1
                    validation_results.append(
                        f"[X] Type mismatch: {source_tool} ({', '.join(source_desc.output_types)}) -> "
                        f"{target_tool} (needs: {', '.join(target_desc.input_types)})"
                    )

        # Build the validation report.
        report = f"**Total connections**: {total_links}\n"
        report += f"**Valid connections**: {valid_links}\n"
        report += f"**Invalid connections**: {invalid_links}\n"

        if missing_tools:
            unique_missing = list(set(missing_tools))
            report += f"\n**Missing tool descriptions**: {len(unique_missing)}\n"
            for tool in unique_missing[:5]:  # Show max 5
                report += f"   - {tool}\n"

        if invalid_links > 0:
            report += f"\n**Type mismatch details**:\n"
            for result in validation_results[:10]:  # Show max 10
                if '[X]' in result:
                    report += f"   {result}\n"

        if valid_links == total_links and total_links > 0:
            report += f"\n**Validation result**: [OK] All tool connections are type-compatible"
        elif invalid_links > 0:
            report += f"\n**Validation result**: [!] Found {invalid_links} type mismatch issues"

        return report

    def _parse_evaluation_response(
        self,
        response_content: str,
        dimensions: List[RubricDimension],
        include_reasoning: bool
    ) -> List[DimensionScore]:
        """Parse an LLM evaluation response with layered fallbacks."""

        # Map dimension names to dimension definitions.
        dim_map = {dim.theme: dim for dim in dimensions}

        # Attempt standard JSON parsing.
        result = self._try_parse_json(response_content, dim_map, include_reasoning)
        if result:
            return result

        # Repair common errors before another parse attempt.
        fixed_json = self._fix_json_advanced(response_content)
        result = self._try_parse_json(fixed_json, dim_map, include_reasoning)
        if result:
            return result

        # Fall back to regex extraction, which is robust but less precise.
        result = self._parse_with_regex(response_content, dim_map, include_reasoning)
        if result:
            return result

        # Return default scores when every parser fails.
        print(f"[WARNING] All parsing methods failed, using default scores")
        return [
            DimensionScore(
                dimension_name=dim.theme,
                score=3.0,
                weight=dim.weight,
                weighted_score=3.0 * dim.weight,
                reasoning="Parsing failed"
            )
            for dim in dimensions
        ]

    def _try_parse_json(
        self,
        json_str: str,
        dim_map: Dict,
        include_reasoning: bool
    ) -> Optional[List[DimensionScore]]:
        """Attempt to parse JSON."""
        try:
            # Extract the JSON portion.
            json_str = json_str.strip()

            # Remove Markdown code fences.
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            # json_repair tolerates malformed JSON returned by an LLM.
            data = json_repair.loads(json_str)

            # Handle supported return types.
            if isinstance(data, list):
                # Use a top-level array directly.
                evaluations = data
            elif isinstance(data, dict):
                # Extract the evaluations array from a dictionary.
                evaluations = data.get('evaluations', [])
            else:
                # Reject unknown types.
                print(f"  [DEBUG] Unexpected data type: {type(data)}")
                return None

            # Build parsed results.
            dimension_scores = []
            for eval_item in evaluations:
                if not isinstance(eval_item, dict):
                    continue
                dim_name = eval_item.get('dimension', '')
                score = float(eval_item.get('score', 3.0))
                if not math.isfinite(score) or not 1.0 <= score <= 5.0:
                    print(
                        f"  [DEBUG] Invalid score for '{dim_name}': {score}"
                    )
                    continue
                reasoning = eval_item.get('reasoning', '') if include_reasoning else ''
                evidence_checks = eval_item.get('evidence_checks', [])
                if not isinstance(evidence_checks, list):
                    evidence_checks = []

                if dim_name in dim_map:
                    dimension = dim_map[dim_name]
                    weighted_score = score * dimension.weight
                    dimension_scores.append(DimensionScore(
                        dimension_name=dim_name,
                        score=score,
                        weight=dimension.weight,
                        weighted_score=weighted_score,
                        reasoning=reasoning,
                        evidence_checks=evidence_checks,
                    ))

            # Ensure every dimension received an evaluation.
            if dimension_scores:
                return dimension_scores
            else:
                print(f"  [DEBUG] No dimensions found in parsed data")
                return None

        except Exception as e:
            # Print the first 200 characters for diagnostics.
            preview = json_str[:200] if json_str else "empty"
            print(f"  [DEBUG] json_repair failed: {e}")
            print(f"  [DEBUG] JSON preview: {preview}...")
            return None

    def _fix_json_advanced(self, response_content: str) -> str:
        """Apply advanced JSON repairs."""
        import re

        # Extract the JSON portion.
        json_str = response_content.strip()

        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0].strip()
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0].strip()

        # Escape special characters in reasoning fields.
        def escape_reasoning(content):
            """Escape a reasoning field."""
            # Escape special characters.
            content = content.replace('\\', '\\\\')  # Backslash.
            content = content.replace('"', '\\"')     # Double quote.
            content = content.replace("'", "\\'")     # Single quote.
            content = content.replace('\n', ' ')     # Replace newline with a space.
            content = content.replace('\r', ' ')     # Replace carriage return with a space.
            content = content.replace('\t', ' ')     # Replace tab with a space.
            # Limit field length.
            if len(content) > 500:
                content = content[:500] + "..."
            return f'"{content}"'

        # Replace reasoning values with the escaped form.
        json_str = re.sub(
            r'"reasoning":\s*"((?:[^"\\]|\\.)*)"(?=\s*[},])',
            lambda m: f'"reasoning": {escape_reasoning(m.group(1))}',
            json_str,
            flags=re.DOTALL
        )

        # Remove unclosed strings.
        lines = json_str.split('\n')
        fixed_lines = []
        for line in lines:
            # A long line with an odd quote count may have been truncated.
            if len(line) > 500 and line.count('"') % 2 != 0:
                # Find the last complete evaluation item.
                last_complete = line.rfind('},')
                if last_complete > 0:
                    line = line[:last_complete + 2]
            fixed_lines.append(line)

        json_str = '\n'.join(fixed_lines)

        # Remove control characters.
        json_str = ''.join(
            char for char in json_str
            if char.isprintable() or char in '\n\r\t'
        )

        return json_str

    def _parse_with_regex(
        self,
        response_content: str,
        dim_map: Dict,
        include_reasoning: bool
    ) -> Optional[List[DimensionScore]]:
        """Extract evaluation data with a defensive regex fallback."""
        import re

        try:
            # Extract the JSON portion.
            json_str = response_content.strip()

            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()

            # Extract each item matching dimension, score, and reasoning fields.
            pattern = r'"dimension":\s*"([^"]+)"\s*,\s*"score":\s*([0-9.]+)\s*,\s*"reasoning":\s*"([^"]*)"'

            matches = re.findall(pattern, json_str, re.DOTALL)

            if not matches:
                return None

            dimension_scores = []
            for match in matches:
                dim_name = match[0]
                score = float(match[1])
                reasoning = match[2] if include_reasoning else ''

                if dim_name in dim_map:
                    dimension = dim_map[dim_name]
                    weighted_score = score * dimension.weight
                    dimension_scores.append(DimensionScore(
                        dimension_name=dim_name,
                        score=score,
                        weight=dimension.weight,
                        weighted_score=weighted_score,
                        reasoning=reasoning[:500] if len(reasoning) > 500 else reasoning
                    ))

            if dimension_scores:
                return dimension_scores
            else:
                return None

        except Exception as e:
            return None
