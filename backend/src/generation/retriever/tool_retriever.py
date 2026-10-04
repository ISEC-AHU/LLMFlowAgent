from typing import List, Dict, Any


class ToolRetriever:
    """
    Tool retriever.

    Accepts original task steps from Stage 2 and rewritten queries from Stage
    3, then performs dual vector retrieval, deduplication, global sorting, and
    optional reranking. Query rewriting is performed independently upstream in
    Stage 3 rather than by this class.
    """

    def __init__(self, vector_store, reranker=None):
        self.vector_store = vector_store
        self.reranker = reranker

    def retrieve(
        self,
        original_steps: List[str],
        rewritten_queries: List[str],
        top_k: int = 15,
        rerank_n: int = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve candidate tools through two search paths.

        Args:
            original_steps: Stage 2 steps used for semantic relevance.
            rewritten_queries: Stage 3 queries used for terminology alignment.
            top_k: Number of tools to return.
            rerank_n: Number of tools retained after reranking, or ``None`` to
                disable reranking.
        """
        all_step_candidates = []

        n = max(len(original_steps), len(rewritten_queries))
        for i in range(n):
            # Path A: original steps for semantic relevance.
            if i < len(original_steps) and original_steps[i].strip():
                res_original = self.vector_store.search(original_steps[i], k=5)
                all_step_candidates.extend(res_original)
            # Path B: rewritten queries for terminology alignment.
            if i < len(rewritten_queries) and rewritten_queries[i].strip():
                res_enhanced = self.vector_store.search(rewritten_queries[i], k=5)
                all_step_candidates.extend(res_enhanced)

        # Deduplicate while retaining the highest score.
        id_to_tool = {}
        for t in all_step_candidates:
            tid = str(t["id"])
            score = t.get("retrieval_score", 0)
            if tid not in id_to_tool or score > id_to_tool[tid].get(
                "retrieval_score", 0
            ):
                id_to_tool[tid] = t

        # Sort globally.
        global_sorted_tools = sorted(
            id_to_tool.values(),
            key=lambda x: x.get("retrieval_score", 0),
            reverse=True,
        )

        # Rerank the merged candidates.
        if self.reranker and rerank_n:
            # Join the original steps to form the reranking context.
            original_context = " ".join(original_steps) or " ".join(rewritten_queries)
            refined_tools = self.reranker.rerank(
                query=original_context,
                documents=global_sorted_tools,
                top_n=rerank_n,
            )
            return refined_tools

        return global_sorted_tools[:top_k]
