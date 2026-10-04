import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from src.rubric_generator.simple_rubric import SimpleRubricGenerator,Rubric,RubricDimension
from src.simulation.model_executor import MultiModelExecutor
from src.simulation.discrepancy_analyzer import DiscrepancyAnalyzer,DiscrepancyReport
from src.simulation.rubric_refiner import RubricRefiner
from src.llm_factory.factory import LLMFactory
from src.evaluation import DAGEvaluator
from src.utils import build_tool_library_information
from utils import to_serializable, normalize_simulation_report


# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
@lru_cache(maxsize=1)
def _get_generator():
    return SimpleRubricGenerator(stage="draft")


@lru_cache(maxsize=1)
def _get_executor():
    return MultiModelExecutor()


@lru_cache(maxsize=1)
def _get_client():
    return LLMFactory.get_role_client("workflow_regeneration")


@lru_cache(maxsize=1)
def _get_analyzer():
    return DiscrepancyAnalyzer(llm_client=_get_client())


@lru_cache(maxsize=1)
def _get_refiner():
    return RubricRefiner()


@lru_cache(maxsize=1)
def _get_evaluator():
    return DAGEvaluator()


@lru_cache(maxsize=8)
def _get_universal_generator(tool_desc_path: str):
    """Cache one universal-rubric generator per knowledge-base snapshot."""
    return SimpleRubricGenerator(
        stage="universal",
        tool_desc_path=tool_desc_path,
    )


def _task_requirement(task: Any) -> str:
    """Extract the natural-language requirement from legacy and agent tasks."""
    if isinstance(task, dict):
        return str(
            task.get("user_request")
            or task.get("task_description")
            or task.get("describe")
            or ""
        ).strip()
    if isinstance(task, str):
        raw = task.strip()
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return raw
        return _task_requirement(parsed) if isinstance(parsed, dict) else raw
    return ""


def _knowledge_base_identity(spi_path: str) -> tuple[str, str]:
    collection_name = Path(spi_path).parent.name.strip() if spi_path else ""
    identity = collection_name.casefold()
    if "bpm" in identity or "business-process" in identity:
        domain = "business process management"
    elif "multimedia" in identity:
        domain = "multimedia processing"
    else:
        domain = collection_name.replace("-", " ") or "workflow modeling"
    return collection_name, domain


async def generate_universal_rubric(task):
    """Generate a task-grounded generic rubric from requirement D and tools T."""
    from knowledge_service import get_selected_tool_spi_path

    raw_path = get_selected_tool_spi_path()
    if not raw_path:
        raise ValueError("The selected knowledge base has no tool metadata file.")
    spi_path = str(Path(raw_path).resolve())
    collection_name, task_domain = _knowledge_base_identity(spi_path)
    generator = _get_universal_generator(spi_path)

    # T contains only the selected knowledge base's tool metadata and modeling
    # contract. It deliberately excludes reference dependency structures.
    tool_library_info = build_tool_library_information(
        generator.tools,
        collection_name=collection_name,
        domain=task_domain,
    )
    requirement = _task_requirement(task)

    rubric = await generator.generate_universal_rubric(
        {"num_dimensions": 4},
        task_domain=task_domain,
        user_request=requirement,
        tool_library_info=tool_library_info,
    )

    serializable = to_serializable(rubric)
    return serializable.get("dimensions", [])


async def generate_draft_rubric(task):

    draft_rubric = await _get_generator().generate_task_rubric(task)
    return draft_rubric


async def generate_simulation_results(task: Dict[str, Any]) -> Dict[str, Any]:








    
    model_results = await _get_executor().simulate_task(task)
    print(f"sim_results: {len(model_results)} models completed")

    
    sim_report = _get_analyzer().analyze_task(task, model_results)
    print("report:", sim_report)

    return sim_report



async def generate_task_specific_rubric(
    task,
    sim_results,
):





    sim_results_obj = sim_results or {"task_links": []}

    
    rubric_obj = await _get_refiner().generate_rubric_from_warnings(
        sim_results=sim_results_obj,
        task=task,
    )

    final_rubric = to_serializable(rubric_obj)

    if isinstance(final_rubric, dict):
        return final_rubric.get("dimensions", [])

    if isinstance(final_rubric, list):
        return final_rubric

    return final_rubric


def _dict_to_dimension(item):

    return RubricDimension(
        theme=item.get("theme", ""),
        tips=item.get("tips", []),
        weight=item.get("weight", 1),
        description=item.get("description", ""),
        source=item.get("source", ""),
        target=item.get("target", ""),
        expected_relation=item.get("expected_relation", ""),
        path_edges=item.get("path_edges", []),
    )


