"""
Build a partial-order graph from an XES log and apply transitive reduction.

Process:
  1. Read activity traces from XES.
  2. Calculate eventually-follows support for every activity pair (A, B).
  3. Build a thresholded partial-order candidate graph.
  4. Break cycles by removing the weakest directional edge.
  5. Apply transitive reduction to retain the minimal partial order.

The result can validate whether log evidence supports workflow dependencies.
"""

from collections import defaultdict
from itertools import permutations
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import networkx as nx
from pm4py.objects.log.importer.xes import importer as xes_importer

Edge = Tuple[str, str]


# ---------------------------------------------------------------------------
# Read traces from an XES file.
# ---------------------------------------------------------------------------

def load_traces_from_xes(
    log_path: str,
    activity_key: str = "concept:name",
    lifecycle_transition: Optional[str] = None,
) -> List[List[str]]:
    """
    Read activity sequences from an XES log file.

    Args:
        log_path: Path to the XES file.
        activity_key: Activity-name attribute, usually ``concept:name``.
        lifecycle_transition:
            When set to ``complete``, include only events whose
            ``lifecycle:transition`` is ``complete``; ``None`` includes all events.

    Returns:
        Activity-name sequences, one list per trace.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If no valid trace exists or an activity attribute is missing.
    """
    path = Path(log_path)

    if not path.is_file():
        raise FileNotFoundError(f"XES file not found: {path}")

    log = xes_importer.apply(str(path))

    traces: List[List[str]] = []

    for trace_index, trace in enumerate(log):
        activities: List[str] = []

        for event_index, event in enumerate(trace):
            # Optionally retain only complete events.
            if lifecycle_transition is not None:
                transition = event.get("lifecycle:transition")
                if transition != lifecycle_transition:
                    continue

            activity = event.get(activity_key)
            if activity is None:
                raise ValueError(
                    f"Event {event_index} in trace {trace_index} "
                    f"is missing attribute {activity_key!r}"
                )

            activity = str(activity).strip()
            if activity:
                activities.append(activity)

        if activities:
            traces.append(activities)

    if not traces:
        raise ValueError("The XES file contains no valid traces.")

    return traces


# ---------------------------------------------------------------------------
# Build a partial-order candidate graph from eventually-follows relations.
# ---------------------------------------------------------------------------

