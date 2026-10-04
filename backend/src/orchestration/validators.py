import hashlib
import json
from typing import Any, Dict, List, Set, Tuple


def _node_name(node: Dict[str, Any]) -> str:
    return str(
        node.get("task")
        or node.get("name")
        or node.get("label")
        or node.get("id")
        or ""
    ).strip()


def dag_fingerprint(dag: Dict[str, Any]) -> str:
    nodes = sorted(
        _node_name(node)
        for node in dag.get("task_nodes", [])
        if _node_name(node)
    )
    edges = sorted(
        (
            str(link.get("source", "")).strip(),
            str(link.get("target", "")).strip(),
        )
        for link in dag.get("task_links", [])
        if link.get("source") and link.get("target")
    )
    canonical = json.dumps(
        {"nodes": nodes, "edges": edges},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_dag(
    dag: Dict[str, Any],
    tool_metadata: Dict[str, Dict[str, Any]] = None,
) -> Dict[str, Any]:
    nodes = {
        _node_name(node)
        for node in dag.get("task_nodes", [])
        if _node_name(node)
    }
    edges: List[Tuple[str, str]] = []
    issues: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    metadata = tool_metadata or {}

    if not nodes:
        issues.append(
            {
                "issue_id": "STRUCT-EMPTY-DAG",
                "category": "empty_graph",
                "severity": "high",
                "claim": "The generated workflow contains no task nodes.",
                "evidence": [
                    {
                        "source": "static_validator",
                        "detail": "task_nodes is empty.",
                    }
                ],
                "recommended_action": {"operation": "regenerate_dag"},
            }
        )

    if metadata:
        for index, node in enumerate(dag.get("task_nodes", [])):
            name = _node_name(node)
            if name and name not in metadata:
                issues.append(
                    {
                        "issue_id": f"TOOL-MISSING-{index}",
                        "category": "unknown_tool",
                        "severity": "high",
                        "claim": f"Tool '{name}' is not present in the selected knowledge base.",
                        "evidence": [
                            {
                                "source": "tool_catalog",
                                "detail": "The node could not be resolved against tools_spi.json.",
                            }
                        ],
                        "recommended_action": {
                            "operation": "replace_node",
                            "node": name,
                        },
                    }
                )

    for index, link in enumerate(dag.get("task_links", [])):
        source = str(link.get("source", "")).strip()
        target = str(link.get("target", "")).strip()
        if not source or not target:
            issues.append(
                {
                    "issue_id": f"STRUCT-EMPTY-{index}",
                    "category": "structure",
                    "severity": "high",
                    "claim": "A dependency edge has an empty endpoint.",
                    "evidence": [{"source": "static_validator", "detail": str(link)}],
                    "recommended_action": {
                        "operation": "remove_invalid_edge",
                        "edge": link,
                    },
                }
            )
            continue
        edge = (source, target)
        edges.append(edge)
        if source == target:
            issues.append(
                {
                    "issue_id": f"STRUCT-SELF-{index}",
                    "category": "self_loop",
                    "severity": "high",
                    "target": {"source": source, "target": target},
                    "claim": "A workflow node cannot depend on itself.",
                    "evidence": [{"source": "static_validator", "detail": "Self-loop detected."}],
                    "recommended_action": {
                        "operation": "remove_edge",
                        "source": source,
                        "target": target,
                    },
                }
            )
        if source not in nodes or target not in nodes:
            issues.append(
                {
                    "issue_id": f"STRUCT-REF-{index}",
                    "category": "invalid_reference",
                    "severity": "high",
                    "target": {"source": source, "target": target},
                    "claim": "A dependency references a node that is not present in the DAG.",
                    "evidence": [
                        {
                            "source": "static_validator",
                            "detail": f"Known nodes: {sorted(nodes)}",
                        }
                    ],
                    "recommended_action": {
                        "operation": "remove_or_retarget_edge",
                        "source": source,
                        "target": target,
                    },
                }
            )
        if edge in seen:
            issues.append(
                {
                    "issue_id": f"STRUCT-DUP-{index}",
                    "category": "duplicate_edge",
                    "severity": "low",
                    "target": {"source": source, "target": target},
                    "claim": "The same dependency is declared more than once.",
                    "evidence": [{"source": "static_validator", "detail": "Duplicate edge."}],
                    "recommended_action": {
                        "operation": "remove_duplicate_edge",
                        "source": source,
                        "target": target,
                    },
                }
            )
        seen.add(edge)

        source_tool = metadata.get(source)
        target_tool = metadata.get(target)
        if source_tool and target_tool:
            outputs = {
                str(value).strip().lower()
                for value in source_tool.get("output_type", [])
                if str(value).strip()
            }
            inputs = {
                str(value).strip().lower()
                for value in target_tool.get("input_type", [])
                if str(value).strip()
            }
            if outputs and inputs and outputs.isdisjoint(inputs):
                issues.append(
                    {
                        "issue_id": f"TOOL-IO-{index}",
                        "category": "io_compatibility",
                        "severity": "medium",
                        "target": {"source": source, "target": target},
                        "claim": "The connected tools have no directly compatible input/output type.",
                        "evidence": [
                            {
                                "source": "tool_catalog",
                                "detail": (
                                    f"{source} outputs {sorted(outputs)}; "
                                    f"{target} accepts {sorted(inputs)}."
                                ),
                            }
                        ],
                        "recommended_action": {
                            "operation": "review_or_insert_adapter",
                            "source": source,
                            "target": target,
                        },
                    }
                )

    adjacency = {node: [] for node in nodes}
    undirected = {node: set() for node in nodes}
    indegree = {node: 0 for node in nodes}
    for source, target in seen:
        if source in nodes and target in nodes and source != target:
            adjacency[source].append(target)
            indegree[target] += 1
            undirected[source].add(target)
            undirected[target].add(source)

    components: List[List[str]] = []
    remaining = set(nodes)
    while remaining:
        root = next(iter(remaining))
        frontier = [root]
        component: Set[str] = set()
        while frontier:
            node = frontier.pop()
            if node in component:
                continue
            component.add(node)
            frontier.extend(undirected.get(node, set()) - component)
        remaining -= component
        components.append(sorted(component))

    if len(components) > 1:
        issues.append(
            {
                "issue_id": "STRUCT-DISCONNECTED",
                "category": "disconnected_graph",
                "severity": "high",
                "claim": (
                    f"The workflow is split into {len(components)} disconnected subgraphs."
                ),
                "evidence": [
                    {
                        "source": "static_validator",
                        "detail": f"Weakly connected components: {components}",
                    }
                ],
                "recommended_action": {
                    "operation": "regenerate_connected_dag",
                    "components": components,
                },
            }
        )

    queue = [node for node, degree in indegree.items() if degree == 0]
    visited = 0
    while queue:
        node = queue.pop()
        visited += 1
        for target in adjacency[node]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)

    if nodes and visited != len(nodes):
        issues.append(
            {
                "issue_id": "STRUCT-CYCLE",
                "category": "cycle",
                "severity": "high",
                "claim": "The workflow contains at least one directed cycle.",
                "evidence": [
                    {
                        "source": "static_validator",
                        "detail": "Topological sorting did not visit every node.",
                    }
                ],
                "recommended_action": {
                    "operation": "break_cycle",
                },
            }
        )

    hard_constraints_passed = not any(
        issue.get("severity") == "high" for issue in issues
    )
    return {
        "valid": hard_constraints_passed,
        "hard_constraints_passed": hard_constraints_passed,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "component_count": len(components),
        "components": components,
        "issues": issues,
    }
