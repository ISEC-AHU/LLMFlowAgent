import asyncio
import json
import os
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from deps import db
from knowledge_service import (
    get_selected_tool_spi_path,
    retrieve_tools,
    rewrite_queries,
    tools_to_retrieved_docs,
)
from service import (
    generate_dag_report,
    generate_simulation_results,
    generate_task_specific_rubric,
    generate_universal_rubric,
    workflow_regeneration_service,
)
from src.generation.chains.create_game import create_game_chain_with_history
from src.generation.chains.write_dag import write_dag_chain
from src.generation.chains.write_xml import write_xml_chain
from src.utils.tool_context import normalize_api_metadata
from utils import parse_dag, parse_task_steps

from .storage import WorkflowRunStorage, now_ms
from .validators import dag_fingerprint, validate_dag


ACTIVE_STATUSES = {
    "pending",
    "generating",
    "evaluating",
    "repairing",
    "verifying",
    "awaiting_review",
}
MAX_GENERATION_ATTEMPTS = 3
MAX_CONFIGURABLE_VERSIONS = 10
DEFAULT_REGENERATION_THRESHOLD = 1.0
DEFAULT_ACCEPTANCE_THRESHOLD = 4.0
DEFAULT_TASK_DECOMPOSITION_TIMEOUT_SECONDS = 90.0


def _task_decomposition_timeout_seconds() -> float:
    """Return a positive timeout without letting invalid config break startup."""
    raw_value = os.getenv("TASK_DECOMPOSITION_TIMEOUT_SECONDS", "").strip()
    if not raw_value:
        return DEFAULT_TASK_DECOMPOSITION_TIMEOUT_SECONDS
    try:
        configured = float(raw_value)
    except ValueError:
        return DEFAULT_TASK_DECOMPOSITION_TIMEOUT_SECONDS
    return configured if configured > 0 else DEFAULT_TASK_DECOMPOSITION_TIMEOUT_SECONDS
STRUCTURAL_REGENERATION_CATEGORIES = {
    "cycle",
    "disconnected_graph",
    "empty_graph",
    "self_loop",
    "invalid_reference",
    "structure",
}


class RunStopped(Exception):
    pass


def _as_dict(row) -> Dict[str, Any]:
    return {key: row[key] for key in row.keys()}


def _score(report: Dict[str, Any], key: str) -> Optional[float]:
    value = (report.get(key) or {}).get("normalized_score")
    return float(value) if isinstance(value, (int, float)) else None


def _composite_score(
    generic_score: Optional[float],
    task_specific_score: Optional[float],
) -> float:
    values = [
        value
        for value in (generic_score, task_specific_score)
        if value is not None
    ]
    return sum(values) / len(values) if values else 0.0


def _has_deterministic_defect(
    report: Dict[str, Any],
    threshold: float = 3.5,
) -> bool:
    """Detect a hard, deterministic defect hiding behind a passing composite.

    Two evidence states are treated as blocking defects:

    * ``evidence_verification == "failed"`` — the evaluator's reasoning was
      rejected by the deterministic DAG evidence, so the neutral score it
      received cannot be trusted (Workflow 194 regression: a "failed" generic
      control-flow dimension was averaged away and the version accepted).
    * ``evidence_verification == "deterministic"`` with ``score < threshold``
      — a graph-factual dependency requirement that the current DAG violates.

    Either case means the version carries a real defect that must not be
    averaged away by higher-scoring soft dimensions.
    """
    for report_key in ("task_specific_report", "generic_report"):
        report_part = report.get(report_key) or {}
        if not isinstance(report_part, dict):
            continue
        for dimension in report_part.get("dimension_scores", []) or []:
            if not isinstance(dimension, dict):
                continue
            verification = str(
                dimension.get("evidence_verification", "")
            ).lower()
            if verification == "failed":
                return True
            if verification != "deterministic":
                continue
            try:
                score = float(dimension.get("score") or 0.0)
            except (TypeError, ValueError):
                continue
            if score < threshold:
                return True
    return False


def _coordination_decision(
    composite_score: float,
    regeneration_threshold: float = DEFAULT_REGENERATION_THRESHOLD,
    acceptance_threshold: float = DEFAULT_ACCEPTANCE_THRESHOLD,
    *,
    structural_failure: bool = False,
    deterministic_defect: bool = False,
) -> str:
    """Route one evaluated version using the Coordinator score policy.

    ``deterministic_defect`` acts as an acceptance gate: even when the composite
    score clears ``acceptance_threshold``, a version carrying a deterministic
    graph-factual defect is downgraded to ``repair`` so the defect is fixed in a
    later round instead of being averaged away.
    """
    if structural_failure or composite_score < regeneration_threshold:
        return "regenerate"
    if composite_score >= acceptance_threshold:
        return "repair" if deterministic_defect else "accept"
    return "repair"


def _edge_key(link: Dict[str, Any]) -> Tuple[str, str]:
    return (
        str(link.get("source", "")).strip(),
        str(link.get("target", "")).strip(),
    )


def _dag_diff(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    before_nodes = {
        str(
            node.get("task")
            or node.get("name")
            or node.get("label")
            or node.get("id")
            or ""
        ).strip()
        for node in before.get("task_nodes", [])
        if isinstance(node, dict)
    }
    after_nodes = {
        str(
            node.get("task")
            or node.get("name")
            or node.get("label")
            or node.get("id")
            or ""
        ).strip()
        for node in after.get("task_nodes", [])
        if isinstance(node, dict)
    }
    before_nodes.discard("")
    after_nodes.discard("")
    before_edges = {
        _edge_key(link)
        for link in before.get("task_links", [])
        if all(_edge_key(link))
    }
    after_edges = {
        _edge_key(link)
        for link in after.get("task_links", [])
        if all(_edge_key(link))
    }
    return {
        "added_nodes": sorted(after_nodes - before_nodes),
        "removed_nodes": sorted(before_nodes - after_nodes),
        "unchanged_node_count": len(before_nodes & after_nodes),
        "added_edges": [
            {"source": source, "target": target}
            for source, target in sorted(after_edges - before_edges)
        ],
        "removed_edges": [
            {"source": source, "target": target}
            for source, target in sorted(before_edges - after_edges)
        ],
        "unchanged_edge_count": len(before_edges & after_edges),
    }


def _repair_operation_key(operation: Dict[str, Any]) -> Tuple[str, str, str]:
    operation_name = str(operation.get("operation", "")).strip().lower()
    if operation_name == "insert_node_between":
        raw_node = operation.get("node") or {}
        node_name = str(
            raw_node.get("task")
            or raw_node.get("name")
            or operation.get("source")
            or ""
        ).strip()
        predecessors = [
            str(value).strip()
            for value in operation.get("predecessors", []) or []
            if str(value).strip()
        ]
        successors = [
            str(value).strip()
            for value in operation.get("successors", []) or []
            if str(value).strip()
        ]
        remove_edges = [
            _edge_key(edge)
            for edge in operation.get("remove_edges", []) or []
            if isinstance(edge, dict) and all(_edge_key(edge))
        ]
        wiring = (
            ",".join(predecessors)
            + "->"
            + ",".join(successors)
            + "|remove:"
            + ",".join(
                f"{source}->{target}" for source, target in remove_edges
            )
        )
        return operation_name, node_name, wiring
    return (
        operation_name,
        str(operation.get("source", "")).strip(),
        str(operation.get("target", "")).strip(),
    )


def _repair_history_from_versions(
    versions: List[Dict[str, Any]], limit: int = 3
) -> List[Dict[str, Any]]:
    """Return recent accepted Repair Agent logs in version order."""
    history = []
    for version in versions:
        summary = version.get("repair_summary") or {}
        if not isinstance(summary, dict) or summary.get("producer") != "repair":
            continue
        revision_log = summary.get("revision_log")
        if not isinstance(revision_log, dict):
            continue
        if str(revision_log.get("outcome", "")).startswith("rejected_"):
            continue
        history.append(revision_log)
    return history[-max(0, limit):] if limit else []


def _verify_revision_log(
    *,
    source_version: int,
    before: Dict[str, Any],
    after: Dict[str, Any],
    repair_plan: Dict[str, Any],
    agent_revision_log: Optional[Dict[str, Any]],
    repair_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Verify the Repair Agent's log against the actual before/after DAGs."""
    def node_names(workflow: Dict[str, Any]) -> Set[str]:
        names = {
            str(
                node.get("task")
                or node.get("name")
                or node.get("label")
                or node.get("id")
                or ""
            ).strip()
            for node in workflow.get("task_nodes", [])
            if isinstance(node, dict)
        }
        names.discard("")
        return names

    before_nodes = node_names(before)
    after_nodes = node_names(after)
    before_edges = {
        _edge_key(link)
        for link in before.get("task_links", [])
        if all(_edge_key(link))
    }
    after_edges = {
        _edge_key(link)
        for link in after.get("task_links", [])
        if all(_edge_key(link))
    }
    raw_log = agent_revision_log if isinstance(agent_revision_log, dict) else {}
    raw_operations = raw_log.get("operations") or []
    if not isinstance(raw_operations, list):
        raw_operations = []
    reported_by_key = {
        _repair_operation_key(item): item
        for item in raw_operations
        if isinstance(item, dict)
        and _repair_operation_key(item)[0]
        in {"add_edge", "remove_edge", "insert_node_between"}
    }

    prior_by_key: Dict[Tuple[str, str, str], List[str]] = {}
    for history_log in repair_history or []:
        if not isinstance(history_log, dict):
            continue
        for prior in history_log.get("operations") or []:
            if not isinstance(prior, dict):
                continue
            key = _repair_operation_key(prior)
            prior_by_key.setdefault(key, []).append(str(prior.get("status", "")))

    verified_operations = []
    planned_added_edges: Set[Tuple[str, str]] = set()
    planned_removed_edges: Set[Tuple[str, str]] = set()
    planned_added_nodes: Set[str] = set()
    for planned in repair_plan.get("operations", []):
        if not isinstance(planned, dict):
            continue
        operation, source, target = _repair_operation_key(planned)
        if operation not in {
            "add_edge",
            "remove_edge",
            "insert_node_between",
        }:
            continue
        key = (operation, source, target)
        reported = reported_by_key.get(key, {})
        previous_statuses = prior_by_key.get(key, [])

        if operation == "insert_node_between":
            raw_node = planned.get("node") or {}
            node_name = str(
                raw_node.get("task") or raw_node.get("name") or source or ""
            ).strip()
            predecessors = [
                str(value).strip()
                for value in planned.get("predecessors", []) or []
                if str(value).strip()
            ]
            successors = [
                str(value).strip()
                for value in planned.get("successors", []) or []
                if str(value).strip()
            ]
            remove_edges = [
                _edge_key(edge)
                for edge in planned.get("remove_edges", []) or []
                if isinstance(edge, dict) and all(_edge_key(edge))
            ]
            added_edges = {
                *((predecessor, node_name) for predecessor in predecessors),
                *((node_name, successor) for successor in successors),
            }
            planned_added_nodes.add(node_name)
            planned_added_edges.update(added_edges)
            planned_removed_edges.update(remove_edges)
            before_present = node_name in before_nodes
            after_present = node_name in after_nodes
            satisfied = (
                bool(node_name)
                and after_present
                and added_edges.issubset(after_edges)
                and all(edge not in after_edges for edge in remove_edges)
            )
            changed = (
                (not before_present and after_present)
                or bool(added_edges - before_edges)
                or any(edge in before_edges and edge not in after_edges for edge in remove_edges)
            )
            status = (
                "applied"
                if satisfied and changed
                else "already_satisfied"
                if satisfied
                else "failed"
            )
            verified_operations.append(
                {
                    "issue_id": planned.get("issue_id")
                    or reported.get("issue_id")
                    or "",
                    "operation": operation,
                    "source": node_name,
                    "target": target,
                    "node": dict(raw_node),
                    "predecessors": predecessors,
                    "successors": successors,
                    "remove_edges": [
                        {"source": edge_source, "target": edge_target}
                        for edge_source, edge_target in remove_edges
                    ],
                    "grounding": planned.get("grounding") or {},
                    "status": status,
                    "before_state": "present" if before_present else "absent",
                    "after_state": "present" if after_present else "absent",
                    "reason": planned.get("reason")
                    or reported.get("reason")
                    or "",
                    "agent_reported_status": str(reported.get("status", "")),
                    "previously_recorded": bool(previous_statuses),
                    "previous_statuses": previous_statuses,
                }
            )
            continue

        if not source or not target:
            continue
        edge = (source, target)
        before_present = edge in before_edges
        after_present = edge in after_edges
        if operation == "add_edge":
            planned_added_edges.add(edge)
            if after_present and not before_present:
                status = "applied"
            elif after_present:
                status = "already_satisfied"
            else:
                status = "failed"
        else:
            planned_removed_edges.add(edge)
            if before_present and not after_present:
                status = "applied"
            elif not after_present:
                status = "already_satisfied"
            else:
                status = "failed"

        verified_operations.append(
            {
                "issue_id": planned.get("issue_id")
                or reported.get("issue_id")
                or "",
                "operation": operation,
                "source": source,
                "target": target,
                "status": status,
                "before_state": "present" if before_present else "absent",
                "after_state": "present" if after_present else "absent",
                "reason": planned.get("reason")
                or reported.get("reason")
                or "",
                "agent_reported_status": str(reported.get("status", "")),
                "previously_recorded": bool(previous_statuses),
                "previous_statuses": previous_statuses,
            }
        )

    diff = _dag_diff(before, after)
    unplanned_operations = []
    for node_name in diff["added_nodes"]:
        if node_name not in planned_added_nodes:
            unplanned_operations.append(
                {"operation": "add_node", "node": node_name}
            )
    for node_name in diff["removed_nodes"]:
        unplanned_operations.append(
            {"operation": "remove_node", "node": node_name}
        )
    for edge in diff["added_edges"]:
        edge_key = (edge["source"], edge["target"])
        if edge_key not in planned_added_edges:
            unplanned_operations.append({"operation": "add_edge", **edge})
    for edge in diff["removed_edges"]:
        edge_key = (edge["source"], edge["target"])
        if edge_key not in planned_removed_edges:
            unplanned_operations.append({"operation": "remove_edge", **edge})

    raw_outcome = str(raw_log.get("outcome", "")).strip()
    verification_status = (
        raw_outcome
        if raw_outcome.startswith("rejected_")
        else (
            "verified_with_unplanned_changes"
            if unplanned_operations
            else "verified"
        )
    )
    return {
        "source_version": source_version,
        "target_version": source_version + 1,
        "source_fingerprint": dag_fingerprint(before),
        "target_fingerprint": dag_fingerprint(after),
        "summary": str(raw_log.get("summary", "")).strip(),
        "executor": str(raw_log.get("executor", "repair_agent")).strip(),
        "atomic": bool(raw_log.get("atomic", False)),
        "outcome": raw_outcome,
        "errors": list(raw_log.get("errors") or []),
        "structural_issues": list(raw_log.get("structural_issues") or []),
        "operations": verified_operations,
        "unplanned_operations": unplanned_operations,
        "history_entries_consulted": len(repair_history or []),
        "verification_status": verification_status,
    }


def _normalized_activity_name(value: Any) -> str:
    """Normalize a workflow/API activity name for exact textual matching."""
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))


