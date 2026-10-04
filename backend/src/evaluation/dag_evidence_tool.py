"""Deterministic verification of factual claims about a workflow DAG.

The tool deliberately performs no model calls.  It treats ``task_nodes`` and
``task_links`` in the supplied DAG as the only authoritative evidence and
compares that evidence with an ``observed`` boolean supplied by each claim.
"""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


SUPPORTED_PREDICATES = frozenset(
    {"node_exists", "direct_edge_exists", "path_exists"}
)

_TRUE_STRINGS = frozenset({"true", "1", "yes"})
_FALSE_STRINGS = frozenset({"false", "0", "no"})


def _text(value: Any) -> str:
    """Return a trimmed string without treating ``None`` as text."""

    return "" if value is None else str(value).strip()


def _node_name(node: Any) -> str:
    if isinstance(node, Mapping):
        return _text(
            node.get("task")
            or node.get("name")
            or node.get("label")
            or node.get("id")
        )
    return _text(node)


def _normalize_predicate(value: Any) -> str:
    return _text(value).lower().replace("-", "_").replace(" ", "_")


def _normalize_boolean(value: Any) -> Tuple[Optional[bool], Optional[str]]:
    if isinstance(value, bool):
        return value, None
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _TRUE_STRINGS:
            return True, None
        if normalized in _FALSE_STRINGS:
            return False, None
    return None, "invalid_observed_boolean"


def _dag_facts(
    dag: Mapping[str, Any],
) -> Tuple[set[str], set[Tuple[str, str]], Dict[str, set[str]]]:
    nodes = {
        name
        for name in (_node_name(node) for node in dag.get("task_nodes", []) or [])
        if name
    }
    edges: set[Tuple[str, str]] = set()
    adjacency: Dict[str, set[str]] = {}
    for link in dag.get("task_links", []) or []:
        if not isinstance(link, Mapping):
            continue
        source = _text(link.get("source"))
        target = _text(link.get("target"))
        if not source or not target:
            continue
        edges.add((source, target))
        adjacency.setdefault(source, set()).add(target)
    return nodes, edges, adjacency


def _path_exists(adjacency: Mapping[str, set[str]], source: str, target: str) -> bool:
    """Return whether a directed path of at least one edge exists."""

    queue = deque([source])
    visited = {source}
    while queue:
        current = queue.popleft()
        for successor in adjacency.get(current, set()):
            if successor == target:
                return True
            if successor not in visited:
                visited.add(successor)
                queue.append(successor)
    return False


def evaluate_dag_evidence(
    dag: Mapping[str, Any], claims: Optional[Iterable[Mapping[str, Any]]]
) -> Dict[str, Any]:
    """Verify model-observed DAG facts using deterministic graph operations.

    Supported claims are:

    * ``node_exists`` with a non-empty ``node``;
    * ``direct_edge_exists`` with non-empty ``source`` and ``target``; and
    * ``path_exists`` with non-empty ``source`` and ``target``.

    Each normalized check records the claimed ``observed`` value, the
    deterministically calculated ``actual`` value, and whether they agree.
    Malformed claims are returned as invalid checks instead of being skipped.
    """

    if not isinstance(dag, Mapping):
        raise TypeError("dag must be a mapping")

    nodes, edges, adjacency = _dag_facts(dag)
    checks: List[Dict[str, Any]] = []

    for index, raw_claim in enumerate(claims or []):
        if not isinstance(raw_claim, Mapping):
            checks.append(
                {
                    "index": index,
                    "predicate": "",
                    "node": "",
                    "source": "",
                    "target": "",
                    "observed": None,
                    "actual": None,
                    "valid": False,
                    "error": "claim_must_be_an_object",
                }
            )
            continue

        predicate = _normalize_predicate(raw_claim.get("predicate"))
        node = _text(raw_claim.get("node"))
        source = _text(raw_claim.get("source"))
        target = _text(raw_claim.get("target"))
        observed, observed_error = _normalize_boolean(raw_claim.get("observed"))
        error = observed_error
        actual: Optional[bool] = None

        if predicate not in SUPPORTED_PREDICATES:
            error = "unsupported_predicate"
        elif predicate == "node_exists":
            if not node:
                error = "missing_node"
            else:
                actual = node in nodes
        elif not source or not target:
            error = "missing_edge_endpoint"
        elif source not in nodes or target not in nodes:
            error = "unknown_edge_endpoint"
        elif source == target:
            error = "self_relation_is_not_valid_evidence"
        elif predicate == "direct_edge_exists":
            actual = (source, target) in edges
        else:
            actual = _path_exists(adjacency, source, target)

        valid = error is None and observed == actual
        checks.append(
            {
                "index": index,
                "predicate": predicate,
                "node": node,
                "source": source,
                "target": target,
                "observed": observed,
                "actual": actual,
                "valid": valid,
                "error": error,
            }
        )

    valid_count = sum(1 for check in checks if check["valid"])
    return {
        "checks": checks,
        "valid_count": valid_count,
        "invalid_count": len(checks) - valid_count,
    }


class DAGEvidenceTool:
    """Small callable wrapper for agent/tool integrations."""

    name = "evaluation_dag_evidence"

    def run(
        self,
        dag: Mapping[str, Any],
        claims: Optional[Iterable[Mapping[str, Any]]],
    ) -> Dict[str, Any]:
        return evaluate_dag_evidence(dag, claims)

    __call__ = run