def build_eventually_follows_graph(
    traces: List[List[str]],
    ef_threshold: float = 0.8,
    min_trace_count: int = 2,
    direction_margin: float = 0.1,
) -> Tuple[nx.DiGraph, Dict[str, Any]]:
    """
    Extract eventually-follows relations and build a candidate graph.

    For each activity pair (A, B), calculate:

        EF(A, B)
        = traces where A occurs before B / traces containing both A and B

    Add A -> B when:
      1. A and B co-occur at least ``min_trace_count`` times.
      2. EF(A, B) >= ef_threshold
      3. EF(A, B) - EF(B, A) >= ``direction_margin``, excluding likely concurrency.

    Args:
        traces: Activity sequences.
        ef_threshold: Eventually-follows threshold; defaults to 0.8.
        min_trace_count: Minimum co-occurring trace count; defaults to 2.
        direction_margin: Directional margin threshold; defaults to 0.1.

    Returns:
        (graph, statistics):
            graph: NetworkX directed graph with support-rate edge attributes.
            statistics: Statistics including ``pair_statistics``.

    Raises:
        ValueError: If an argument is outside its valid range.
    """
    if not 0.0 <= ef_threshold <= 1.0:
        raise ValueError("ef_threshold must be within [0, 1].")
    if min_trace_count < 1:
        raise ValueError("min_trace_count must be at least 1.")
    if not 0.0 <= direction_margin <= 1.0:
        raise ValueError("direction_margin must be within [0, 1].")

    cooccurrence_count: Dict[Edge, int] = defaultdict(int)
    eventually_count: Dict[Edge, int] = defaultdict(int)
    all_activities: Set[str] = set()

    for trace in traces:
        all_activities.update(trace)

        positions: Dict[str, List[int]] = defaultdict(list)
        for index, activity in enumerate(trace):
            positions[activity].append(index)

        present_activities = list(positions.keys())

        for source, target in permutations(present_activities, 2):
            pair = (source, target)
            cooccurrence_count[pair] += 1

            # Strict eventually-follows: at least one source occurrence precedes
            # at least one target occurrence.
            source_before_target = (
                min(positions[source]) < max(positions[target])
            )
            if source_before_target:
                eventually_count[pair] += 1

    graph = nx.DiGraph()
    graph.add_nodes_from(sorted(all_activities))

    pair_statistics: List[Dict[str, Any]] = []

    for (source, target), both_count in cooccurrence_count.items():
        support_count = eventually_count[(source, target)]
        support_rate = support_count / both_count

        reverse_pair = (target, source)
        reverse_both_count = cooccurrence_count.get(reverse_pair, 0)
        reverse_support_count = eventually_count.get(reverse_pair, 0)
        reverse_support_rate = (
            reverse_support_count / reverse_both_count
            if reverse_both_count > 0
            else 0.0
        )
        direction_strength = support_rate - reverse_support_rate

        pair_statistics.append({
            "source": source,
            "target": target,
            "support_rate": round(support_rate, 4),
            "reverse_support_rate": round(reverse_support_rate, 4),
            "direction_strength": round(direction_strength, 4),
            "trace_count": both_count,
            "support_count": support_count,
        })

        # Add the edge only when it meets all thresholds.
        if (
            both_count >= min_trace_count
            and support_rate >= ef_threshold
            and direction_strength >= direction_margin
        ):
            graph.add_edge(
                source, target,
                support_rate=support_rate,
                reverse_support_rate=reverse_support_rate,
                direction_strength=direction_strength,
                trace_count=both_count,
                support_count=support_count,
            )

    statistics = {
        "pair_statistics": pair_statistics,
        "cooccurrence_count": dict(cooccurrence_count),
        "eventually_count": dict(eventually_count),
    }

    return graph, statistics


# ---------------------------------------------------------------------------
# Remove cycles from the partial-order candidate graph.
# ---------------------------------------------------------------------------

def remove_cycles_by_weakest_edge(
    graph: nx.DiGraph,
) -> Tuple[nx.DiGraph, List[Dict[str, Any]]]:
    """
    Remove the weakest directional edge from each detected cycle.

    Transitive reduction requires a DAG, so cycles must be removed first.
    This heuristic handles log noise, loops, and repeated activities.
    """
    dag = graph.copy()
    removed_edges: List[Dict[str, Any]] = []

    while not nx.is_directed_acyclic_graph(dag):
        cycle = nx.find_cycle(dag, orientation="original")
        cycle_edges = [(s, t) for s, t, _ in cycle]

        # Prefer removing the edge with the smallest directional margin.
        weakest_source, weakest_target = min(
            cycle_edges,
            key=lambda edge: (
                dag.edges[edge].get("direction_strength", 0.0),
                dag.edges[edge].get("support_rate", 0.0),
                dag.edges[edge].get("trace_count", 0),
            ),
        )

        edge_data = dict(dag.edges[weakest_source, weakest_target])
        removed_edges.append({
            "source": weakest_source,
            "target": weakest_target,
            **edge_data,
            "reason": "removed_to_break_cycle",
        })
        dag.remove_edge(weakest_source, weakest_target)

    return dag, removed_edges


# ---------------------------------------------------------------------------
# Apply transitive reduction.
# ---------------------------------------------------------------------------

def transitive_reduce_with_attributes(
    dag: nx.DiGraph,
) -> nx.DiGraph:
    """
    Apply transitive reduction to a DAG.

    For example, before reduction: A -> B, B -> C, A -> C. Because C is
    reachable through A -> B -> C, A -> C is redundant. After reduction:
    A -> B, B -> C.

    Raises:
        nx.NetworkXError: If the input graph is not a DAG.
    """
    if not nx.is_directed_acyclic_graph(dag):
        raise nx.NetworkXError("Transitive reduction requires a DAG.")

    reduced_graph = nx.transitive_reduction(dag)

    # NetworkX drops edge attributes during reduction; restore them from the source.
    for source, target in reduced_graph.edges():
        reduced_graph.edges[source, target].update(
            dag.edges[source, target]
        )

    return reduced_graph