def normalize_rubric(rubric, task=None):
    
    if hasattr(rubric, "dimensions") and hasattr(rubric, "metadata"):
        return rubric

    task_id = ""
    task_description = ""
    if isinstance(task, dict):
        task_id = str(task.get("id", ""))
        task_description = task.get("user_request", "") or task.get("task_description", "")

    if isinstance(rubric, list):
        return Rubric(
            dimensions=[
                _dict_to_dimension(item) if isinstance(item, dict) else item
                for item in rubric
            ],
            metadata={
                "type": "merged_selected",
                "source": "universal+draft",
                "total_dimensions": len(rubric),
            },
            task_id=task_id,
            task_description=task_description,
            min_score=0,
            max_score=5,
        )

    if isinstance(rubric, dict) and "dimensions" in rubric:
        dims = rubric.get("dimensions", [])
        return Rubric(
            dimensions=[
                _dict_to_dimension(item) if isinstance(item, dict) else item
                for item in dims
            ],
            metadata=rubric.get("metadata", {
                "type": "merged_selected",
                "source": "universal+draft",
                "total_dimensions": len(dims),
            }),
            task_id=rubric.get("task_id", task_id),
            task_description=rubric.get("task_description", task_description),
            min_score=rubric.get("min_score", 0),
            max_score=rubric.get("max_score", 5),
        )

    return rubric


async def generate_dag_report(task, rubric, conformance_results=None, universal_rubric=None):








    evaluator = _get_evaluator()

    
    ts_report = None
    if rubric:
        ts_rubric = normalize_rubric(rubric, task=task)
        ts_result = await evaluator.evaluate_dag(
            task, ts_rubric,
            conformance_results=conformance_results,
            prompt_type='task_specific',
        )
        ts_report = to_serializable(ts_result)

    
    gen_report = None
    if universal_rubric:
        gen_rubric = normalize_rubric(universal_rubric, task=task)
        gen_result = await evaluator.evaluate_dag(
            task, gen_rubric,
            prompt_type='generic',
        )
        gen_report = to_serializable(gen_result)

    return {
        "task_specific_report": ts_report,
        "generic_report": gen_report,
    }

import re
from src.llm_factory.base import Message


def _build_dag_regeneration_prompt(
    task,
    original_workflow,
    sim_results,
    evaluation_report=None,
    repair_plan=None,
    repair_history=None,
):
    """Build the Repair Agent prompt, including its prior revision memory."""
    user_request = task.get("user_request", "")

    original_nodes = original_workflow.get("task_nodes", [])
    original_links = original_workflow.get("task_links", [])

    task_links_status = sim_results.get("task_links", [])
    pass_links = [
        f"  {l['source']} → {l['target']}" for l in task_links_status if l.get("status") == "pass"
    ]
    warn_links = [
        f"  {l['source']} → {l['target']}" for l in task_links_status if l.get("status") == "warn"
    ]

    evaluation_context = (
        json.dumps(evaluation_report, indent=2, ensure_ascii=False)
        if evaluation_report
        else "(not provided)"
    )
    repair_context = (
        json.dumps(repair_plan, indent=2, ensure_ascii=False)
        if repair_plan
        else "(not provided)"
    )
    history_context = json.dumps(
        repair_history or [],
        indent=2,
        ensure_ascii=False,
    )

    prompt = f"""You are a workflow optimization expert. Your task is to revise a DAG (Directed Acyclic Graph) workflow model based on discrepancy analysis results and a structured repair plan.

## Task Description
{user_request}

## Current DAG Model
task_nodes:
{json.dumps(original_nodes, indent=2, ensure_ascii=False)}

task_links:
{json.dumps(original_links, indent=2, ensure_ascii=False)}

## Discrepancy Analysis Results
The DAG was evaluated by multiple AI models. Each dependency edge was checked for consensus:

### PASS edges (all models agree):
{chr(10).join(pass_links) if pass_links else "  (none)"}

### WARN edges (some models disagree — these may need revision):
{chr(10).join(warn_links) if warn_links else "  (none)"}

## Evaluation Report
{evaluation_context}

## Structured Repair Plan
{repair_context}

## Previous Revision History (reference only)
{history_context}

## Your Task
Based on the discrepancy analysis, evaluation evidence, and repair plan:
1. WARN edges indicate potential issues — consider removing, reordering, or restructuring them.
2. PASS edges are reliable — keep them.
3. Apply high-priority repair operations first, but verify that each operation is semantically valid.
4. Use Previous Revision History as repair memory. The Current DAG and the current Repair Plan take precedence over historical entries. Do not repeat an operation whose intended effect is already satisfied in the Current DAG.
5. The Current DAG is authoritative: if a previously applied effect is no longer present and the current Repair Plan requests it again, the operation may be reapplied.
6. Preserve the existing task_nodes exactly. This repair stage may only add or remove dependency edges explicitly requested by the Repair Plan.
7. Return one revision-log entry for every requested repair operation. Mark it as applied, already_satisfied, or failed and briefly explain the outcome.
8. Modify the DAG to resolve the diagnosed issues while preserving unaffected workflow structure.

Output ONLY a valid JSON object with this exact structure (no markdown, no explanation):
{{
  "task_nodes": [
    {{"task": "<tool name>", "arguments": ["<arg1>", "<arg2>"]}}
  ],
  "task_links": [
    {{"source": "<tool name>", "target": "<tool name>"}}
  ],
  "revision_log": {{
    "summary": "<brief description of this repair>",
    "operations": [
      {{
        "issue_id": "<repair-plan issue id>",
        "operation": "<add_edge or remove_edge>",
        "source": "<source node>",
        "target": "<target node>",
        "status": "<applied, already_satisfied, or failed>",
        "reason": "<what was done and why>"
      }}
    ]
  }}
}}
"""
    return prompt


