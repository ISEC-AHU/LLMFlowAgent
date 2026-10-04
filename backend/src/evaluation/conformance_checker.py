"""
Conformance checker for edge-level validation against a partial-order graph.

Uses an execution log (.xes) as ground truth and validates workflow dependency
edges with an eventually-follows partial-order graph and transitive reduction.

Process:
  1. Build an eventually-follows candidate graph from XES.
  2. Remove cycles by deleting the weakest directional edge.
  3. Apply transitive reduction to retain the minimal partial-order edge set.
  4. Validate workflow dependencies against the retained edges.

Status rules:
  - Edge retained after reduction -> pass (directly supported by the log).
  - Edge present before but removed by reduction -> warn (transitively
    redundant rather than a direct dependency).
  - Edge absent from the partial-order graph -> warn (unsupported by the log).
"""

import os

# Limit threads before loading pm4py (NumPy/OpenBLAS) to avoid Windows memory
# allocation failures.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")

from typing import Any, Dict, List


def validate_edges_with_log(
    edges: List[Dict[str, Any]],
    log_path: str,
    threshold: float = 0.8,
) -> Dict[str, Any]:
    """
    Validate dependency edges against an execution log.

    Process:
      1. Build an eventually-follows candidate graph from XES.
      2. Remove cycles by deleting the weakest directional edge.
      3. Apply transitive reduction to retain the minimal edge set.
      4. Validate workflow dependencies against retained edges.

    The log is ground truth: retained edges pass, transitively redundant edges
    warn, and edges absent from the partial-order graph warn.

    Args:
        edges: Edges to validate, including source, target, and status fields.
        log_path: Path to the .xes log file.
        threshold: Eventually-follows threshold; defaults to 0.8.

    Returns:
        {
            "task_links": List[Dict],   # Edges with status overridden by log evidence.
            "trace_count": int,         # Total trace count.
            "log_reduced_edges": List[Dict], # Complete reduced log edge set.
        }
    """
    from src.evaluation.log_partial_order import infer_partial_order_from_xes

    # Build and transitively reduce the XES partial-order graph.
    result = infer_partial_order_from_xes(
        log_path=log_path,
        ef_threshold=threshold,
        min_trace_count=2,
        direction_margin=0.1,
        lifecycle_transition=None,
    )

    # Extract edge sets.
    reduced_edge_set = {
        (e["source"], e["target"]) for e in result["reduced_edges"]
    }
    precedence_edge_set = {
        (e["source"], e["target"]) for e in result["precedence_edges"]
    }

    # Index pair statistics for EF rates and trace counts.
    pair_stats_map = {}
    for stat in result["pair_statistics"]:
        pair_stats_map[(stat["source"], stat["target"])] = stat

    # Validate every workflow dependency edge.
    updated_edges: List[Dict[str, Any]] = []

    for edge in edges:
        source = edge.get("source", "")
        target = edge.get("target", "")
        pair = (source, target)

        stat = pair_stats_map.get(pair, {})
        trace_count = stat.get("trace_count", 0)

        updated_edge = dict(edge)

        if pair in reduced_edge_set:
            # Retained after reduction: direct log support.
            updated_edge["status"] = "pass"
            updated_edge["log_support_rate"] = 1.0
            updated_edge["log_trace_count"] = trace_count
            updated_edge["log_edge_type"] = "direct"
        elif pair in precedence_edge_set:
            # Present before reduction: transitively redundant edge.
            updated_edge["status"] = "warn"
            updated_edge["log_support_rate"] = 0.5
            updated_edge["log_trace_count"] = trace_count
            updated_edge["log_edge_type"] = "transitive"
        else:
            # Absent from the partial-order graph: unsupported by the log.
            ef_rate = stat.get("support_rate", 0.0)
            updated_edge["status"] = "warn"
            updated_edge["log_support_rate"] = round(ef_rate, 4)
            updated_edge["log_trace_count"] = trace_count
            updated_edge["log_edge_type"] = "unsupported"

        updated_edges.append(updated_edge)

    pass_count = sum(1 for e in updated_edges if e["status"] == "pass")
    warn_count = sum(1 for e in updated_edges if e["status"] == "warn")
    print(
        f"📊 Log-Edge Validation (Partial Order + Transitive Reduction): "
        f"{result['trace_count']} traces, "
        f"{len(result['reduced_edges'])} reduced edges, "
        f"{len(updated_edges)} workflow edges, "
        f"pass={pass_count} warn={warn_count}"
    )

    return {
        "task_links": updated_edges,
        "trace_count": result["trace_count"],
        # Keep the complete reduced edge set, not only the dependencies that
        # happened to be proposed by the multi-model analysis.  A verified
        # missing activity is absent from those proposals by definition, so
        # its predecessor/successor evidence can only be recovered here.
        "log_reduced_edges": [dict(edge) for edge in result["reduced_edges"]],
    }
