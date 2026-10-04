"""Deterministically apply a structured repair plan to a workflow DAG.

The Repair Agent is allowed to decide *what* should change through the
structured repair plan.  This tool owns *how* those changes are applied.  It
never asks an LLM to rewrite the complete graph and it either commits the
whole plan or returns the original DAG unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional, Set, Tuple

from src.orchestration.validators import dag_fingerprint, validate_dag


SUPPORTED_OPERATIONS = {"add_edge", "remove_edge", "insert_node_between"}
STRUCTURAL_BLOCKERS = {
    "cycle",
    "disconnected_graph",
    "empty_graph",
    "self_loop",
    "invalid_reference",
    "structure",
}


def _node_name(node: Dict[str, Any]) -> str:
    return str(
        node.get("task")
        or node.get("name")
        or node.get("label")
        or node.get("id")
        or ""
    ).strip()


def _edge_key(value: Dict[str, Any]) -> Tuple[str, str]:
    return (
        str(value.get("source", "")).strip(),
        str(value.get("target", "")).strip(),
    )


def _ordered_names(value: Any) -> List[str]:
    """Return unique node names while preserving the supplied order."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    names: List[str] = []
    seen = set()
    for item in items:
        name = _node_name(item) if isinstance(item, dict) else str(item).strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _candidate_node(operation: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the candidate API node supplied by ``insert_node_between``."""
    raw = operation.get("node")
    if not isinstance(raw, dict):
        return None
    name = _node_name(raw)
    if not name:
        return None
    node = deepcopy(raw)
    # Downstream workflow serializers use ``task`` as the canonical node id.
    node["task"] = name
    node.setdefault("arguments", [])
    return node


def _insert_endpoints(operation: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    predecessors = _ordered_names(operation.get("predecessors"))
    successors = _ordered_names(operation.get("successors"))
    return predecessors, successors


def _raw_remove_edges(operation: Dict[str, Any]) -> Any:
    """Read the formal field, with the pre-release name as a compatibility alias."""
    if "remove_edges" in operation:
        return operation.get("remove_edges")
    if "bypass_edges" in operation:
        return operation.get("bypass_edges")
    return None


def _explicit_remove_edges(
    operation: Dict[str, Any],
) -> Optional[List[Tuple[str, str]]]:
    """Return dependencies explicitly requested for removal."""
    raw_edges = _raw_remove_edges(operation)
    if raw_edges is None:
        return None
    if not isinstance(raw_edges, list):
        return []
    edges: List[Tuple[str, str]] = []
    seen = set()
    for raw_edge in raw_edges:
        if not isinstance(raw_edge, dict):
            return []
        edge = _edge_key(raw_edge)
        if all(edge) and edge not in seen:
            seen.add(edge)
            edges.append(edge)
    return edges


def _operation_key(value: Dict[str, Any]) -> Tuple[str, str, str]:
    operation = str(value.get("operation", "")).strip().lower()
    if operation == "insert_node_between":
        node = _candidate_node(value)
        node_name = _node_name(node or {})
        predecessors, successors = _insert_endpoints(value)
        remove_edges = _explicit_remove_edges(value) or []
        removal_signature = ",".join(
            f"{source}->{target}" for source, target in remove_edges
        )
        wiring = (
            ",".join(predecessors)
            + "->"
            + ",".join(successors)
            + "|remove:"
            + removal_signature
        )
        return operation, node_name, wiring
    source, target = _edge_key(value)
    return (
        operation,
        source,
        target,
    )


def _history_statuses(
    history: Optional[List[Dict[str, Any]]],
) -> Dict[Tuple[str, str, str], List[str]]:
    statuses: Dict[Tuple[str, str, str], List[str]] = {}
    for revision in history or []:
        if not isinstance(revision, dict):
            continue
        for operation in revision.get("operations") or []:
            if not isinstance(operation, dict):
                continue
            key = _operation_key(operation)
            statuses.setdefault(key, []).append(
                str(operation.get("status", "")).strip()
            )
    return statuses


def _operation_log(
    operation: Any,
    *,
    status: str,
    detail: str,
    previous_statuses: Optional[List[str]] = None,
) -> Dict[str, Any]:
    item = operation if isinstance(operation, dict) else {}
    operation_name, source, target = _operation_key(item)
    result = {
        "issue_id": str(item.get("issue_id", "")).strip(),
        "operation": operation_name,
        "source": source,
        "target": target,
        "status": status,
        "reason": str(item.get("reason", "")).strip(),
        "detail": detail,
        "previously_recorded": bool(previous_statuses),
        "previous_statuses": list(previous_statuses or []),
    }
    if operation_name == "insert_node_between":
        candidate = _candidate_node(item)
        predecessors, successors = _insert_endpoints(item)
        remove_edges = _explicit_remove_edges(item)
        result.update(
            {
                "node": deepcopy(candidate) if candidate is not None else None,
                "predecessors": predecessors,
                "successors": successors,
                "remove_edges": [
                    {"source": edge_source, "target": edge_target}
                    for edge_source, edge_target in (remove_edges or [])
                ],
                "grounding": deepcopy(item.get("grounding")),
            }
        )
    return result


def _artifact(
    original: Dict[str, Any],
    operations: List[Dict[str, Any]],
    *,
    outcome: str,
    summary: str,
    revised: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    structural_issues: Optional[List[str]] = None,
    history_count: int = 0,
) -> Dict[str, Any]:
    result_dag = deepcopy(revised if revised is not None else original)
    return {
        "dag": result_dag,
        "revision_log": {
            "executor": "dag_modification_tool",
            "atomic": True,
            "outcome": outcome,
            "summary": summary,
            "operations": operations,
            "errors": list(errors or []),
            "structural_issues": list(structural_issues or []),
            "history_entries_consulted": history_count,
            "source_fingerprint": dag_fingerprint(original),
            "target_fingerprint": dag_fingerprint(result_dag),
        },
    }


def apply_dag_modifications(
    dag: Dict[str, Any],
    repair_plan: Dict[str, Any],
    *,
    repair_history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Apply every operation in ``repair_plan`` as one atomic batch.

    Besides the backward-compatible ``add_edge`` and ``remove_edge`` actions,
    ``insert_node_between`` can insert one grounded candidate API node, remove
    explicitly listed bypass dependencies, and connect all supplied
    predecessors and successors. Invalid operations or a structurally invalid
    resulting DAG reject the complete batch.
    """
    if not isinstance(dag, dict):
        raise TypeError("The current workflow DAG must be a dictionary.")
    if not isinstance(repair_plan, dict):
        raise TypeError("The repair plan must be a dictionary.")

    original = deepcopy(dag)
    raw_operations = repair_plan.get("operations", [])
    if not isinstance(raw_operations, list):
        raw_operations = []

    history_by_key = _history_statuses(repair_history)
    original_nodes = {
        _node_name(node)
        for node in original.get("task_nodes", [])
        if isinstance(node, dict) and _node_name(node)
    }
    edge_order: List[Tuple[str, str]] = []
    original_edges: Set[Tuple[str, str]] = set()
    for link in original.get("task_links", []):
        if not isinstance(link, dict):
            continue
        edge = _edge_key(link)
        if all(edge) and edge not in original_edges:
            edge_order.append(edge)
            original_edges.add(edge)
    protected_edges: Set[Tuple[str, str]] = {
        _edge_key(edge)
        for edge in repair_plan.get("protected_edges", [])
        if isinstance(edge, dict) and all(_edge_key(edge))
    }

    validation_errors: Dict[int, List[str]] = {}
    insert_specs: Dict[int, Dict[str, Any]] = {}
    inserted_nodes: Dict[str, Tuple[int, Dict[str, Any]]] = {}

    # First collect candidate nodes so ordinary edge operations in the same
    # atomic batch may safely reference a node inserted by another operation.
    for index, raw_operation in enumerate(raw_operations):
        if not isinstance(raw_operation, dict):
            continue
        if str(raw_operation.get("operation", "")).strip().lower() != "insert_node_between":
            continue
        candidate = _candidate_node(raw_operation)
        if candidate is None:
            validation_errors.setdefault(index, []).append(
                "insert_node_between requires node.task and node.arguments."
            )
            continue
        if not isinstance(raw_operation.get("node", {}).get("arguments"), list):
            validation_errors.setdefault(index, []).append(
                "node.arguments must be a list."
            )
        name = _node_name(candidate)
        previous = inserted_nodes.get(name)
        if previous and previous[1] != candidate:
            validation_errors.setdefault(index, []).append(
                "The same candidate node cannot be inserted with conflicting definitions."
            )
            validation_errors.setdefault(previous[0], []).append(
                "The same candidate node cannot be inserted with conflicting definitions."
            )
        else:
            inserted_nodes[name] = (index, candidate)

    prospective_nodes = original_nodes | set(inserted_nodes)
    edge_effects: Dict[Tuple[str, str], Dict[str, Set[int]]] = {}

    def register_edge_effect(
        edge: Tuple[str, str], effect: str, operation_index: int
    ) -> None:
        edge_effects.setdefault(edge, {}).setdefault(effect, set()).add(operation_index)

    for index, raw_operation in enumerate(raw_operations):
        errors: List[str] = []
        if not isinstance(raw_operation, dict):
            errors.append("The repair operation must be a JSON object.")
            validation_errors[index] = errors
            continue
        operation = str(raw_operation.get("operation", "")).strip().lower()
        if operation not in SUPPORTED_OPERATIONS:
            errors.append(
                "Only add_edge, remove_edge, and insert_node_between are supported by this tool."
            )
        elif operation in {"add_edge", "remove_edge"}:
            source, target = _edge_key(raw_operation)
            if not source or not target:
                errors.append("Both source and target are required.")
            elif source not in prospective_nodes or target not in prospective_nodes:
                errors.append("Both edge endpoints must reference DAG nodes in this repair batch.")
            elif source == target:
                errors.append("A self-loop cannot be added or removed as a repair.")
            if operation == "remove_edge" and (source, target) in protected_edges:
                errors.append("A protected PASS dependency cannot be removed.")
            if source and target:
                register_edge_effect((source, target), operation, index)
        else:
            candidate = _candidate_node(raw_operation)
            if candidate is not None:
                node_name = _node_name(candidate)
                predecessors, successors = _insert_endpoints(raw_operation)
                explicit_remove_edges = _explicit_remove_edges(raw_operation)
                if not isinstance(raw_operation.get("predecessors"), list):
                    errors.append("predecessors must be a list of DAG node names.")
                if not isinstance(raw_operation.get("successors"), list):
                    errors.append("successors must be a list of DAG node names.")
                if not predecessors or not successors:
                    errors.append(
                        "insert_node_between requires at least one predecessor and one successor."
                    )
                grounding = raw_operation.get("grounding")
                if not isinstance(grounding, dict) or not grounding:
                    errors.append(
                        "insert_node_between requires non-empty grounding metadata."
                    )
                invalid_endpoints = [
                    endpoint
                    for endpoint in [*predecessors, *successors]
                    if endpoint not in prospective_nodes or endpoint == node_name
                ]
                if invalid_endpoints:
                    errors.append(
                        "All predecessors and successors must reference other "
                        "DAG nodes in this repair batch."
                    )
                existing_node = next(
                    (
                        node
                        for node in original.get("task_nodes", [])
                        if isinstance(node, dict) and _node_name(node) == node_name
                    ),
                    None,
                )
                if existing_node is not None:
                    normalized_existing = deepcopy(existing_node)
                    normalized_existing["task"] = node_name
                    normalized_existing.setdefault("arguments", [])
                    if normalized_existing != candidate:
                        errors.append(
                            "A DAG node with this name already exists with a different definition."
                        )
                raw_remove_edges = _raw_remove_edges(raw_operation)
                if raw_remove_edges is None:
                    errors.append("insert_node_between requires remove_edges as a list.")
                elif not isinstance(raw_remove_edges, list):
                    errors.append("remove_edges must be a list of dependency objects.")
                elif any(
                    not isinstance(raw_edge, dict) or not all(_edge_key(raw_edge))
                    for raw_edge in raw_remove_edges
                ):
                    errors.append(
                        "Every remove_edges entry must contain a source and target."
                    )
                remove_edges = explicit_remove_edges or []
                for remove_edge in remove_edges:
                    if (
                        remove_edge[0] not in predecessors
                        or remove_edge[1] not in successors
                    ):
                        errors.append(
                            "Each remove_edges entry must connect a supplied "
                            "predecessor to a supplied successor."
                        )
                    if remove_edge in protected_edges:
                        errors.append(
                            "A protected PASS dependency cannot be removed by insert_node_between."
                        )
                    register_edge_effect(remove_edge, "remove_edge", index)
                for predecessor in predecessors:
                    register_edge_effect((predecessor, node_name), "add_edge", index)
                for successor in successors:
                    register_edge_effect((node_name, successor), "add_edge", index)
                insert_specs[index] = {
                    "candidate": candidate,
                    "predecessors": predecessors,
                    "successors": successors,
                    "remove_edges": remove_edges,
                }
        if errors:
            validation_errors.setdefault(index, []).extend(errors)

    conflicting_edges = {
        edge for edge, effects in edge_effects.items() if len(effects) > 1
    }
    if conflicting_edges:
        for edge in conflicting_edges:
            affected_indices = set().union(*edge_effects[edge].values())
            for index in affected_indices:
                validation_errors.setdefault(index, []).append(
                    "The same repair batch cannot both add and remove this edge."
                )

    if validation_errors:
        logs = []
        flattened_errors = []
        for index, raw_operation in enumerate(raw_operations):
            key = _operation_key(raw_operation) if isinstance(raw_operation, dict) else ("", "", "")
            errors = validation_errors.get(index, [])
            if errors:
                detail = " ".join(errors)
                status = "failed"
                flattened_errors.append(f"Operation {index + 1}: {detail}")
            else:
                detail = "Not executed because another operation invalidated the atomic batch."
                status = "rolled_back"
            logs.append(
                _operation_log(
                    raw_operation,
                    status=status,
                    detail=detail,
                    previous_statuses=history_by_key.get(key, []),
                )
            )
        return _artifact(
            original,
            logs,
            outcome="rejected_invalid_plan",
            summary="The repair plan was rejected before modifying the DAG.",
            errors=flattened_errors,
            history_count=len(repair_history or []),
        )

    edge_set: Set[Tuple[str, str]] = set(original_edges)
    revised_nodes = deepcopy(original.get("task_nodes", []))
    revised_node_names = set(original_nodes)

    operation_logs: List[Dict[str, Any]] = []
    for index, raw_operation in enumerate(raw_operations):
        operation, source, target = _operation_key(raw_operation)
        previous = history_by_key.get((operation, source, target), [])
        if operation == "insert_node_between":
            spec = insert_specs[index]
            candidate = spec["candidate"]
            node_name = _node_name(candidate)
            changed = False
            removed_count = 0
            added_count = 0
            if node_name not in revised_node_names:
                revised_nodes.append(deepcopy(candidate))
                revised_node_names.add(node_name)
                changed = True
            for remove_edge in spec["remove_edges"]:
                if remove_edge in edge_set:
                    edge_set.remove(remove_edge)
                    edge_order = [
                        edge for edge in edge_order if edge != remove_edge
                    ]
                    removed_count += 1
                    changed = True
            inserted_edges = [
                *((predecessor, node_name) for predecessor in spec["predecessors"]),
                *((node_name, successor) for successor in spec["successors"]),
            ]
            for inserted_edge in inserted_edges:
                if inserted_edge not in edge_set:
                    edge_set.add(inserted_edge)
                    edge_order.append(inserted_edge)
                    added_count += 1
                    changed = True
            if changed:
                status = "applied"
                detail = (
                    f"Inserted candidate API node '{node_name}', removed {removed_count} "
                    f"dependencies, and added {added_count} dependencies."
                )
            else:
                status = "already_satisfied"
                detail = (
                    f"Candidate API node '{node_name}' and all requested dependencies "
                    "already exist, while the requested removals are absent."
                )
        elif operation == "add_edge":
            edge = (source, target)
            if edge in edge_set:
                status = "already_satisfied"
                detail = "The requested dependency already exists in the current DAG."
            else:
                edge_set.add(edge)
                edge_order.append(edge)
                status = "applied"
                detail = "The requested dependency was added."
        else:
            edge = (source, target)
            if edge not in edge_set:
                status = "already_satisfied"
                detail = "The requested dependency is already absent from the current DAG."
            else:
                edge_set.remove(edge)
                edge_order = [candidate for candidate in edge_order if candidate != edge]
                status = "applied"
                detail = "The requested dependency was removed."
        operation_logs.append(
            _operation_log(
                raw_operation,
                status=status,
                detail=detail,
                previous_statuses=previous,
            )
        )

    revised = deepcopy(original)
    revised["task_links"] = [
        {"source": source, "target": target}
        for source, target in edge_order
        if (source, target) in edge_set
    ]
    revised["task_nodes"] = revised_nodes

    structural_validation = validate_dag(revised)
    structural_issues = [
        str(issue.get("category", ""))
        for issue in structural_validation.get("issues", [])
        if issue.get("category") in STRUCTURAL_BLOCKERS
    ]
    if structural_issues:
        rolled_back_logs = []
        for raw_operation, applied_log in zip(raw_operations, operation_logs):
            status = applied_log["status"]
            detail = applied_log["detail"]
            if status == "applied":
                status = "rolled_back"
                detail = (
                    "The operation was applied provisionally and rolled back because "
                    "the complete repair produced an invalid DAG."
                )
            rolled_back_logs.append(
                {
                    **applied_log,
                    "status": status,
                    "detail": detail,
                }
            )
        return _artifact(
            original,
            rolled_back_logs,
            outcome="rejected_structural_failure",
            summary=(
                "The complete repair batch was rolled back because the resulting "
                "workflow failed structural validation."
            ),
            structural_issues=structural_issues,
            history_count=len(repair_history or []),
        )

    applied_count = sum(
        item.get("status") == "applied" for item in operation_logs
    )
    return _artifact(
        original,
        operation_logs,
        outcome="applied",
        summary=(
            f"DAG Modification Tool completed {len(operation_logs)} repair "
            f"operations ({applied_count} changed the DAG)."
        ),
        revised=revised,
        history_count=len(repair_history or []),
    )


class DAGModificationTool:
    """Callable tool wrapper used by the Repair Agent."""

    name = "dag_modification"

    def run(
        self,
        dag: Dict[str, Any],
        repair_plan: Dict[str, Any],
        *,
        repair_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return apply_dag_modifications(
            dag,
            repair_plan,
            repair_history=repair_history,
        )

    __call__ = run