# ---------------------------------------------------------------------------
# Convert NetworkX edges to dictionaries.
# ---------------------------------------------------------------------------

def graph_edges_to_list(graph: nx.DiGraph) -> List[Dict[str, Any]]:
    """Convert graph edges to dictionaries suitable for JSON serialization."""
    result: List[Dict[str, Any]] = []

    for source, target, edge_data in sorted(graph.edges(data=True), key=lambda x: (x[0], x[1])):
        item: Dict[str, Any] = {"source": source, "target": target}
        for key, value in edge_data.items():
            if isinstance(value, float):
                value = round(value, 4)
            item[key] = value
        result.append(item)

    return result


# ---------------------------------------------------------------------------
# Build and reduce a partial-order graph from XES.
# ---------------------------------------------------------------------------

def infer_partial_order_from_xes(
    log_path: str,
    ef_threshold: float = 0.8,
    min_trace_count: int = 2,
    direction_margin: float = 0.1,
    lifecycle_transition: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build an eventually-follows candidate graph from XES and reduce it.

    Args:
        log_path: Path to the XES file.
        ef_threshold: Eventually-follows threshold; defaults to 0.8.
        min_trace_count: Minimum co-occurring trace count; defaults to 2.
        direction_margin: Directional margin threshold; defaults to 0.1.
        lifecycle_transition:
            ``complete`` reads only complete events; ``None`` reads all events.

    Returns:
        {
            "trace_count": int,
            "activity_count": int,
            "traces": List[List[str]],
            "precedence_edges": List[Dict],   # Candidate edges before reduction.
            "reduced_edges": List[Dict],       # Minimal edges retained after reduction.
            "transitive_edges": List[Dict],    # Edges removed by reduction.
            "cycle_removed_edges": List[Dict], # Edges removed to break cycles.
            "pair_statistics": List[Dict],     # Statistics for each activity pair.
        }
    """
    # Read activity sequences from XES.
    traces = load_traces_from_xes(
        log_path=log_path,
        lifecycle_transition=lifecycle_transition,
    )

    # Build the eventually-follows candidate graph.
    candidate_graph, statistics = build_eventually_follows_graph(
        traces=traces,
        ef_threshold=ef_threshold,
        min_trace_count=min_trace_count,
        direction_margin=direction_margin,
    )

    # Ensure the graph is a DAG.
    precedence_graph, cycle_removed_edges = remove_cycles_by_weakest_edge(candidate_graph)

    # Apply transitive reduction.
    reduced_graph = transitive_reduce_with_attributes(precedence_graph)

    precedence_edge_set = set(precedence_graph.edges())
    reduced_edge_set = set(reduced_graph.edges())
    transitive_edge_set = precedence_edge_set - reduced_edge_set

    transitive_edges: List[Dict[str, Any]] = []
    for source, target in sorted(transitive_edge_set):
        edge_data = dict(precedence_graph.edges[source, target])
        item: Dict[str, Any] = {"source": source, "target": target, "reason": "removed_by_transitive_reduction"}
        for key, value in edge_data.items():
            if isinstance(value, float):
                value = round(value, 4)
            item[key] = value
        transitive_edges.append(item)

    return {
        "trace_count": len(traces),
        "activity_count": precedence_graph.number_of_nodes(),
        "traces": traces,
        "precedence_edges": graph_edges_to_list(precedence_graph),
        "reduced_edges": graph_edges_to_list(reduced_graph),
        "transitive_edges": transitive_edges,
        "cycle_removed_edges": cycle_removed_edges,
        "pair_statistics": statistics["pair_statistics"],
    }
