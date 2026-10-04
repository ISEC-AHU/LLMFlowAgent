import json
import os
import sys
import time

import dashscope
import faiss
import numpy as np
from dashscope import TextEmbedding

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from src.llm_factory.factory import LLMFactory
except ImportError:
    from llm_factory.factory import LLMFactory


class VectorStore:
    def __init__(
        self,
        index_path=None,
        map_path=None,
        model=None,
        dimension=1536,
    ):
        if not index_path or not map_path:
            raise ValueError(
                "index_path and map_path are required. "
                "Use knowledge_service.get_selected_tool_index_path() "
                "and get_selected_tool_map_path() to obtain them."
            )
        api_key = LLMFactory.get_dashscope_api_key()
        if not api_key:
            raise ValueError("DashScope api_key is not configured in backend/config/llm_providers.yaml")
        dashscope.api_key = api_key

        try:
            self.index = faiss.read_index(index_path)
            with open(map_path, "r", encoding="utf-8") as f:
                self.tool_list = json.load(f)
        except Exception as e:
            print(f"❌ Index load failed: {e}")
            raise e

        self.model = model or LLMFactory.get_embedding_model() or TextEmbedding.Models.text_embedding_v2
        self.dimension = dimension
        # print(f"🔍 VectorStore loaded | model: {self.model}")

    def _get_query_embedding(self, query: str, max_retries=3):
        retries = 0
        while retries < max_retries:
            try:
                kwargs = {"model": self.model, "input": query}
                if "v3" in self.model:
                    kwargs["dimension"] = self.dimension

                resp = TextEmbedding.call(**kwargs)

                if resp.status_code == 200:
                    embedding = np.array(
                        resp.output["embeddings"][0]["embedding"]
                    ).astype("float32")
                    faiss.normalize_L2(embedding.reshape(1, -1))
                    return embedding

                print(f"⚠️ Embedding API error: {resp.message}, retry {retries + 1}...")
            except Exception as e:
                print(f"❌ Embedding request failed: {e}, retrying...")

            retries += 1
            time.sleep(2)

        raise Exception(f"Failed to get embedding after {max_retries} retries.")

    def search(self, query: str, k: int = 5):
        query_vector = self._get_query_embedding(query).reshape(1, -1)
        distances, indices = self.index.search(query_vector, k)

        results = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx != -1 and idx < len(self.tool_list):
                tool = self.tool_list[idx].copy()
                tool["retrieval_score"] = float(dist)
                results.append(tool)
        return results