def _parse_dag_response(response_text):
    """Parse a Repair Agent response containing a DAG and revision log."""
    text = response_text.strip()

    
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    dag = json.loads(text)
    if not isinstance(dag, dict):
        raise ValueError("Repair Agent response must be a JSON object.")

    
    if "task_nodes" not in dag:
        dag["task_nodes"] = []
    if "task_links" not in dag:
        dag["task_links"] = []

    return dag


async def workflow_regeneration_service(
    task,
    original_workflow,
    sim_results,
    evaluation_report=None,
    repair_plan=None,
    repair_history=None,
    return_revision_log=False,
):
















    # The Coordinator supplies an executable structured Repair Plan. Apply edge
    # changes and grounded insert_node_between operations through a
    # deterministic tool instead of asking an LLM to regenerate the
    # complete DAG.  Keeping this branch inside the existing service preserves
    # the legacy API contract while making the agent loop genuinely reparative.
    if isinstance(repair_plan, dict) and "operations" in repair_plan:
        from src.repair import DAGModificationTool

        repair_artifact = DAGModificationTool()(
            original_workflow or {"task_nodes": [], "task_links": []},
            repair_plan,
            repair_history=repair_history,
        )
        if return_revision_log:
            return repair_artifact
        return repair_artifact["dag"]

    
    if not original_workflow or not sim_results:
        print("⚠️ workflow_regeneration_service: missing original_workflow or sim_results, returning original")
        fallback = original_workflow or {"task_nodes": [], "task_links": []}
        if return_revision_log:
            return {
                "dag": fallback,
                "revision_log": {"summary": "No repair was performed.", "operations": []},
            }
        return fallback

    client = _get_client()

    system_prompt = (
        "You are a workflow DAG optimization expert. "
        "You revise workflow DAG models based on multi-agent discrepancy analysis. "
        "Always respond with valid JSON only."
    )
    user_prompt = _build_dag_regeneration_prompt(
        task,
        original_workflow,
        sim_results,
        evaluation_report=evaluation_report,
        repair_plan=repair_plan,
        repair_history=repair_history,
    )

    messages = [
        Message("system", system_prompt),
        Message("user", user_prompt),
    ]

    response = await client.acomplete(
        messages=messages,
        temperature=0.0,
        max_tokens=4000,
    )

    
    if isinstance(response, str):
        response_text = response
    elif hasattr(response, "content"):
        response_text = response.content
    elif isinstance(response, dict):
        response_text = response.get("content", "")
    else:
        response_text = str(response)

    print("Regeneration LLM response length:", len(response_text))

    optimized_dag = _parse_dag_response(response_text)
    agent_revision_log = optimized_dag.pop("revision_log", None)
    if not isinstance(agent_revision_log, dict):
        agent_revision_log = {"summary": "", "operations": []}
    print("✅ Optimized DAG:",
          len(optimized_dag.get("task_nodes", [])), "nodes,",
          len(optimized_dag.get("task_links", [])), "links")

    if return_revision_log:
        return {
            "dag": optimized_dag,
            "revision_log": agent_revision_log,
        }
    return optimized_dag


def validate_edges_with_log_service(
    sim_results: Dict[str, Any], log_file_path: str
) -> Dict[str, Any]:













    from src.evaluation.conformance_checker import validate_edges_with_log

    task_links = sim_results.get("task_links", [])
    model_status_by_edge = {
        (str(link.get("source", "")), str(link.get("target", ""))): (
            link.get("model_status") or link.get("status", "warn")
        )
        for link in task_links
    }
    result = validate_edges_with_log(
        edges=task_links,
        log_path=log_file_path,
        threshold=0.8,
    )

    updated_sim = dict(sim_results)
    updated_sim["task_links"] = [
        {
            **link,
            "model_status": model_status_by_edge.get(
                (str(link.get("source", "")), str(link.get("target", ""))),
                "warn",
            ),
            "log_status": link.get("status", "warn"),
        }
        for link in result["task_links"]
    ]
    updated_sim["log_trace_count"] = result["trace_count"]
    updated_sim["log_reduced_edges"] = result.get("log_reduced_edges", [])
    return updated_sim