_ACTIVITY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "by",
    "for",
    "from",
    "in",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


def _light_activity_stem(token: str) -> str:
    """Apply a deliberately small normalization for common inflections."""
    value = token.casefold()
    if len(value) > 4 and value.endswith("ies"):
        value = value[:-3] + "y"
    elif len(value) > 4 and value.endswith("ing"):
        value = value[:-3]
        if len(value) > 2 and value[-1] == value[-2]:
            value = value[:-1]
    elif len(value) > 3 and value.endswith("ed"):
        # provided -> provide; selected -> select
        value = value[:-1] if value[-3] == "e" else value[:-2]
    elif len(value) > 3 and value.endswith("s") and not value.endswith("ss"):
        value = value[:-1]
    if len(value) > 4 and value.endswith("e"):
        value = value[:-1]
    return value


def _activity_tokens(value: Any) -> Tuple[str, ...]:
    tokens = []
    for token in re.findall(r"[a-z0-9]+", str(value or "").casefold()):
        if token in _ACTIVITY_STOP_WORDS:
            continue
        normalized = _light_activity_stem(token)
        if normalized and normalized not in tokens:
            tokens.append(normalized)
    return tuple(tokens)


def _node_names(dag: Dict[str, Any]) -> Dict[str, str]:
    """Map normalized node names to their canonical DAG spelling."""
    result: Dict[str, str] = {}
    for node in dag.get("task_nodes", []) or []:
        if not isinstance(node, dict):
            continue
        name = str(
            node.get("task")
            or node.get("name")
            or node.get("label")
            or node.get("id")
            or ""
        ).strip()
        normalized = _normalized_activity_name(name)
        if name and normalized:
            result.setdefault(normalized, name)
    return result


def _requirement_mentions_activity(
    task: Optional[Dict[str, Any]], activity_name: str
) -> bool:
    """Require conservative token evidence in the original requirement."""
    if not isinstance(task, dict):
        return False
    requirement_tokens = set(_activity_tokens(task.get("user_request", "")))
    activity_tokens = set(_activity_tokens(activity_name))
    if not requirement_tokens or not activity_tokens:
        return False
    return activity_tokens <= requirement_tokens


