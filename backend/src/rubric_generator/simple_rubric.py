"""
Simple Rubric Generator
Generates evaluation criteria from task descriptions using OpenJudge's simple-rubric method.
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
import re
import json

from ..llm_factory.factory import LLMFactory
from ..llm_factory.base import Message
from ..utils import (
    ToolDescriptionLoader,
    build_tool_library_information,
    get_prompt_manager,
)


@dataclass
class RubricDimension:
    """Evaluation dimension."""

    theme: str  # Theme, such as logical correctness.
    tips: List[str]  # Concrete checks.
    weight: float = 1.0  # Relative weight.
    description: str = ""  # Dimension description.
    source: str = ""
    target: str = ""
    expected_relation: str = ""
    # Authoritative log path for a transitive_only dimension: the shortest
    # path in the XES transitive reduction, for example
    # [{"source": "Collect", "target": "Guide"},
    #  {"source": "Guide", "target": "Provide quote"}].
    # Evaluation and repair use it to identify missing bridge edges and commit
    # each removal with its paired addition as one atomic group in Workflow 199.
    path_edges: List[Dict[str, str]] = field(default_factory=list)


@dataclass
class Rubric:
    """Complete rubric."""

    task_id: str
    task_description: str
    dimensions: List[RubricDimension]
    min_score: int = 0
    max_score: int = 5
    metadata: Dict = None

    def to_dict(self) -> Dict:
        """Convert the rubric to a dictionary."""
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "dimensions": [
                {
                    "theme": dim.theme,
                    "tips": dim.tips,
                    "weight": dim.weight,
                    "description": dim.description,
                    "source": dim.source,
                    "target": dim.target,
                    "expected_relation": dim.expected_relation,
                    "path_edges": dim.path_edges,
                }
                for dim in self.dimensions
            ],
            "min_score": self.min_score,
            "max_score": self.max_score,
            "metadata": self.metadata or {},
        }

    def to_markdown(self) -> str:
        """Convert the rubric to Markdown."""
        lines = [
            f"# Evaluation Rubric for Task: {self.task_id}",
            "",
            f"**Task Description:** {self.task_description}",
            "",
            f"**Score Range:** {self.min_score} - {self.max_score}",
            "",
            "## Evaluation Dimensions",
            "",
        ]

        for i, dim in enumerate(self.dimensions, 1):
            lines.append(f"### Dimension {i}: {dim.theme} (weight: {dim.weight})")
            if dim.description:
                lines.append(f"*{dim.description}*")
            lines.append("")
            for tip in dim.tips:
                lines.append(f"- {tip}")
            lines.append("")

        return "\n".join(lines)


class SimpleRubricGenerator:
    """
    Simple-rubric generator based on OpenJudge.

    Uses zero-shot generation from a task description, asks an LLM to extract
    dimensions and checks, and returns a structured theme-tip rubric.
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        stage: str = "universal",
        tool_desc_path: Optional[str] = None,
        prompts_dir: str = "prompts",
    ):
        """
        Initialize the generator.

        Args:
            provider: LLM provider, or ``None`` to use configuration.
            model: Model name, or ``None`` to use configuration.
            stage: Generation stage (``universal``, ``draft``, or ``refinement``).
            tool_desc_path: Path to the tool-description file.
            prompts_dir: Prompt directory path.
        """
        # Use role configuration when provider and model are omitted.
        if provider is None and model is None:
            self.llm = LLMFactory.get_rubric_client(stage)
            config = LLMFactory.get_rubric_generator_config(stage)
            self.provider = config["provider"]
        else:
            role_config = LLMFactory.get_rubric_generator_config(stage)
            selected_provider = provider or role_config["provider"]
            selected_model = model or role_config.get("model")
            self.llm = LLMFactory.get_client(selected_provider, selected_model)
            self.provider = selected_provider

        self.stage = stage

        # Load tool descriptions.
        self.tool_loader = ToolDescriptionLoader(tool_desc_path)
        self.tools = self.tool_loader.get_all_tools()

        # Initialize the prompt manager.
        self.prompt_manager = get_prompt_manager(prompts_dir)

    async def generate_universal_rubric(
        self,
        dataset_stats: Optional[Dict] = None,
        task_domain: str = "workflow modeling",
        *,
        user_request: str = "",
        tool_library_info: Optional[Dict] = None,
    ) -> Rubric:
        """
        Generate a generic rubric grounded in one requirement and its tool library.

        Args:
            dataset_stats: Backward-compatible options; ``num_dimensions`` is used.
            task_domain: Task-domain description.
            user_request: Natural-language workflow requirement D.
            tool_library_info: Tool-library information T and modeling rules.

        Returns:
            Universal evaluation rubric.
        """
        dataset_stats = dataset_stats or {}
        prompt = self._get_universal_prompt(
            dataset_stats,
            task_domain,
            user_request=user_request,
            tool_library_info=tool_library_info,
        )

        messages = [
            Message(role="system", content=self._get_system_prompt()),
            Message(role="user", content=prompt),
        ]

        try:
            response = await self.llm.acomplete(
                messages, temperature=0.3, max_tokens=2000  # Favor deterministic output.
            )

            rubric = self._parse_rubric(response.content, task_id="universal")
            rubric.task_description = user_request
            rubric.metadata = {
                "type": "universal",
                "domain": task_domain,
                "knowledge_base": (tool_library_info or {}).get(
                    "collection_name", ""
                ),
                "tool_count": (tool_library_info or {}).get(
                    "tool_count", len(self.tools)
                ),
            }

            return rubric

        except Exception as e:
            print(f"Error generating universal rubric: {e}")
            # Fall back to the default universal rubric.
            return self._get_default_universal_rubric(
                task_domain,
                user_request=user_request,
            )

    async def generate_task_rubric(
        self, task: Dict, context: Optional[Dict] = None
    ) -> Rubric:
        """
        Generate a rubric for one task.

        Args:
            task: Task data.
                {
                    "id": str,
                    "user_request": str,
                    "task_steps": List[str],
                    "task_nodes": List[Dict],
                    "task_links": List[Dict],
                    "sampled_nodes": List[Dict]
                }
            context: Additional context.

        Returns:
            Task-specific evaluation rubric.
        """
        prompt = self._get_task_prompt(task, context)

        messages = [
            Message(role="system", content=self._get_system_prompt()),
            Message(role="user", content=prompt),
        ]

        try:
            response = await self.llm.acomplete(
                messages, temperature=0.3, max_tokens=2000
            )

            rubric = self._parse_rubric(
                response.content, task_id=task.get("id", "unknown")
            )
            rubric.task_description = task.get("user_request", "")
            rubric.metadata = {
                "type": "task_specific",
                "task_id": task.get("id"),
                "n_tools": task.get("n_tools"),
                "context": context,
            }

            return rubric

        except Exception as e:
            print(f"Error generating task rubric for {task.get('id')}: {e}")
            # Fall back to the default task rubric.
            return self._get_default_task_rubric(task)

    def _get_system_prompt(self) -> str:
        """Return the system prompt."""
        return self.prompt_manager.get_system_prompt()

    def _get_universal_prompt(
        self,
        stats: Dict,
        domain: str,
        *,
        user_request: str = "",
        tool_library_info: Optional[Dict] = None,
    ) -> str:
        """Build a Generic Rubric prompt from requirement D and tool evidence T."""
        library_info = tool_library_info or build_tool_library_information(
            self.tools,
            collection_name="",
            domain=domain,
        )
        return self.prompt_manager.get_universal_prompt(
            domain=domain,
            workflow_requirement=user_request or "(not provided)",
            tool_library_information=json.dumps(
                library_info,
                ensure_ascii=False,
                indent=2,
            ),
            num_dimensions=stats.get("num_dimensions", 4),
        )

    def _get_task_prompt(self, task: Dict, context: Optional[Dict]) -> str:
        """Build the task-specific rubric prompt."""
        # Prepare prompt parameters.
        params = {
            "user_request": task["user_request"],
            "task_steps": self._format_steps(task.get("task_steps", [])),
            "available_tools": self._format_tools(task.get("sampled_nodes", [])),
            "num_nodes": len(task.get("task_nodes", [])),
            "task_nodes": self._format_nodes(task.get("task_nodes", [])),
            "num_links": len(task.get("task_links", [])),
            "task_links": self._format_links(task.get("task_links", [])),
        }

        return self.prompt_manager.get_task_prompt(**params)

    def _format_steps(self, steps: List[str]) -> str:
        """Format task steps."""
        return "\n".join([f"{i+1}. {step}" for i, step in enumerate(steps)])

    def _format_tools(self, tools: List[Dict]) -> str:
        """Format the tool list with detailed descriptions."""
        formatted_tools = []
        for tool in tools[:10]:  # Limit displayed tools.
            tool_name = tool["task"]
            tool_desc = self.tools.get(tool_name)

            if tool_desc:
                # Include detailed information when a description is available.
                formatted_tools.append(
                    f"- **{tool_name}**: {tool_desc.desc}\n"
                    f"  Input: {', '.join(tool_desc.input_types)}\n"
                    f"  Output: {', '.join(tool_desc.output_types)}"
                )
            else:
                # Otherwise include basic information.
                input_types = tool.get("input-type", [])
                output_types = tool.get("output-type", [])
                formatted_tools.append(
                    f"- **{tool_name}**: input={input_types}, output={output_types}"
                )

        return "\n".join(formatted_tools)

    def _format_nodes(self, nodes: List[Dict]) -> str:
        """Format DAG nodes."""
        return "\n".join(
            [f"- {node['task']}: {node.get('arguments', [])}" for node in nodes[:10]]
        )

    def _format_links(self, links: List[Dict]) -> str:
        """Format DAG edges."""
        return "\n".join(
            [f"- {link['source']} → {link['target']}" for link in links[:10]]
        )

    def _parse_rubric(self, response: str, task_id: str) -> Rubric:
        """Parse a rubric returned by an LLM."""
        lines = response.strip().split("\n")
        dimensions = []
        current_theme = None
        current_description = None
        current_tips = []

        for line in lines:
            line_stripped = line.strip()

            # Detect the start of a dimension.
            if line_stripped.startswith("Dimension ") or line_stripped.startswith(
                "Theme:"
            ):
                # Save the preceding dimension.
                if current_theme and current_tips:
                    dimensions.append(
                        RubricDimension(
                            theme=current_theme,
                            tips=current_tips,
                            description=current_description or "",
                        )
                    )

                # Extract the new theme name.
                if "Theme:" in line_stripped:
                    current_theme = line_stripped.split("Theme:", 1)[1].strip()
                else:
                    current_theme = line_stripped
                current_description = None
                current_tips = []

            # Detect a description.
            elif line_stripped.startswith("Description:"):
                current_description = line_stripped.split("Description:", 1)[1].strip()

            # Detect a tip.
            elif line_stripped.startswith("- Tip:") or line_stripped.startswith("-"):
                if "Tip:" in line_stripped:
                    tip = line_stripped.split("Tip:", 1)[1].strip()
                else:
                    tip = line_stripped[1:].strip()
                if tip:
                    current_tips.append(tip)

        # Save the final dimension.
        if current_theme and current_tips:
            dimensions.append(
                RubricDimension(
                    theme=current_theme,
                    tips=current_tips,
                    description=current_description or "",
                )
            )

        return Rubric(
            task_id=task_id,
            task_description="",
            dimensions=dimensions,
            min_score=0,
            max_score=5,
        )

    def _get_default_universal_rubric(
        self, domain: str, user_request: str = ""
    ) -> Rubric:
        """Return the default universal rubric after generation failure."""
        return Rubric(
            task_id="universal_default",
            task_description=user_request or f"Default generic rubric for {domain}",
            dimensions=[
                RubricDimension(
                    theme="Requirement Coverage",
                    description="Evaluates whether the visible workflow activities cover the requested operations",
                    tips=[
                        "Every explicitly requested executable activity is represented",
                        "No unsupported activity is introduced",
                        "Implicit control artifacts are not required as activity nodes",
                    ],
                    weight=1.0,
                ),
                RubricDimension(
                    theme="Direct Dependency Structure",
                    description="Evaluates direct ordering, branching, and joining relationships",
                    tips=[
                        "Direct prerequisite relationships follow the requirement",
                        "Parallel activities are not incorrectly ordered",
                        "Branch and join semantics are represented by the DAG topology",
                    ],
                    weight=1.0,
                ),
                RubricDimension(
                    theme="API Capability Alignment",
                    description="Evaluates whether selected APIs or activities match the requested functions",
                    tips=[
                        "Each selected API has a capability supported by its supplied metadata",
                        "The selected APIs collectively support the requested outcome",
                        "No capability is inferred when metadata is unavailable",
                    ],
                    weight=1.0,
                ),
                RubricDimension(
                    theme="Verifiable Interface Consistency",
                    description="Evaluates interfaces only where the supplied metadata makes them verifiable",
                    tips=[
                        "Connected executable APIs have compatible documented interfaces",
                        "Required conversions are present when their need is supported by metadata",
                        "Missing metadata is not treated as a workflow defect",
                    ],
                    weight=1.0,
                ),
            ],
            metadata={"type": "universal_default", "domain": domain},
        )

    def _get_default_task_rubric(self, task: Dict) -> Rubric:
        """Return the default task rubric after generation failure."""
        return Rubric(
            task_id=task.get("id", "unknown"),
            task_description=task.get("user_request", ""),
            dimensions=[
                RubricDimension(
                    theme="Step Completeness",
                    description="Checks if all required steps are present",
                    tips=[
                        "All user requirements are addressed",
                        "Task steps are complete",
                        "No critical functionality is missing",
                    ],
                    weight=1.0,
                ),
                RubricDimension(
                    theme="Tool Selection",
                    description="Evaluates appropriateness of tool selection",
                    tips=[
                        "Tools match the required operations",
                        "Tool parameters are correctly set",
                        "Tool sequence is logical",
                    ],
                    weight=1.0,
                ),
                RubricDimension(
                    theme="DAG Structure",
                    description="Evaluates DAG structural validity",
                    tips=[
                        "DAG is acyclic",
                        "Nodes are properly connected",
                        "Data flow is coherent",
                    ],
                    weight=1.0,
                ),
            ],
            metadata={"type": "task_default"},
        )
