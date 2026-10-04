# Add the project root to the Python path.
import os
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import dashscope
from dashscope import TextReRank
try:
    from src.llm_factory.factory import LLMFactory
except ImportError:
    from llm_factory.factory import LLMFactory


class Reranker:
    def __init__(self):
        # Use DashScope's gte-rerank model.
        dashscope.api_key = LLMFactory.get_dashscope_api_key()
        self.model = LLMFactory.get_rerank_model()

    def rerank(self, query: str, documents: list, top_n: int = 5):
        """
        Rerank tools using modality contracts and functional descriptions.
        """
        if not documents:
            return []

        # Clamp top_n to a valid range.
        safe_top_n = min(len(documents), top_n)
        if safe_top_n < 1:
            return []

        # Build structured text containing IDs, modality contracts, and
        # descriptions so the model can align input and output semantics.
        doc_texts = []
        for d in documents:
            in_types = ", ".join(d.get("input_type", []))
            out_types = ", ".join(d.get("output_type", []))
            desc = d.get("desc", d.get("description", ""))

            # Format the contract explicitly.
            formatted_text = (
                f"Tool: {d['id']}. "
                f"Inputs: [{in_types}]. "
                f"Outputs: [{out_types}]. "
                f"Function: {desc}"
            )
            doc_texts.append(formatted_text)

        try:
            # Invoke the DashScope reranking API.
            resp = TextReRank.call(
                model=self.model, query=query, documents=doc_texts, top_n=safe_top_n
            )

            if resp.status_code == 200:
                reranked_results = []
                for item in resp.output.results:
                    # Copy reranking scores back to the original tool objects.
                    original_doc = documents[item.index].copy()
                    original_doc["rerank_score"] = item.relevance_score
                    reranked_results.append(original_doc)
                return reranked_results
            else:
                print(f"❌ Rerank API call failed: {resp.message}")
                return documents[:safe_top_n]
        except Exception as e:
            print(f"❌ Reranking error: {e}")
            return documents[:safe_top_n]