def _ground_candidate_api(
    task: Optional[Dict[str, Any]], activity_name: str
) -> Optional[Dict[str, Any]]:
    """Return one uniquely best, conservatively matched candidate API."""
    if not isinstance(task, dict):
        return None
    expected_name = _normalized_activity_name(activity_name)
    expected_tokens = set(_activity_tokens(activity_name))
    if not expected_name or not expected_tokens:
        return None
    candidates = normalize_api_metadata(task.get("api_list"))
    exact = [
        candidate
        for candidate in candidates
        if _normalized_activity_name(candidate.get("name")) == expected_name
    ]
    if len(exact) == 1:
        return {**exact[0], "match_type": "exact_candidate_api"}
    if exact:
        return None

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for candidate in candidates:
        candidate_tokens = set(_activity_tokens(candidate.get("name")))
        overlap = candidate_tokens & expected_tokens
        # A non-exact one-token label is too weak to ground a new node.  For
        # longer names, every candidate token must occur in the verified
        # missing-node label (e.g., Provide quote vs. Provide a quote to the
        # customer).  This is lexical normalization, not semantic guessing.
        if (
            len(candidate_tokens) < 2
            or not candidate_tokens <= expected_tokens
            or len(overlap) < 2
        ):
            continue
        score = (2.0 * len(overlap)) / (
            len(candidate_tokens) + len(expected_tokens)
        )
        scored.append((score, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_candidate = scored[0]
    if len(scored) > 1 and abs(scored[1][0] - best_score) < 1e-9:
        return None
    return {
        **best_candidate,
        "match_type": "unique_token_match",
        "match_score": round(best_score, 4),
    }


def _derive_insert_arguments(
    dag: Dict[str, Any],
    task: Optional[Dict[str, Any]],
    candidate: Dict[str, Any],
    predecessors: List[str],
) -> List[str]:
    """Ground node references through exact input/output type matches."""
    required_inputs = [
        _normalized_activity_name(value)
        for value in candidate.get("input_types", []) or []
        if _normalized_activity_name(value)
    ]
    if not required_inputs or not isinstance(task, dict):
        return []

    producer_outputs: List[Tuple[int, Set[str], bool]] = []
    predecessor_keys = {
        _normalized_activity_name(name) for name in predecessors
    }
    for index, node in enumerate(dag.get("task_nodes", []) or []):
        if not isinstance(node, dict):
            continue
        node_name = str(
            node.get("task") or node.get("name") or node.get("id") or ""
        ).strip()
        predecessor_api = _ground_candidate_api(task, node_name)
        if predecessor_api is None:
            continue
        output_types = {
            _normalized_activity_name(value)
            for value in predecessor_api.get("output_types", []) or []
            if _normalized_activity_name(value)
        }
        producer_outputs.append(
            (
                index,
                output_types,
                _normalized_activity_name(node_name) in predecessor_keys,
            )
        )

    arguments: List[str] = []
    for required_input in required_inputs:
        matches = [
            producer
            for producer in producer_outputs
            if required_input in producer[1]
        ]
        # Prefer a control-flow predecessor when it also supplies the required
        # data; otherwise use the first exact type producer in node order.
        matches.sort(key=lambda item: (not item[2], item[0]))
        argument = (
            f"<node-{matches[0][0]}>" if matches else required_input
        )
        if argument not in arguments:
            arguments.append(argument)
    return arguments


def _log_insertion_context(
    dag: Dict[str, Any],
    simulation: Dict[str, Any],
    activity_name: str,
) -> Optional[Dict[str, Any]]:
    """Locate existing predecessors/successors around a missing log activity."""
    canonical_nodes = _node_names(dag)
    activity = _normalized_activity_name(activity_name)
    if not activity or activity in canonical_nodes:
        return None

    predecessors: List[str] = []
    successors: List[str] = []
    for edge in simulation.get("log_reduced_edges", []) or []:
        if not isinstance(edge, dict):
            continue
        source = _normalized_activity_name(edge.get("source"))
        target = _normalized_activity_name(edge.get("target"))
        if target == activity and source in canonical_nodes:
            predecessor = canonical_nodes[source]
            if predecessor not in predecessors:
                predecessors.append(predecessor)
        if source == activity and target in canonical_nodes:
            successor = canonical_nodes[target]
            if successor not in successors:
                successors.append(successor)

    if not predecessors or not successors:
        return None

    current_edges = {
        _edge_key(edge)
        for edge in dag.get("task_links", []) or []
        if isinstance(edge, dict) and all(_edge_key(edge))
    }
    remove_edges = [
        {"source": predecessor, "target": successor}
        for predecessor in predecessors
        for successor in successors
        if (predecessor, successor) in current_edges
    ]
    return {
        "predecessors": predecessors,
        "successors": successors,
        "remove_edges": remove_edges,
    }


def _verified_missing_nodes(dimension: Dict[str, Any]) -> List[str]:
    """Extract only deterministic, explicitly observed missing-node checks."""
    if str(dimension.get("evidence_verification", "")).lower() not in {
        "verified",
        "deterministic",
    }:
        return []
    missing: List[str] = []
    for check in dimension.get("evidence_checks", []) or []:
        if not isinstance(check, dict):
            continue
        node = str(check.get("node", "")).strip()
        if (
            str(check.get("predicate", "")).strip().lower()
            == "node_exists"
            and check.get("observed") is False
            and check.get("actual") is False
            and check.get("valid") is True
            and not check.get("error")
            and node
            and node not in missing
        ):
            missing.append(node)
    return missing


def _build_missing_node_issue(
    *,
    dag: Dict[str, Any],
    simulation: Dict[str, Any],
    task: Optional[Dict[str, Any]],
    activity_name: str,
    version_no: int,
    issue_suffix: str,
) -> Optional[Dict[str, Any]]:
    """Build a grounded composite insertion issue when all evidence agrees."""
    candidate = _ground_candidate_api(task, activity_name)
    if candidate is None or not _requirement_mentions_activity(
        task, candidate.get("name", "")
    ):
        return None
    context = _log_insertion_context(dag, simulation, candidate.get("name", ""))
    if context is None:
        return None

    canonical_name = str(candidate["name"]).strip()
    grounding = dict(candidate)
    action = {
        "operation": "insert_node_between",
        "node": {
            "task": canonical_name,
            "arguments": _derive_insert_arguments(
                dag, task, candidate, context["predecessors"]
            ),
        },
        "predecessors": context["predecessors"],
        "successors": context["successors"],
        "remove_edges": context["remove_edges"],
        "grounding": grounding,
    }
    return {
        "issue_id": f"MISSING-NODE-{version_no}-{issue_suffix}",
        "category": "missing_workflow_node",
        "severity": "high",
        "confidence": 1.0,
        "fact_verification_status": "verified",
        "status": "open",
        "found_in_version": version_no,
        "target": {"node": canonical_name},
        "claim": (
            f"The required grounded activity '{canonical_name}' is absent from "
            "the current workflow model."
        ),
        "evidence": [
            {
                "source": "dag_evidence_tool",
                "detail": (
                    f"node_exists({canonical_name}) was deterministically "
                    "verified as false."
                ),
            },
            {
                "source": "candidate_api",
                "detail": (
                    f"Uniquely grounded candidate API: {canonical_name} "
                    f"({candidate.get('match_type')})."
                ),
            },
            {
                "source": "workflow_requirement",
                "detail": (
                    f"The original workflow requirement explicitly mentions "
                    f"'{canonical_name}'."
                ),
            },
            {
                "source": "execution_log",
                "detail": (
                    "The minimal log dependency set places the activity after "
                    f"{', '.join(context['predecessors'])} and before "
                    f"{', '.join(context['successors'])}."
                ),
            },
        ],
        "recommended_action": action,
        "acceptance_test": {
            "type": "node_inserted_between",
            "node": canonical_name,
            "predecessors": context["predecessors"],
            "successors": context["successors"],
        },
    }


def _build_issues(
    dag: Dict[str, Any],
    validation: Dict[str, Any],
    simulation: Dict[str, Any],
    report: Dict[str, Any],
    version_no: int,
    final_rubric: Optional[List[Dict[str, Any]]] = None,
    include_dependency_issues: bool = True,
    task: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    issues: List[Dict[str, Any]] = []
    for issue in validation.get("issues", []):
        issues.append(
            {
                **issue,
                "status": "open",
                "found_in_version": version_no,
                "confidence": 1.0,
            }
        )

    current_edges = {
        _edge_key(link)
        for link in dag.get("task_links", [])
        if all(_edge_key(link))
    }
    simulation_links = (
        simulation.get("task_links", []) if include_dependency_issues else []
    )
    for index, link in enumerate(simulation_links):
        if str(link.get("model_status") or link.get("status", "")).lower() != "warn":
            continue
        source, target = _edge_key(link)
        present = (source, target) in current_edges
        log_rate = link.get("log_support_rate")
        log_unsupported = (
            link.get("log_edge_type") == "unsupported"
            or isinstance(log_rate, (int, float))
            and log_rate < 0.8
        )
        issues.append(
            {
                "issue_id": f"EDGE-{version_no}-{index + 1:03d}",
                "category": "log_conformance"
                if log_unsupported
                else "dependency_discrepancy",
                "severity": "high" if log_unsupported else "medium",
                "confidence": 0.9 if log_unsupported else 0.65,
                "status": "open",
                "found_in_version": version_no,
                "target": {"source": source, "target": target},
                "claim": (
                    "Execution-log evidence does not support this dependency."
                    if log_unsupported
                    else "Independent workflow models disagree about this dependency."
                ),
                "evidence": [
                    {
                        "source": "execution_log"
                        if log_unsupported
                        else "multi_model_consensus",
                        "detail": (
                            f"Log support rate: {float(log_rate):.0%}"
                            if isinstance(log_rate, (int, float))
                            else "The edge was marked WARN by deterministic comparison."
                        ),
                    }
                ],
                "recommended_action": None,
                "acceptance_test": {
                    "type": "dependency_re_evaluated",
                    "source": source,
                    "target": target,
                },
            }
        )

    rubric_by_theme = {
        str(item.get("theme", "")): item
        for item in (final_rubric or [])
        if isinstance(item, dict)
    }
    simulation_by_edge = {
        _edge_key(link): link
        for link in simulation.get("task_links", [])
        if all(_edge_key(link))
    }
    emitted_missing_nodes: Set[str] = set()
    for report_key, label in (
        ("generic_report", "generic"),
        ("task_specific_report", "task-specific"),
    ):
        report_part = report.get(report_key) or {}
        for index, dimension in enumerate(
            report_part.get("dimension_scores", [])
        ):
            evidence_verification = str(
                dimension.get("evidence_verification", "not_checked")
            ).lower()
            if evidence_verification == "failed":
                # A graph-factual claim rejected by the deterministic evidence
                # tool must never become a repair issue or operation.
                continue
            score = float(dimension.get("score", 0))
            if score >= 3.5:
                continue
            for missing_index, missing_node in enumerate(
                _verified_missing_nodes(dimension), 1
            ):
                missing_key = _normalized_activity_name(missing_node)
                if not missing_key or missing_key in emitted_missing_nodes:
                    continue
                missing_issue = _build_missing_node_issue(
                    dag=dag,
                    simulation=simulation,
                    task=task,
                    activity_name=missing_node,
                    version_no=version_no,
                    issue_suffix=f"{label.upper()}-{index + 1:03d}-{missing_index:02d}",
                )
                if missing_issue is not None:
                    issues.append(missing_issue)
                    emitted_missing_nodes.add(
                        _normalized_activity_name(
                            (missing_issue.get("target") or {}).get("node")
                        )
                    )
            dimension_name = dimension.get("dimension_name", "")
            rubric_dimension = (
                rubric_by_theme.get(str(dimension_name), {})
                if label == "task-specific"
                else {}
            )
            source = str(rubric_dimension.get("source", "")).strip()
            target = str(rubric_dimension.get("target", "")).strip()
            edge_key = (source, target)
            edge_present = bool(source and target and edge_key in current_edges)
            simulation_link = simulation_by_edge.get(edge_key, {})
            evidence_status = str(
                simulation_link.get("status")
                or simulation_link.get("log_status", "")
            ).lower()
            expected_relation = str(
                rubric_dimension.get("expected_relation", "")
            ).lower()
            # F4: A transitive_only dimension carries the authoritative path
            # obtained through XES transitive reduction. Compare each hop with
            # the current DAG so the repair plan can atomically add missing
            # bridge edges with the primary operation (Workflow 199:
            # Collect -> Guide -> Quote).
            missing_path_edges: List[Dict[str, str]] = []
            if expected_relation == "transitive_only":
                for hop in rubric_dimension.get("path_edges", []) or []:
                    if not isinstance(hop, dict):
                        continue
                    hop_source = str(hop.get("source", "")).strip()
                    hop_target = str(hop.get("target", "")).strip()
                    if (
                        not hop_source
                        or not hop_target
                        or (hop_source, hop_target) in current_edges
                    ):
                        continue
                    missing_path_edges.append(
                        {"source": hop_source, "target": hop_target}
                    )
            recommended_action = None
            acceptance_test = {
                "type": "minimum_dimension_score",
                "dimension": dimension_name,
                "minimum_score": 3.5,
            }
            if source and target and expected_relation == "transitive_only" and (
                missing_path_edges or not edge_present
            ):
                # A transitive_only dimension can be satisfied only by an
                # indirect path: add missing bridge edges and remove any
                # redundant direct edge as one atomic issue group.
                if edge_present:
                    recommended_action = {
                        "operation": "remove_edge",
                        "source": source,
                        "target": target,
                    }
                    acceptance_test = {
                        "type": "dependency_absent",
                        "source": source,
                        "target": target,
                    }
                elif missing_path_edges:
                    recommended_action = {
                        "operation": "add_edge",
                        "source": missing_path_edges[0]["source"],
                        "target": missing_path_edges[0]["target"],
                    }
                    acceptance_test = {
                        "type": "dependency_path_exists",
                        "source": source,
                        "target": target,
                    }
            elif source and target and not edge_present and evidence_status == "pass":
                recommended_action = {
                    "operation": "add_edge",
                    "source": source,
                    "target": target,
                }
                acceptance_test = {
                    "type": "dependency_exists",
                    "source": source,
                    "target": target,
                }
            elif source and target and edge_present and evidence_status == "warn":
                recommended_action = {
                    "operation": "remove_edge",
                    "source": source,
                    "target": target,
                }
                acceptance_test = {
                    "type": "dependency_absent",
                    "source": source,
                    "target": target,
                }
            issues.append(
                {
                    "issue_id": f"RUBRIC-{label}-{version_no}-{index + 1:03d}",
                    "category": "rubric_quality",
                    "severity": "high" if score < 2.5 else "medium",
                    "confidence": 0.75,
                    "fact_verification_status": evidence_verification,
                    "status": "open",
                    "found_in_version": version_no,
                    "target": (
                        {"source": source, "target": target}
                        if source and target
                        else {}
                    ),
                    "claim": dimension_name
                    or "A rubric dimension scored below the target.",
                    "evidence": [
                        {
                            "source": f"{label}_rubric",
                            "detail": (
                                f"Score: {score:.1f}/5. "
                                f"{dimension.get('reasoning', '')}"
                            ).strip(),
                        }
                    ],
                    "recommended_action": recommended_action,
                    "acceptance_test": acceptance_test,
                    "missing_path_edges": missing_path_edges,
                }
            )
    return issues


def _connectivity_deferred_operations(
    operations: List[Dict[str, Any]],
    current_edges: Set[Tuple[str, str]],
    nodes: Set[str],
) -> List[Dict[str, Any]]:
    """Return remove operations that would strand a node without in-edges.

    Workflow 194 regression: a repair batch that deletes the last in-edge of
    a node (``Collect -> Provide quote``) fails structural validation, the
    whole atomic batch is rolled back, and the run is rerouted to generation,
    which rebuilt a degraded chain graph.  Deferring such removes up front
    keeps the remaining operations applicable so the deterministic repair
    path survives.
    """

    def _in_degrees(edges: Set[Tuple[str, str]]) -> Dict[str, int]:
        degrees = {name: 0 for name in nodes}
        for _source, target in edges:
            if target in degrees:
                degrees[target] += 1
        return degrees

    before = _in_degrees(current_edges)
    after_edges = set(current_edges)
    for operation in operations:
        edge = (
            str(operation.get("source", "")).strip(),
            str(operation.get("target", "")).strip(),
        )
        name = str(operation.get("operation", "")).strip().lower()
        if name == "add_edge":
            after_edges.add(edge)
        elif name == "remove_edge":
            after_edges.discard(edge)
    after = _in_degrees(after_edges)
    dangling = {
        name
        for name, degree in after.items()
        if degree == 0 and before.get(name, 0) > 0
    }
    if not dangling:
        return []
    return [
        operation
        for operation in operations
        if str(operation.get("operation", "")).strip().lower() == "remove_edge"
        and str(operation.get("target", "")).strip() in dangling
    ]


def _build_repair_plan(
    version_no: int,
    issues: List[Dict[str, Any]],
    dag: Dict[str, Any],
    simulation: Dict[str, Any],
    task: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    nodes = {
        str(
            node.get("task")
            or node.get("name")
            or node.get("label")
            or node.get("id")
            or ""
        ).strip()
        for node in dag.get("task_nodes", [])
        if isinstance(node, dict)
    }
    nodes.discard("")
    current_edges = {
        _edge_key(link)
        for link in dag.get("task_links", [])
        if isinstance(link, dict) and all(_edge_key(link))
    }
    pass_edge_keys = {
        _edge_key(link)
        for link in simulation.get("task_links", [])
        if str(link.get("status") or link.get("log_status", "")).lower()
        == "pass"
    }
    protected_edge_keys = current_edges & pass_edge_keys

    candidates = []
    for issue in issues:
        action = issue.get("recommended_action")
        if not isinstance(action, dict):
            continue
        operation = str(action.get("operation", "")).strip().lower()
        priority = (
            1
            if issue.get("severity") == "high"
            else 2
            if issue.get("severity") == "medium"
            else 3
        )
        evidence = issue.get("evidence") or []
        reason = (
            evidence[0].get("detail", "")
            if evidence and isinstance(evidence[0], dict)
            else issue.get("claim", "")
        )

        if operation in {"add_edge", "remove_edge"}:
            source = str(action.get("source", "")).strip()
            target = str(action.get("target", "")).strip()
            edge = (source, target)
            if (
                not source
                or not target
                or source == target
                or source not in nodes
                or target not in nodes
            ):
                continue
            if operation == "add_edge" and edge in current_edges:
                continue
            if operation == "remove_edge" and (
                edge not in current_edges or edge in protected_edge_keys
            ):
                continue
            candidates.append(
                {
                    "issue_id": issue.get("issue_id"),
                    "priority": priority,
                    **action,
                    "reason": reason,
                    "acceptance_test": issue.get("acceptance_test"),
                }
            )
            # F4: Commit a transitive_only repair atomically with its primary
            # operation, adding missing bridge edges from the authoritative
            # log path. The target therefore always retains an incoming edge,
            # so the connectivity precheck does not defer the removal
            # (Workflow 199 applies remove Collect->Quote and add
            # Guide->Quote in the same batch).
            for hop in issue.get("missing_path_edges") or []:
                if not isinstance(hop, dict):
                    continue
                hop_source = str(hop.get("source", "")).strip()
                hop_target = str(hop.get("target", "")).strip()
                if (
                    not hop_source
                    or not hop_target
                    or hop_source == hop_target
                    or hop_source not in nodes
                    or hop_target not in nodes
                    or (hop_source, hop_target) in current_edges
                    or (hop_source, hop_target) == edge
                ):
                    continue
                candidates.append(
                    {
                        "issue_id": issue.get("issue_id"),
                        "priority": priority,
                        "operation": "add_edge",
                        "source": hop_source,
                        "target": hop_target,
                        "reason": (
                            f"Rebuild log path bridge for {source} -> {target}: "
                            + reason
                        ).strip(),
                        "acceptance_test": issue.get("acceptance_test"),
                    }
                )
            continue

        if operation != "insert_node_between":
            continue
        # Composite node insertion is intentionally evidence-gated.  Repair
        # plans cannot introduce a node proposed only in free-form reasoning.
        if str(issue.get("fact_verification_status", "")).lower() not in {
            "verified",
            "deterministic",
        }:
            continue
        raw_node = action.get("node")
        if not isinstance(raw_node, dict):
            continue
        node_name = str(
            raw_node.get("task")
            or raw_node.get("name")
            or raw_node.get("id")
            or ""
        ).strip()
        candidate = _ground_candidate_api(task, node_name)
        context = _log_insertion_context(dag, simulation, node_name)
        if (
            not node_name
            or _normalized_activity_name(node_name)
            in {_normalized_activity_name(name) for name in nodes}
            or candidate is None
            or not _requirement_mentions_activity(task, node_name)
            or context is None
        ):
            continue
        grounding = action.get("grounding")
        if (
            not isinstance(grounding, dict)
            or _normalized_activity_name(grounding.get("name"))
            != _normalized_activity_name(candidate.get("name"))
            or grounding.get("match_type")
            not in {"exact_candidate_api", "unique_token_match"}
        ):
            continue
        remove_edge_keys = {
            _edge_key(edge)
            for edge in context["remove_edges"]
            if isinstance(edge, dict) and all(_edge_key(edge))
        }
        # A user-confirmed PASS edge remains protected even when the log
        # suggests replacing it with an intermediate node.  Do not emit an
        # atomic insertion that the deterministic executor must reject.
        if remove_edge_keys & protected_edge_keys:
            continue
        candidates.append(
            {
                "issue_id": issue.get("issue_id"),
                # A grounded insertion must win over an edge-only removal of
                # the same bypass edge; otherwise the connectivity pre-check
                # defers the removal and the missing node remains unrepairable.
                "priority": 0,
                "operation": "insert_node_between",
                "node": {
                    "task": str(candidate["name"]).strip(),
                    "arguments": _derive_insert_arguments(
                        dag,
                        task,
                        candidate,
                        context["predecessors"],
                    ),
                },
                "predecessors": list(context["predecessors"]),
                "successors": list(context["successors"]),
                "remove_edges": list(context["remove_edges"]),
                "grounding": dict(grounding),
                "reason": reason,
                "acceptance_test": issue.get("acceptance_test"),
            }
        )

    # Resolve duplicate and contradictory suggestions deterministically.  The
    # highest-priority action for one edge wins; equal-priority ties keep the
    # first evidence item produced by the evaluator.
    operations = []
    selected_edges = set()
    selected_operations = set()
    selected_nodes = set()
    for candidate in sorted(
        candidates, key=lambda operation: operation.get("priority", 9)
    ):
        if candidate["operation"] == "insert_node_between":
            node_name = str((candidate.get("node") or {}).get("task", "")).strip()
            affected_edges = {
                _edge_key(edge)
                for edge in candidate.get("remove_edges", [])
                if isinstance(edge, dict) and all(_edge_key(edge))
            }
            affected_edges.update(
                (predecessor, node_name)
                for predecessor in candidate.get("predecessors", [])
            )
            affected_edges.update(
                (node_name, successor)
                for successor in candidate.get("successors", [])
            )
            normalized_node = _normalized_activity_name(node_name)
            if (
                not normalized_node
                or normalized_node in selected_nodes
                or affected_edges & selected_edges
            ):
                continue
            selected_nodes.add(normalized_node)
            selected_edges.update(affected_edges)
            selected_operations.add(
                ("insert_node_between", normalized_node, "")
            )
            operations.append(candidate)
            continue
        edge = (candidate["source"], candidate["target"])
        operation_key = (candidate["operation"], *edge)
        if edge in selected_edges or operation_key in selected_operations:
            continue
        selected_edges.add(edge)
        selected_operations.add(operation_key)
        operations.append(candidate)

    # Connectivity pre-check: a remove that would strand its target node gets
    # deferred instead of invalidating the whole atomic batch (Workflow 194).
    deferred_operations = _connectivity_deferred_operations(
        operations, current_edges, nodes
    )
    if deferred_operations:
        deferred_keys = {
            _repair_operation_key(operation) for operation in deferred_operations
        }
        operations = [
            operation
            for operation in operations
            if _repair_operation_key(operation) not in deferred_keys
        ]
        for operation in deferred_operations:
            operation["status"] = "deferred"
            operation["reason"] = (
                "Deferred: applying this removal would leave "
                f"'{operation.get('target')}' without any incoming edge and "
                "roll back the complete atomic repair batch."
            )

    pass_edges = [
        {"source": link.get("source"), "target": link.get("target")}
        for link in dag.get("task_links", [])
        if link.get("source")
        and link.get("target")
        and _edge_key(link) in pass_edge_keys
    ]
    return {
        "source_version": version_no,
        "operations": operations,
        "protected_edges": pass_edges,
        "deferred_operations": deferred_operations,
    }


def _issue_signature(issue: Dict[str, Any]) -> Tuple[str, str, str, str]:
    target = issue.get("target") or {}
    return (
        str(issue.get("category", "")),
        str(target.get("source", "")),
        str(target.get("target", "")),
        str(issue.get("claim", "")),
    )


class CoordinatorAgent:
    """Policy-driven Coordinator Agent for the workflow agent team."""

    def __init__(self, storage: Optional[WorkflowRunStorage] = None):
        self.storage = storage or WorkflowRunStorage()

    def _coordinate(
        self,
        run_id: str,
        *,
        step: str,
        message: str,
        event_type: str = "coordinator_decision",
        status: Optional[str] = None,
        version_no: Optional[int] = None,
        payload: Any = None,
    ) -> None:
        run = self.storage.get_run(run_id) or {}
        self.storage.update_run(
            run_id,
            status=status or run.get("status") or "pending",
            active_agent="coordinator",
            active_step=step,
        )
        self.storage.add_event(
            run_id,
            event_type,
            agent="coordinator",
            step=step,
            version_no=version_no,
            message=message,
            payload=payload,
        )

    @staticmethod
    def _structural_blockers(validation: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            issue
            for issue in validation.get("issues", [])
            if issue.get("category") in STRUCTURAL_REGENERATION_CATEGORIES
        ]

    async def execute(self, run_id: str) -> None:
        try:
            run = self.storage.get_run(run_id)
            if not run:
                return
            versions = self.storage.list_versions(run_id)
            self.storage.update_run(
                run_id,
                error_message=None,
                stop_requested=False,
                started_at=run.get("started_at") or now_ms(),
            )
            self.storage.add_event(
                run_id,
                "run_started",
                agent="coordinator",
                message="Coordinator Agent started the workflow run.",
            )
            if versions:
                self._coordinate(
                    run_id,
                    step="resume_run",
                    message="Coordinator Agent resumed the existing workflow run.",
                    event_type="coordinator_run_resumed",
                    version_no=int(versions[-1]["version_no"]),
                )
                current_version = versions[-1]
                dag = current_version["dag"]
                version_no = int(current_version["version_no"])
            else:
                self._coordinate(
                    run_id,
                    step="request_received",
                    message=(
                        "Coordinator Agent received the workflow request and "
                        "delegated initial modeling to Generation Agent."
                    ),
                    event_type="coordinator_request_received",
                    status="generating",
                    payload={"target_agent": "generation"},
                )
                dag = await self._generate_initial_dag(run_id, run)
                version_no = 1

            await self._optimization_loop(run_id, dag, version_no)
        except asyncio.CancelledError:
            self.storage.update_run(
                run_id,
                status="stopped",
                active_agent="coordinator",
                active_step="stopped",
                completed_at=now_ms(),
                error_message="The run was cancelled.",
            )
            self.storage.add_event(
                run_id,
                "coordinator_stopped",
                agent="coordinator",
                step="stopped",
                message="Coordinator Agent stopped the cancelled workflow run.",
            )
            raise
        except RunStopped:
            return
        except Exception as exc:
            self.storage.update_run(
                run_id,
                status="failed",
                active_agent="coordinator",
                active_step="failed",
                error_message=str(exc),
                completed_at=now_ms(),
            )
            self.storage.add_event(
                run_id,
                "run_failed",
                agent="coordinator",
                message=str(exc),
            )

    def apply_log_validation(
        self,
        run_id: str,
        version_no: int,
        updated_simulation: Dict[str, Any],
    ) -> Dict[str, Any]:
        version = self.storage.get_version(run_id, version_no)
        if not version:
            raise ValueError("Workflow version not found.")
        run = self.storage.get_run(run_id)
        task = self._build_task(run, version["dag"]) if run else None
        validation = version.get("validation_results") or validate_dag(
            version["dag"]
        )
        report = version.get("evaluation_report") or {}
        prior = (
            self.storage.get_version(run_id, version_no - 1)
            if version_no > 1
            else None
        )
        issues = _build_issues(
            version["dag"],
            validation,
            updated_simulation,
            report,
            version_no,
            task=task,
        )
        if prior and prior.get("issues"):
            current_signatures = {_issue_signature(issue) for issue in issues}
            prior_issues = []
            for prior_issue in prior["issues"]:
                still_present = _issue_signature(prior_issue) in current_signatures
                prior_issues.append(
                    {
                        **prior_issue,
                        "status": "unresolved" if still_present else "verified",
                        **(
                            {}
                            if still_present
                            else {"resolved_in_version": version_no}
                        ),
                    }
                )
            self.storage.update_version(
                run_id,
                int(prior["version_no"]),
                issues=prior_issues,
            )
        repair_plan = _build_repair_plan(
            version_no,
            issues,
            version["dag"],
            updated_simulation,
            task=task,
        )
        awaiting_review = bool(
            run
            and run.get("status") == "awaiting_review"
            and int(run.get("current_version") or 0) == version_no
        )
        self.storage.update_version(
            run_id,
            version_no,
            simulation_results=updated_simulation,
            issues=issues,
            repair_plan=repair_plan,
            status="awaiting_review" if awaiting_review else "evaluated",
        )
        self.storage.add_event(
            run_id,
            "log_validation_completed",
            agent="evaluation",
            version_no=version_no,
            message=f"Execution-log validation updated workflow version v{version_no}.",
        )
        if awaiting_review:
            self._coordinate(
                run_id,
                step="request_dependency_review",
                message=(
                    "Coordinator Agent received the execution log and is "
                    "waiting for the user's PASS/WARN dependency decisions."
                ),
                event_type="coordinator_user_input_required",
                status="awaiting_review",
                version_no=version_no,
                payload={"decision": "request_dependency_review"},
            )
        return self.storage.get_version(run_id, version_no) or version

    async def _generate_structurally_valid_dag(
        self,
        run_id: str,
        *,
        description: str,
        api_list: List[Dict[str, Any]],
        initial_feedback: str = "",
        source: str = "initial_generation",
    ) -> Tuple[Dict[str, Any], str]:
        """Ask Generation Agent for a candidate until the structural gate passes."""
        feedback = initial_feedback
        rejected_fingerprints = set()
        api_payload = json.dumps(
            [item.get("doc", item) for item in api_list],
            ensure_ascii=False,
        )

        for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
            self._coordinate(
                run_id,
                step="delegate_generation",
                message=(
                    "Coordinator Agent delegated DAG generation "
                    f"attempt {attempt} to Generation Agent."
                ),
                event_type="coordinator_delegated_generation",
                status="generating",
                payload={
                    "target_agent": "generation",
                    "generation_attempt": attempt,
                    "source": source,
                },
            )
            self._set_stage(
                run_id,
                status="generating",
                agent="generation",
                step="dag_generation",
                message=f"Building DAG candidate attempt {attempt}.",
            )
            dag_text = str(
                await write_dag_chain.ainvoke(
                    {
                        "text": description,
                        "api_list": api_payload,
                        "generation_feedback": feedback,
                    }
                )
            )
            dag = parse_dag(dag_text)
            self._check_stop(run_id)

            self._set_stage(
                run_id,
                status="evaluating",
                agent="evaluation",
                step="structural_validation",
                message=(
                    "Checking the generated candidate for cycles and "
                    "disconnected subgraphs."
                ),
            )
            validation = validate_dag(dag)
            blockers = self._structural_blockers(validation)
            fingerprint = dag_fingerprint(dag)
            repeated = fingerprint in rejected_fingerprints
            self.storage.add_event(
                run_id,
                "structural_validation_completed",
                agent="evaluation",
                step="structural_validation",
                message=(
                    f"Generation attempt {attempt} passed the structural gate."
                    if not blockers and not repeated
                    else f"Generation attempt {attempt} failed the structural gate."
                ),
                payload={
                    "generation_attempt": attempt,
                    "passed": not blockers and not repeated,
                    "component_count": validation.get("component_count", 0),
                    "issues": [
                        {
                            "category": issue.get("category"),
                            "claim": issue.get("claim"),
                        }
                        for issue in blockers
                    ],
                    "repeated_candidate": repeated,
                },
            )
            if not blockers and not repeated:
                self._coordinate(
                    run_id,
                    step="structural_gate_passed",
                    message=(
                        "Coordinator Agent accepted the structurally valid DAG "
                        "and will continue to workflow evaluation."
                    ),
                    event_type="coordinator_structural_decision",
                    status="evaluating",
                    payload={
                        "decision": "continue_evaluation",
                        "generation_attempt": attempt,
                    },
                )
                return dag, dag_text

            rejected_fingerprints.add(fingerprint)
            issue_lines = [
                f"- {issue.get('category')}: {issue.get('claim')}"
                for issue in blockers
            ]
            if repeated:
                issue_lines.append("- repeated_candidate: do not reproduce the previous DAG")
            feedback = (
                "Regenerate the complete DAG from the original task and API list.\n"
                "The candidate must be acyclic and form exactly one weakly connected graph.\n"
                + "\n".join(issue_lines)
                + "\nPrevious rejected DAG:\n"
                + json.dumps(dag, ensure_ascii=False)
            )
            if attempt < MAX_GENERATION_ATTEMPTS:
                self._coordinate(
                    run_id,
                    step="reroute_generation",
                    message=(
                        "Coordinator Agent rejected the candidate because of a hard "
                        "structural failure and routed it back to Generation Agent."
                    ),
                    event_type="coordinator_rerouted_generation",
                    status="generating",
                    payload={
                        "decision": "regenerate",
                        "target_agent": "generation",
                        "generation_attempt": attempt + 1,
                        "reason": [issue.get("category") for issue in blockers]
                        or ["repeated_candidate"],
                    },
                )
            else:
                self._coordinate(
                    run_id,
                    step="generation_failed",
                    message=(
                        "Coordinator Agent stopped regeneration because every "
                        "candidate failed the structural gate."
                    ),
                    event_type="coordinator_generation_failed",
                    status="failed",
                    payload={
                        "decision": "fail_run",
                        "generation_attempt": attempt,
                        "reason": [issue.get("category") for issue in blockers]
                        or ["repeated_candidate"],
                    },
                )

        raise ValueError(
            "Generation Agent could not produce an acyclic, connected DAG after "
            f"{MAX_GENERATION_ATTEMPTS} attempts."
        )

    async def _decompose_request(
        self,
        run_id: str,
        *,
        session_id: str,
        description: str,
    ) -> str:
        request_text = (
            description
            if description.lower().startswith("workflow:")
            else f"workflow: {description}"
        )
        timeout_seconds = _task_decomposition_timeout_seconds()
        try:
            response = await asyncio.wait_for(
                create_game_chain_with_history.ainvoke(
                    {"input": request_text},
                    config={"configurable": {"session_id": session_id}},
                ),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            message = (
                "Task decomposition timed out after "
                f"{timeout_seconds:g} seconds."
            )
            self.storage.add_event(
                run_id,
                "task_decomposition_timeout",
                agent="generation",
                step="task_decomposition",
                message=message,
                payload={"timeout_seconds": timeout_seconds},
            )
            raise RuntimeError(message) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            detail = str(exc).strip() or type(exc).__name__
            message = f"Task decomposition failed: {detail}"
            self.storage.add_event(
                run_id,
                "task_decomposition_failed",
                agent="generation",
                step="task_decomposition",
                message=message,
                payload={"error_type": type(exc).__name__},
            )
            raise RuntimeError(message) from exc

        extracted_task = str(response).strip()
        normalized_response = extracted_task.rstrip(".!").strip().upper()
        if (
            not extracted_task
            or normalized_response == "OK"
            or not parse_task_steps(extracted_task)
        ):
            message = "Task decomposition failed: the model returned no valid tasks."
            self.storage.add_event(
                run_id,
                "task_decomposition_failed",
                agent="generation",
                step="task_decomposition",
                message=message,
                payload={"error_type": "invalid_model_output"},
            )
            raise RuntimeError(message)
        return extracted_task

    async def _generate_initial_dag(
        self, run_id: str, run: Dict[str, Any]
    ) -> Dict[str, Any]:
        workflow_id = int(run["workflow_id"])
        rows = db.fetch_query(
            """
            SELECT id, create_game_session_id, describe, extracted_task,
                   rewrite_queries, api_list, dag
            FROM workflow
            WHERE id = %s
            LIMIT 1
            """,
            (workflow_id,),
        )
        if not rows:
            raise ValueError(f"Workflow {workflow_id} does not exist.")
        workflow = _as_dict(rows[0])
        session_id = workflow.get("create_game_session_id")
        if not session_id:
            raise ValueError("Workflow session ID is missing.")
        description = str(run.get("description") or workflow.get("describe") or "").strip()
        if not description:
            raise ValueError("Workflow description is empty.")

        self._set_stage(
            run_id,
            status="generating",
            agent="generation",
            step="task_decomposition",
            message="Decomposing the natural-language request.",
        )
        extracted_task = await self._decompose_request(
            run_id,
            session_id=session_id,
            description=description,
        )
        db.execute_query(
            "UPDATE workflow SET describe = %s, extracted_task = %s WHERE id = %s",
            (description, extracted_task, workflow_id),
        )
        self._check_stop(run_id)

        self._set_stage(
            run_id,
            status="generating",
            agent="generation",
            step="query_rewriting",
            message="Rewriting tasks into retrieval queries.",
        )
        queries = await asyncio.to_thread(rewrite_queries, extracted_task)
        if not queries:
            raise ValueError("Query rewriting returned no queries.")
        db.execute_query(
            "UPDATE workflow SET rewrite_queries = %s WHERE id = %s",
            (queries, workflow_id),
        )
        self._check_stop(run_id)

        self._set_stage(
            run_id,
            status="generating",
            agent="generation",
            step="api_retrieval",
            message="Retrieving APIs from the selected knowledge base.",
        )
        task_steps = parse_task_steps(extracted_task)
        retrieved_tools = await asyncio.to_thread(
            retrieve_tools,
            task_steps,
            queries,
            len(queries) + 5,
            len(queries) + 2,
        )
        api_list = tools_to_retrieved_docs(retrieved_tools)
        if not api_list:
            raise ValueError("API retrieval returned no tools.")
        db.execute_query(
            "UPDATE workflow SET api_list = %s WHERE id = %s",
            (json.dumps(api_list, ensure_ascii=False), workflow_id),
        )
        self._check_stop(run_id)

        dag, dag_text = await self._generate_structurally_valid_dag(
            run_id,
            description=description,
            api_list=api_list,
        )

        db.execute_query(
            """
            UPDATE workflow
            SET describe = %s,
                extracted_task = %s,
                rewrite_queries = %s,
                api_list = %s,
                dag = %s
            WHERE id = %s
            """,
            (
                description,
                extracted_task,
                queries,
                json.dumps(api_list, ensure_ascii=False),
                dag_text,
                workflow_id,
            ),
        )
        fingerprint = dag_fingerprint(dag)
        self.storage.create_version(
            run_id=run_id,
            workflow_id=workflow_id,
            version_no=1,
            parent_version_no=None,
            dag=dag,
            fingerprint=fingerprint,
        )
        self.storage.update_run(
            run_id,
            current_version=1,
            current_iteration=1,
        )
        self.storage.add_event(
            run_id,
            "version_created",
            agent="generation",
            version_no=1,
            message="Initial DAG version v1 was created.",
            payload={
                "node_count": len(dag.get("task_nodes", [])),
                "edge_count": len(dag.get("task_links", [])),
            },
        )
        return dag

    async def _regenerate_after_structural_failure(
        self,
        run_id: str,
        run: Dict[str, Any],
        invalid_dag: Dict[str, Any],
        blockers: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        rows = db.fetch_query(
            """
            SELECT describe, extracted_task, api_list
            FROM workflow
            WHERE id = %s
            LIMIT 1
            """,
            (int(run["workflow_id"]),),
        )
        workflow = _as_dict(rows[0]) if rows else {}
        api_list = workflow.get("api_list") or []
        if isinstance(api_list, str):
            try:
                api_list = json.loads(api_list)
            except json.JSONDecodeError:
                api_list = []
        if not isinstance(api_list, list) or not api_list:
            raise ValueError("Coordinator Agent cannot regenerate without the API list.")
        feedback = (
            "A previous DAG failed the Evaluation Agent structural gate.\n"
            "Regenerate the complete workflow as one acyclic, weakly connected DAG.\n"
            + "\n".join(
                f"- {issue.get('category')}: {issue.get('claim')}"
                for issue in blockers
            )
            + "\nRejected DAG:\n"
            + json.dumps(invalid_dag, ensure_ascii=False)
        )
        regenerated, _ = await self._generate_structurally_valid_dag(
            run_id,
            description=str(
                workflow.get("describe") or run.get("description") or ""
            ),
            api_list=api_list,
            initial_feedback=feedback,
            source="repair_structural_failure",
        )
        return regenerated

    async def _regenerate_after_low_score(
        self,
        run_id: str,
        run: Dict[str, Any],
        current_dag: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Regenerate the full DAG using the Evaluation Agent's feedback."""
        task = self._build_task(run, current_dag)
        api_list = task.get("api_list") or []
        if not isinstance(api_list, list) or not api_list:
            raise ValueError("Coordinator Agent cannot regenerate without the API list.")

        feedback = (
            "The current workflow requires complete regeneration rather than "
            "local edge repair because its overall score is below the routing "
            "threshold or it failed structural validation.\n"
            f"Composite score: {evaluation.get('composite_score', 0):.2f}\n"
            "Evaluation report:\n"
            + json.dumps(evaluation.get("report") or {}, ensure_ascii=False)
            + "\nCurrent DAG:\n"
            + json.dumps(current_dag, ensure_ascii=False)
        )
        regenerated, _ = await self._generate_structurally_valid_dag(
            run_id,
            description=str(
                task.get("user_request") or run.get("description") or ""
            ),
            api_list=api_list,
            initial_feedback=feedback,
            source="low_score_regeneration",
        )
        return regenerated

    async def _optimization_loop(
        self, run_id: str, dag: Dict[str, Any], version_no: int
    ) -> None:
        run = self.storage.get_run(run_id)
        if not run:
            return
        max_iterations = min(
            MAX_CONFIGURABLE_VERSIONS,
            max(1, int(run.get("max_iterations") or 3)),
        )
        best_score = -1.0
        best_version = run.get("best_version")
        no_improvement_rounds = 0

        existing_versions = self.storage.list_versions(run_id)
        for existing in existing_versions:
            value = existing.get("composite_score")
            if isinstance(value, (int, float)) and value > best_score:
                best_score = float(value)
                best_version = int(existing["version_no"])

        while version_no <= max_iterations:
            self._check_stop(run_id)
            self._coordinate(
                run_id,
                step="delegate_evaluation",
                message=(
                    f"Coordinator Agent delegated workflow version v{version_no} "
                    "to Evaluation Agent."
                ),
                event_type="coordinator_delegated_evaluation",
                status="evaluating" if version_no == 1 else "verifying",
                version_no=version_no,
                payload={"target_agent": "evaluation"},
            )
            result = await self._evaluate_version(
                run_id, version_no, dag, previous_version=version_no - 1
            )
            if result.get("paused"):
                return
            composite = result["composite_score"]
            if composite > best_score:
                best_score = composite
                best_version = version_no
                no_improvement_rounds = 0
                self.storage.update_run(run_id, best_version=best_version)
            else:
                no_improvement_rounds += 1

            if result["accepted"]:
                final_version_no = int(best_version or version_no)
                final_record = self.storage.get_version(
                    run_id, final_version_no
                )
                final_dag = (
                    final_record.get("dag") if final_record else dag
                )
                await self._finish_run(
                    run_id,
                    final_version_no,
                    final_dag,
                    status="completed",
                    message=(
                        f"Version v{version_no} passed the acceptance checks; "
                        f"the highest-scoring version v{final_version_no} was selected."
                    ),
                )
                return

            run = self.storage.get_run(run_id) or run
            if not run.get("auto_repair"):
                await self._finish_review(
                    run_id,
                    best_version or version_no,
                    "Automatic repair is disabled.",
                )
                return
            if version_no >= max_iterations:
                await self._finish_review(
                    run_id,
                    best_version or version_no,
                    "The maximum number of workflow versions was reached.",
                )
                return
            if no_improvement_rounds >= 2:
                await self._finish_review(
                    run_id,
                    best_version or version_no,
                    "Two consecutive versions did not improve the workflow score.",
                )
                return
            revision_log = None
            if result["routing_decision"] == "regenerate":
                routing_reason = (
                    "failed structural validation"
                    if result.get("structural_failure")
                    else (
                        f"received Composite score {composite:.2f}, below the "
                        "regeneration threshold"
                    )
                )
                self._coordinate(
                    run_id,
                    step="route_by_score",
                    message=(
                        f"Workflow v{version_no} {routing_reason}, so "
                        "Coordinator Agent routed it to Generation Agent."
                    ),
                    event_type="coordinator_score_routing",
                    status="generating",
                    version_no=version_no,
                    payload={
                        "decision": "regenerate",
                        "target_agent": "generation",
                        "composite_score": composite,
                        "regeneration_threshold": result[
                            "regeneration_threshold"
                        ],
                        "acceptance_threshold": result[
                            "acceptance_threshold"
                        ],
                        "structural_failure": result.get(
                            "structural_failure", False
                        ),
                    },
                )
                revised_dag = await self._regenerate_after_low_score(
                    run_id,
                    run,
                    dag,
                    result,
                )
                version_producer = "generation"
            else:
                if not result["repair_plan"].get("operations"):
                    await self._finish_review(
                        run_id,
                        best_version or version_no,
                        "The evaluation agent found no executable repair operation.",
                    )
                    return

                self._coordinate(
                    run_id,
                    step="delegate_repair",
                    message=(
                        f"Coordinator Agent delegated the v{version_no} repair plan "
                        "to Repair Agent."
                    ),
                    event_type="coordinator_delegated_repair",
                    status="repairing",
                    version_no=version_no,
                    payload={
                        "decision": "repair",
                        "target_agent": "repair",
                        "composite_score": composite,
                        "regeneration_threshold": result[
                            "regeneration_threshold"
                        ],
                        "acceptance_threshold": result[
                            "acceptance_threshold"
                        ],
                    },
                )
                revised_dag, revision_log = await self._repair_version(
                    run_id,
                    version_no,
                    dag,
                    result,
                )
                version_producer = (
                    "generation"
                    if revision_log.get("rerouted_to_generation")
                    else "repair"
                )
                self._set_stage(
                    run_id,
                    status="verifying",
                    agent="evaluation",
                    step="structural_validation",
                    version_no=version_no,
                    message=(
                        "Checking the repaired DAG structural integrity."
                        if version_producer == "repair"
                        else "Checking the regenerated DAG structural integrity."
                    ),
                )
                structural_validation = validate_dag(revised_dag)
                structural_blockers = self._structural_blockers(
                    structural_validation
                )
                self.storage.add_event(
                    run_id,
                    "structural_validation_completed",
                    agent="evaluation",
                    step="structural_validation",
                    version_no=version_no,
                    message=(
                        f"The {version_producer} DAG passed the structural gate."
                        if not structural_blockers
                        else f"The {version_producer} DAG failed the structural gate."
                    ),
                    payload={
                        "passed": not structural_blockers,
                        "component_count": structural_validation.get(
                            "component_count", 0
                        ),
                        "issues": [
                            {
                                "category": issue.get("category"),
                                "claim": issue.get("claim"),
                            }
                            for issue in structural_blockers
                        ],
                    },
                )
                if structural_blockers:
                    revision_log = {
                        **revision_log,
                        "outcome": (
                            "rejected_structural_failure"
                            if version_producer == "repair"
                            else revision_log.get("outcome", "")
                        ),
                        "structural_issues": [
                            issue.get("category") for issue in structural_blockers
                        ],
                    }
                    self.storage.add_event(
                        run_id,
                        "repair_revision_rejected",
                        agent="repair",
                        step="revision_log",
                        version_no=version_no,
                        message=(
                            "Repair Agent revision was rejected by the structural gate; "
                            "its log will not be reused as successful repair history."
                        ),
                        payload={
                            "operation_count": len(
                                revision_log.get("operations", [])
                            ),
                            "structural_issues": revision_log.get(
                                "structural_issues", []
                            ),
                        },
                    )
                    self._coordinate(
                        run_id,
                        step="reroute_generation",
                        message=(
                            "Coordinator Agent detected a cycle or disconnected "
                            "subgraph and routed regeneration to Generation Agent "
                            "instead of continuing with Repair Agent."
                        ),
                        event_type="coordinator_rerouted_generation",
                        status="generating",
                        version_no=version_no,
                        payload={
                            "decision": "regenerate",
                            "target_agent": "generation",
                            "reason": [
                                issue.get("category")
                                for issue in structural_blockers
                            ],
                        },
                    )
                    revised_dag = await self._regenerate_after_structural_failure(
                        run_id,
                        run,
                        revised_dag,
                        structural_blockers,
                    )
                    version_producer = "generation"
                else:
                    self._coordinate(
                        run_id,
                        step="structural_gate_passed",
                        message=(
                            f"Coordinator Agent accepted the {version_producer} DAG "
                            "and will continue verification."
                        ),
                        event_type="coordinator_structural_decision",
                        status="verifying",
                        version_no=version_no,
                        payload={"decision": "continue_evaluation"},
                    )
            revised_fingerprint = dag_fingerprint(revised_dag)
            if self.storage.fingerprint_exists(run_id, revised_fingerprint):
                await self._finish_review(
                    run_id,
                    best_version or version_no,
                    "The next DAG already exists in the version history.",
                )
                return

            next_version = version_no + 1
            summary = {
                **_dag_diff(dag, revised_dag),
                "producer": version_producer,
            }
            if version_producer == "repair":
                revision_log = {
                    **revision_log,
                    "outcome": "accepted_for_evaluation",
                }
                summary["revision_log"] = revision_log
            elif revision_log:
                summary["rejected_repair_revision_log"] = revision_log
            self.storage.create_version(
                run_id=run_id,
                workflow_id=int(run["workflow_id"]),
                version_no=next_version,
                parent_version_no=version_no,
                dag=revised_dag,
                fingerprint=revised_fingerprint,
                repair_plan=result["repair_plan"],
                repair_summary=summary,
            )
            self.storage.update_run(
                run_id,
                current_version=next_version,
                current_iteration=next_version,
            )
            self.storage.add_event(
                run_id,
                "version_created",
                agent=version_producer,
                version_no=next_version,
                message=(
                    f"Repair Agent created workflow version v{next_version}."
                    if version_producer == "repair"
                    else f"Generation Agent regenerated workflow version v{next_version}."
                ),
                payload={
                    "producer": version_producer,
                    "added_node_count": len(summary["added_nodes"]),
                    "removed_node_count": len(summary["removed_nodes"]),
                    "added_edge_count": len(summary["added_edges"]),
                    "removed_edge_count": len(summary["removed_edges"]),
                    "revision_operation_count": len(
                        (summary.get("revision_log") or {}).get(
                            "operations", []
                        )
                    ),
                },
            )
            dag = revised_dag
            version_no = next_version

    async def _evaluate_version(
        self,
        run_id: str,
        version_no: int,
        dag: Dict[str, Any],
        previous_version: int,
    ) -> Dict[str, Any]:
        run = self.storage.get_run(run_id)
        if not run:
            raise ValueError("Workflow run no longer exists.")
        task = self._build_task(run, dag)
        version = self.storage.get_version(run_id, version_no)
        if not version:
            raise ValueError("Workflow version no longer exists.")
        is_initial_evaluation = version_no == 1
        baseline_version = (
            version
            if is_initial_evaluation
            else self.storage.get_version(run_id, 1)
        )
        if not baseline_version:
            raise ValueError("The initial evaluation baseline is unavailable.")
        baseline_universal_rubric = baseline_version.get("universal_rubric")
        baseline_final_rubric = baseline_version.get("final_rubric")
        baseline_simulation = baseline_version.get("simulation_results") or {
            "task_links": []
        }
        review_confirmed = bool(
            is_initial_evaluation
            and version.get("status") == "review_confirmed"
        )
        if review_confirmed:
            validation = version.get("validation_results") or validate_dag(dag)
            universal_rubric = version.get("universal_rubric")
            simulation = version.get("simulation_results") or {"task_links": []}
        else:
            self._set_stage(
                run_id,
                status="evaluating" if is_initial_evaluation else "verifying",
                agent="evaluation",
                step="static_validation",
                version_no=version_no,
                message=f"Checking structural constraints for v{version_no}.",
            )
            tool_metadata = {}
            try:
                with open(
                    get_selected_tool_spi_path(),
                    "r",
                    encoding="utf-8",
                ) as handle:
                    tool_metadata = {
                        str(item.get("id", "")).strip(): item
                        for item in json.load(handle)
                        if item.get("id")
                    }
            except Exception:
                tool_metadata = {}
            validation = validate_dag(dag, tool_metadata=tool_metadata)
            self._check_stop(run_id)
            if is_initial_evaluation:
                universal_rubric = version.get("universal_rubric")
                self._set_stage(
                    run_id,
                    status="evaluating",
                    agent="evaluation",
                    step="discrepancy_analysis",
                    version_no=version_no,
                    message="Comparing independent dependency proposals for v1.",
                )
                simulation = await generate_simulation_results(task)
                self._check_stop(run_id)
                self.storage.update_version(
                    run_id,
                    version_no,
                    simulation_results=simulation,
                    universal_rubric=universal_rubric,
                    validation_results=validation,
                    hard_constraints_passed=validation.get(
                        "hard_constraints_passed", False
                    ),
                    status="awaiting_review",
                )
                self.storage.update_run(
                    run_id,
                    status="awaiting_review",
                    active_agent="coordinator",
                    active_step="request_user_input",
                    error_message=None,
                )
                self.storage.add_event(
                    run_id,
                    "coordinator_user_input_required",
                    agent="coordinator",
                    step="request_user_input",
                    version_no=version_no,
                    message=(
                        "Coordinator Agent requests an XES log and PASS/WARN "
                        "dependency decisions for the first evaluation."
                    ),
                    payload={
                        "decision": "request_user_input",
                        "edge_count": len(simulation.get("task_links", [])),
                        "warn_count": sum(
                            1
                            for link in simulation.get("task_links", [])
                            if str(link.get("status", "")).lower() == "warn"
                        ),
                    },
                )
                return {"paused": True}

            if (
                baseline_universal_rubric is None
                or baseline_final_rubric is None
            ):
                raise ValueError(
                    "The Evaluation rubric from v1 is unavailable."
                )
            universal_rubric = baseline_universal_rubric
            final_rubric = baseline_final_rubric
            simulation = {
                "task_links": [],
                "analysis_skipped": True,
                "reason": "Only the fixed v1 Evaluation rubric is used after v1.",
            }
            self.storage.update_version(
                run_id,
                version_no,
                simulation_results=simulation,
                universal_rubric=universal_rubric,
                final_rubric=final_rubric,
                validation_results=validation,
                hard_constraints_passed=validation.get(
                    "hard_constraints_passed", False
                ),
                status="evaluating",
            )
            self.storage.add_event(
                run_id,
                "evaluation_rubric_reused",
                agent="evaluation",
                version_no=version_no,
                message=f"Reusing the v1 Evaluation rubric to score v{version_no}.",
                payload={"source_version": 1},
            )

        if universal_rubric is None:
            if not is_initial_evaluation:
                raise ValueError("The Universal rubric from v1 is unavailable.")
            self._set_stage(
                run_id,
                status="evaluating",
                agent="evaluation",
                step="universal_rubric",
                version_no=version_no,
                message="Generating universal evaluation criteria.",
            )
            universal_rubric = await generate_universal_rubric(task)
            self.storage.update_version(
                run_id,
                version_no,
                universal_rubric=universal_rubric,
            )

        if is_initial_evaluation:
            self._set_stage(
                run_id,
                status="evaluating",
                agent="evaluation",
                step="task_specific_rubric",
                version_no=version_no,
                message="Generating criteria for disputed dependencies.",
            )
            final_rubric = await generate_task_specific_rubric(task, simulation)
            self.storage.update_version(
                run_id,
                version_no,
                final_rubric=final_rubric,
            )

        self._set_stage(
            run_id,
            status="evaluating" if is_initial_evaluation else "verifying",
            agent="evaluation",
            step="scoring",
            version_no=version_no,
            message=(
                "Scoring workflow version v1."
                if is_initial_evaluation
                else f"Scoring v{version_no} with the fixed v1 Evaluation rubric."
            ),
        )
        report = await generate_dag_report(
            task,
            rubric=final_rubric or None,
            conformance_results=simulation if is_initial_evaluation else None,
            universal_rubric=universal_rubric or None,
        )
        evaluated_dimensions = []
        for report_name in ("generic_report", "task_specific_report"):
            evaluated_dimensions.extend(
                (report.get(report_name) or {}).get("dimension_scores", [])
            )
        verified_dimensions = sum(
            str(item.get("evidence_verification", "")).lower()
            in {"verified", "deterministic"}
            for item in evaluated_dimensions
        )
        rejected_dimensions = sum(
            str(item.get("evidence_verification", "")).lower() == "failed"
            for item in evaluated_dimensions
        )
        self.storage.add_event(
            run_id,
            "dag_evidence_verification_completed",
            agent="evaluation",
            step="dag_evidence_verification",
            version_no=version_no,
            message=(
                "DAG Evidence Verification Tool checked the graph facts used "
                f"to score v{version_no}."
            ),
            payload={
                "dimension_count": len(evaluated_dimensions),
                "verified_dimension_count": verified_dimensions,
                "rejected_dimension_count": rejected_dimensions,
            },
        )
        repair_evidence = (
            simulation if is_initial_evaluation else baseline_simulation
        )
        issues = _build_issues(
            dag,
            validation,
            repair_evidence,
            report,
            version_no,
            final_rubric,
            include_dependency_issues=is_initial_evaluation,
            task=task,
        )
        repair_plan = _build_repair_plan(
            version_no,
            issues,
            dag,
            repair_evidence,
            task=task,
        )

        generic_score = _score(report, "generic_report")
        task_score = _score(report, "task_specific_report")
        composite_score = _composite_score(generic_score, task_score)
        regeneration_threshold = float(
            run.get("regeneration_threshold")
            if run.get("regeneration_threshold") is not None
            else DEFAULT_REGENERATION_THRESHOLD
        )
        acceptance_threshold = float(
            run.get("acceptance_threshold")
            if run.get("acceptance_threshold") is not None
            else DEFAULT_ACCEPTANCE_THRESHOLD
        )
        warn_count = sum(
            1
            for link in simulation.get("task_links", [])
            if str(link.get("status", "")).lower() == "warn"
        )
        structural_failure = bool(
            self._structural_blockers(validation)
        )
        deterministic_defect = _has_deterministic_defect(report)
        routing_decision = _coordination_decision(
            composite_score,
            regeneration_threshold,
            acceptance_threshold,
            structural_failure=structural_failure,
            deterministic_defect=deterministic_defect,
        )
        accepted = routing_decision == "accept"

        self.storage.update_version(
            run_id,
            version_no,
            simulation_results=simulation,
            universal_rubric=universal_rubric,
            final_rubric=final_rubric,
            evaluation_report=report,
            issues=issues,
            repair_plan=repair_plan,
            generic_score=generic_score,
            task_specific_score=task_score,
            composite_score=composite_score,
            hard_constraints_passed=validation.get(
                "hard_constraints_passed", False
            ),
            validation_results=validation,
            status="accepted" if accepted else "evaluated",
        )
        self.storage.add_event(
            run_id,
            "evaluation_completed",
            agent="evaluation",
            version_no=version_no,
            message=(
                f"v{version_no} passed evaluation."
                if accepted
                else f"v{version_no} requires further review or repair."
            ),
            payload={
                "generic_score": generic_score,
                "task_specific_score": task_score,
                "composite_score": composite_score,
                "warn_count": warn_count,
                "issue_count": len(issues),
                "routing_decision": routing_decision,
                "regeneration_threshold": regeneration_threshold,
                "acceptance_threshold": acceptance_threshold,
                "structural_failure": structural_failure,
                "deterministic_defect": deterministic_defect,
            },
        )
        return {
            "accepted": accepted,
            "simulation": simulation,
            "report": report,
            "issues": issues,
            "repair_plan": repair_plan,
            "composite_score": composite_score,
            "routing_decision": routing_decision,
            "regeneration_threshold": regeneration_threshold,
            "acceptance_threshold": acceptance_threshold,
            "structural_failure": structural_failure,
            "deterministic_defect": deterministic_defect,
        }

    async def _repair_version(
        self,
        run_id: str,
        version_no: int,
        dag: Dict[str, Any],
        evaluation: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        run = self.storage.get_run(run_id)
        if not run:
            raise ValueError("Workflow run no longer exists.")
        self._set_stage(
            run_id,
            status="repairing",
            agent="repair",
            step="apply_repair_plan",
            version_no=version_no,
            message=f"Applying the repair plan to v{version_no}.",
        )
        task = self._build_task(run, dag)
        repair_history = _repair_history_from_versions(
            self.storage.list_versions(run_id),
            limit=3,
        )
        repair_artifact = await workflow_regeneration_service(
            task,
            dag,
            evaluation["simulation"],
            evaluation_report=evaluation["report"],
            repair_plan=evaluation["repair_plan"],
            repair_history=repair_history,
            return_revision_log=True,
        )
        revised = repair_artifact.get("dag", {})
        if not revised.get("task_nodes"):
            raise ValueError("Repair agent returned a DAG without task nodes.")

        # Keep every original node and admit only node additions explicitly
        # authorized by insert_node_between.  This preserves the old defense
        # against an LLM rewriting the node set while allowing the deterministic
        # modification tool to perform the one new composite repair operation.
        planned_insertions: Dict[str, Dict[str, Any]] = {}
        for operation in evaluation["repair_plan"].get("operations", []):
            if (
                not isinstance(operation, dict)
                or str(operation.get("operation", "")).lower()
                != "insert_node_between"
            ):
                continue
            raw_node = operation.get("node") or {}
            name = str(
                raw_node.get("task") or raw_node.get("name") or ""
            ).strip()
            if name:
                planned_insertions[name] = dict(raw_node)

        returned_nodes = {
            str(
                node.get("task") or node.get("name") or node.get("id") or ""
            ).strip(): node
            for node in revised.get("task_nodes", [])
            if isinstance(node, dict)
        }
        sanitized_nodes = [
            dict(node) if isinstance(node, dict) else node
            for node in dag.get("task_nodes", [])
        ]
        original_names = {
            str(
                node.get("task") or node.get("name") or node.get("id") or ""
            ).strip()
            for node in sanitized_nodes
            if isinstance(node, dict)
        }
        for name, planned_node in planned_insertions.items():
            if name in returned_nodes and name not in original_names:
                sanitized_nodes.append(dict(planned_node))
                original_names.add(name)
        agent_changed_nodes = revised.get("task_nodes") != sanitized_nodes
        revised = {**revised, "task_nodes": sanitized_nodes}

        # PASS edges are protected by the repair plan. Restore one if any legacy
        # caller violates that contract so history cannot record a false repair.
        revised_links = []
        revised_edge_keys = set()
        for link in revised.get("task_links", []):
            if not isinstance(link, dict):
                continue
            edge = _edge_key(link)
            if not all(edge) or edge in revised_edge_keys:
                continue
            revised_links.append({"source": edge[0], "target": edge[1]})
            revised_edge_keys.add(edge)
        for protected in evaluation["repair_plan"].get("protected_edges", []):
            edge = _edge_key(protected)
            if all(edge) and edge not in revised_edge_keys:
                revised_links.append(
                    {"source": edge[0], "target": edge[1]}
                )
                revised_edge_keys.add(edge)
        revised["task_links"] = revised_links

        revision_log = _verify_revision_log(
            source_version=version_no,
            before=dag,
            after=revised,
            repair_plan=evaluation["repair_plan"],
            agent_revision_log=repair_artifact.get("revision_log"),
            repair_history=repair_history,
        )
        revision_log["agent_node_changes_discarded"] = agent_changed_nodes
        self.storage.add_event(
            run_id,
            "repair_revision_logged",
            agent="repair",
            step="revision_log",
            version_no=version_no,
            message=(
                "Repair Agent executed the structured plan with the DAG "
                "Modification Tool, and Coordinator Agent verified the result."
            ),
            payload={
                "operation_count": len(revision_log["operations"]),
                "history_entries_consulted": len(repair_history),
                "verification_status": revision_log["verification_status"],
                "agent_node_changes_discarded": agent_changed_nodes,
            },
        )
        if str(revision_log.get("outcome", "")).startswith("rejected_"):
            self.storage.add_event(
                run_id,
                "repair_revision_rejected",
                agent="repair",
                step="revision_log",
                version_no=version_no,
                message=(
                    "DAG Modification Tool rolled back the complete repair plan; "
                    "Coordinator Agent will request regeneration."
                ),
                payload={
                    "outcome": revision_log.get("outcome"),
                    "errors": revision_log.get("errors", []),
                    "structural_issues": revision_log.get(
                        "structural_issues", []
                    ),
                },
            )
            self._coordinate(
                run_id,
                step="reroute_generation",
                message=(
                    "Coordinator Agent routed the rejected atomic repair to "
                    "Generation Agent."
                ),
                event_type="coordinator_rerouted_generation",
                status="generating",
                version_no=version_no,
                payload={
                    "decision": "regenerate",
                    "target_agent": "generation",
                    "reason": revision_log.get("outcome"),
                },
            )
            revised = await self._regenerate_after_low_score(
                run_id,
                run,
                dag,
                evaluation,
            )
            revision_log["rerouted_to_generation"] = True
        self._check_stop(run_id)
        return revised, revision_log

    async def _finish_run(
        self,
        run_id: str,
        version_no: int,
        dag: Dict[str, Any],
        *,
        status: str,
        message: str,
    ) -> None:
        xml = await self._generate_xml(run_id, version_no, dag)
        run = self.storage.get_run(run_id)
        if run:
            db.execute_query(
                "UPDATE workflow SET xml = %s WHERE id = %s",
                (xml, int(run["workflow_id"])),
            )
        self.storage.update_run(
            run_id,
            status=status,
            active_agent="coordinator",
            active_step="completed",
            best_version=version_no,
            final_version=version_no,
            completed_at=now_ms(),
        )
        self.storage.add_event(
            run_id,
            "coordinator_completed",
            agent="coordinator",
            step="completed",
            version_no=version_no,
            message=f"Coordinator Agent selected v{version_no}. {message}",
            payload={"decision": "select_final_version"},
        )

    async def _finish_review(
        self, run_id: str, version_no: int, message: str
    ) -> None:
        version = self.storage.get_version(run_id, version_no)
        if version:
            await self._generate_xml(run_id, version_no, version["dag"])
        self.storage.update_run(
            run_id,
            status="needs_review",
            active_agent="coordinator",
            active_step="needs_review",
            final_version=version_no,
            completed_at=now_ms(),
            error_message=message,
        )
        self.storage.add_event(
            run_id,
            "coordinator_needs_review",
            agent="coordinator",
            step="needs_review",
            version_no=version_no,
            message=f"Coordinator Agent paused for user review. {message}",
            payload={"decision": "request_user_review"},
        )

    async def _generate_xml(
        self, run_id: str, version_no: int, dag: Dict[str, Any]
    ) -> str:
        self._set_stage(
            run_id,
            status="verifying",
            agent="evaluation",
            step="xml_generation",
            version_no=version_no,
            message=f"Generating XML for workflow version v{version_no}.",
        )
        xml = str(
            await write_xml_chain.ainvoke(
                {"dag": json.dumps(dag, ensure_ascii=False)}
            )
        )
        self.storage.update_version(run_id, version_no, xml=xml)
        return xml

    def _build_task(
        self, run: Dict[str, Any], dag: Dict[str, Any]
    ) -> Dict[str, Any]:
        rows = db.fetch_query(
            """
            SELECT describe, extracted_task, api_list
            FROM workflow
            WHERE id = %s
            LIMIT 1
            """,
            (int(run["workflow_id"]),),
        )
        workflow = _as_dict(rows[0]) if rows else {}
        api_list = workflow.get("api_list") or []
        if isinstance(api_list, str):
            try:
                api_list = json.loads(api_list)
            except (TypeError, ValueError, json.JSONDecodeError):
                api_list = []
        if not isinstance(api_list, list):
            api_list = []
        return {
            "id": str(run["workflow_id"]),
            "user_request": workflow.get("describe")
            or run.get("description")
            or "",
            "extracted_task": workflow.get("extracted_task") or "",
            "task_steps": parse_task_steps(
                workflow.get("extracted_task") or ""
            ),
            "task_nodes": dag.get("task_nodes", []),
            "task_links": dag.get("task_links", []),
            # Persisted retrieval results are the authoritative metadata snapshot
            # for every evaluation/repair iteration of this workflow.
            "api_list": api_list,
        }

    def _set_stage(
        self,
        run_id: str,
        *,
        status: str,
        agent: str,
        step: str,
        message: str,
        version_no: Optional[int] = None,
    ) -> None:
        self.storage.update_run(
            run_id,
            status=status,
            active_agent=agent,
            active_step=step,
            current_version=version_no
            if version_no is not None
            else (self.storage.get_run(run_id) or {}).get("current_version"),
        )
        self.storage.add_event(
            run_id,
            "agent_step_started",
            agent=agent,
            step=step,
            version_no=version_no,
            message=message,
        )

    def _check_stop(self, run_id: str) -> None:
        if self.storage.should_stop(run_id):
            self.storage.update_run(
                run_id,
                status="stopped",
                active_agent="coordinator",
                active_step="stopped",
                completed_at=now_ms(),
                error_message="Stopped by the user.",
            )
            self.storage.add_event(
                run_id,
                "coordinator_stopped",
                agent="coordinator",
                step="stopped",
                message="Coordinator Agent stopped the run at the user's request.",
            )
            raise RunStopped()
