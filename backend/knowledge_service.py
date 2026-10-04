"""
Unified tool knowledge service.

This module is the single backend entry point for tool/API knowledge retrieval.
It uses the same FAISS/tool-map implementation for workflow generation,
evaluation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from functools import lru_cache
from typing import Any, Dict, List


BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_SRC = os.path.join(BACKEND_DIR, "src")
KNOWLEDGE_BASE_DIR = os.path.join(BACKEND_DIR, "knowledge_bases")
REGISTRY_PATH = os.path.join(KNOWLEDGE_BASE_DIR, "registry.json")
REGISTRY_PATH_FIELDS = (
    "tool_spi_path",
    "tool_map_path",
    "tool_index_path",
    "storage_dir",
)


def _ensure_backend_src_path() -> None:
    if BACKEND_SRC not in sys.path:
        sys.path.insert(0, BACKEND_SRC)


def _safe_name(name: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name.strip())
    return cleaned.strip("._") or "knowledge_base"


def _resolve_registry_path(path: str) -> str:
    """Resolve a registry path relative to the backend directory."""
    if not path:
        return ""
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.abspath(os.path.join(BACKEND_DIR, path))


def _load_record_paths(record: Dict[str, Any]) -> Dict[str, Any]:
    loaded = dict(record)
    for field in REGISTRY_PATH_FIELDS:
        loaded[field] = _resolve_registry_path(str(loaded.get(field) or ""))
    return loaded


def _store_record_paths(record: Dict[str, Any]) -> Dict[str, Any]:
    stored = dict(record)
    for field in REGISTRY_PATH_FIELDS:
        value = _resolve_registry_path(str(stored.get(field) or ""))
        if not value:
            stored[field] = ""
            continue
        try:
            if os.path.commonpath((BACKEND_DIR, value)) == BACKEND_DIR:
                stored[field] = os.path.relpath(value, BACKEND_DIR).replace(os.sep, "/")
            else:
                stored[field] = value
        except ValueError:
            stored[field] = value
    return stored


def _load_registry() -> Dict[str, Any]:
    os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
    if not os.path.exists(REGISTRY_PATH):
        registry = {"selected": "", "collections": []}
        _save_registry(registry)
        return registry

    with open(REGISTRY_PATH, "r", encoding="utf-8") as f:
        registry = json.load(f)

    collections = [
        _load_record_paths(item) for item in (registry.get("collections") or [])
    ]
    selected = registry.get("selected") or ""
    if selected and not any(item.get("collection_name") == selected for item in collections):
        selected = collections[0].get("collection_name") if collections else ""
    for item in collections:
        item["is_selected"] = item.get("collection_name") == selected
    registry["selected"] = selected
    registry["collections"] = collections
    return registry


def _save_registry(registry: Dict[str, Any]) -> None:
    os.makedirs(KNOWLEDGE_BASE_DIR, exist_ok=True)
    selected = registry.get("selected") or ""
    collections = []
    for item in registry.get("collections", []):
        stored = _store_record_paths(item)
        stored["is_selected"] = stored.get("collection_name") == selected
        collections.append(stored)
    payload = {**registry, "selected": selected, "collections": collections}
    with open(REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)


def _selected_record() -> Dict[str, Any]:
    registry = _load_registry()
    selected = registry.get("selected") or ""
    for item in registry.get("collections", []):
        if item.get("collection_name") == selected:
            return item
    raise ValueError("No knowledge base is selected. Create or select a FAISS knowledge base first.")


def get_selected_tool_spi_path() -> str:
    return _selected_record().get("tool_spi_path", "")


def get_selected_tool_map_path() -> str:
    return _selected_record().get("tool_map_path", "")


def get_selected_tool_index_path() -> str:
    return _selected_record().get("tool_index_path", "")


def reset_tool_retriever_cache() -> None:
    get_tool_retriever.cache_clear()


@lru_cache(maxsize=1)
def get_tool_retriever():
    _ensure_backend_src_path()

    from generation.retriever.reranker import Reranker
    from generation.retriever.tool_retriever import ToolRetriever
    from generation.retriever.vector_store import VectorStore

    vector_store = VectorStore(
        index_path=get_selected_tool_index_path(),
        map_path=get_selected_tool_map_path(),
    )
    reranker = Reranker()
    return ToolRetriever(
        vector_store=vector_store,
        reranker=reranker,
    )


@lru_cache(maxsize=1)
def get_query_rewriter():
    """Return a standalone QueryRewriter instance for the Stage 3 rewrite endpoint."""
    _ensure_backend_src_path()

    from generation.retriever.query_rewriter import QueryRewriter
    from generation.retriever.vector_store import VectorStore

    vector_store = VectorStore(
        index_path=get_selected_tool_index_path(),#tool_index_path
        map_path=get_selected_tool_map_path(),#tool_map_path
    )
    return QueryRewriter(vector_store=vector_store)


def rewrite_queries(text: str) -> List[str]:
    """
    Split task text into steps and use QueryRewriter to generate technical search queries.
    Used by POST /workflow/rewrite as a replacement for LangChain rewrite_query.
    """
    steps = [s.strip() for s in text.split("\n") if s.strip()]
    if not steps:
        return []
    return get_query_rewriter().rewrite(steps)


def retrieve_tools(
    original_steps: List[str],
    rewritten_queries: List[str],
    top_k: int = 15,
    rerank_n: int = 12,
) -> List[Dict[str, Any]]:
    """
    Retrieve candidate tools through both retrieval paths.

    Args:
        original_steps: Original task steps from Stage 2.
        rewritten_queries: Rewritten queries from Stage 3.
        top_k: Number of tools to return.
        rerank_n: Number of tools retained after reranking.
    """
    cleaned_original = [s.strip() for s in (original_steps or []) if s and s.strip()]
    cleaned_rewritten = [s.strip() for s in (rewritten_queries or []) if s and s.strip()]
    if not cleaned_original and not cleaned_rewritten:
        return []

    return get_tool_retriever().retrieve(
        original_steps=cleaned_original,
        rewritten_queries=cleaned_rewritten,
        top_k=top_k,
        rerank_n=rerank_n,
    )


def tool_to_retrieved_doc(tool: Dict[str, Any]) -> Dict[str, Any]:
    page_content = {
        "id": tool.get("id"),
        "name": tool.get("name") or tool.get("id"),
        "desc": tool.get("desc") or tool.get("description", ""),
        "description": tool.get("description") or tool.get("desc", ""),
        "input_type": tool.get("input_type") or tool.get("input-type") or [],
        "output_type": tool.get("output_type") or tool.get("output-type") or [],
        "retrieval_score": tool.get("retrieval_score"),
        "rerank_score": tool.get("rerank_score"),
    }
    return {
        "doc": {
            "metadata": {
                "source": "knowledge_service",
                "tool_id": page_content["id"],
                "retrieval_backend": "faiss_tool_map",
            },
            "page_content": json.dumps(page_content, ensure_ascii=False),
            "type": "Tool",
        },
        "status": 1,
    }


def tools_to_retrieved_docs(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [tool_to_retrieved_doc(tool) for tool in tools]


def list_builtin_knowledge_bases() -> List[Dict[str, Any]]:
    collections = _load_registry().get("collections", [])
    result = []
    for item in collections:
        row = dict(item)
        try:
            with open(row.get("tool_map_path", ""), "r", encoding="utf-8") as f:
                row["tool_count"] = len(json.load(f))
        except Exception:
            row["tool_count"] = None
        result.append(row)
    return result


def _normalize_tool(raw: Dict[str, Any]) -> Dict[str, Any]:
    tool_id = raw.get("id") or raw.get("name") or raw.get("tool_id")
    if not tool_id:
        raise ValueError("Each tool must contain id/name/tool_id")

    desc = raw.get("desc") or raw.get("description") or raw.get("function") or ""
    input_type = raw.get("input_type") or raw.get("input-type") or raw.get("inputs") or []
    output_type = raw.get("output_type") or raw.get("output-type") or raw.get("outputs") or []
    if isinstance(input_type, str):
        input_type = [item.strip() for item in input_type.split(",") if item.strip()]
    if isinstance(output_type, str):
        output_type = [item.strip() for item in output_type.split(",") if item.strip()]

    metadata = raw.get("metadata_for_embedding")
    if not metadata:
        metadata = (
            f"Tool ID: {tool_id}. Function: {desc}. "
            f"Input Requirements: {', '.join(input_type)}. "
            f"Output Modality: {', '.join(output_type)}."
        )

    return {
        "id": tool_id,
        "desc": desc,
        "input_type": input_type,
        "output_type": output_type,
        "metadata_for_embedding": metadata,
    }


def _load_tools_from_upload(file_bytes: bytes) -> List[Dict[str, Any]]:
    data = json.loads(file_bytes.decode("utf-8"))
    if isinstance(data, dict):
        if isinstance(data.get("tools"), list):
            data = data["tools"]
        elif isinstance(data.get("nodes"), list):
            data = data["nodes"]
        else:
            raise ValueError("JSON object must contain a tools or nodes list")
    if not isinstance(data, list):
        raise ValueError("Knowledge base upload must be a JSON list or an object with tools/nodes")
    return [_normalize_tool(item) for item in data]


def _build_faiss_index(tools: List[Dict[str, Any]], output_dir: str) -> None:
    _ensure_backend_src_path()

    import dashscope
    import faiss
    import numpy as np
    from dashscope import TextEmbedding
    from src.llm_factory.factory import LLMFactory

    dashscope.api_key = LLMFactory.get_dashscope_api_key()
    if not dashscope.api_key:
        raise ValueError("DashScope api_key is not configured in backend/config/llm_providers.yaml")

    texts = [tool["metadata_for_embedding"] for tool in tools]
    embeddings = []
    batch_size = 10
    for i in range(0, len(texts), batch_size):
        batch = texts[i: i + batch_size]
        resp = TextEmbedding.call(model=LLMFactory.get_embedding_model(), input=batch)
        if resp.status_code != 200:
            raise RuntimeError(f"Embedding API error: {resp.message}")
        embeddings.extend(item["embedding"] for item in resp.output["embeddings"])

    embeddings_array = np.array(embeddings).astype("float32")
    faiss.normalize_L2(embeddings_array)
    index = faiss.IndexFlatIP(embeddings_array.shape[1])
    index.add(embeddings_array)

    os.makedirs(output_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(output_dir, "tools.index"))
    with open(os.path.join(output_dir, "tool_map.json"), "w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)
    with open(os.path.join(output_dir, "tools_spi.json"), "w", encoding="utf-8") as f:
        json.dump(tools, f, indent=2, ensure_ascii=False)


def create_knowledge_base(
    collection_name: str,
    collection_describe: str,
    create_time: str,
    file_bytes: bytes,
) -> Dict[str, Any]:
    registry = _load_registry()
    if any(item.get("collection_name") == collection_name for item in registry.get("collections", [])):
        raise ValueError(f"Knowledge base already exists: {collection_name}")

    tools = _load_tools_from_upload(file_bytes)
    safe = _safe_name(collection_name)
    storage_dir = os.path.join(KNOWLEDGE_BASE_DIR, safe)
    if os.path.exists(storage_dir):
        safe = f"{safe}_{create_time or 'new'}"
        storage_dir = os.path.join(KNOWLEDGE_BASE_DIR, safe)

    _build_faiss_index(tools, storage_dir)

    record = {
        "collection_name": collection_name,
        "collection_describe": collection_describe or "",
        "create_time": create_time,
        "is_selected": False,
        "retrieval_backend": "faiss_tool_map",
        "tool_spi_path": os.path.join(storage_dir, "tools_spi.json"),
        "tool_map_path": os.path.join(storage_dir, "tool_map.json"),
        "tool_index_path": os.path.join(storage_dir, "tools.index"),
        "storage_dir": storage_dir,
    }
    registry["collections"].append(record)
    _save_registry(registry)
    return record


def select_knowledge_base(collection_name: str) -> Dict[str, Any]:
    registry = _load_registry()
    if not any(item.get("collection_name") == collection_name for item in registry.get("collections", [])):
        raise ValueError(f"Knowledge base not found: {collection_name}")
    registry["selected"] = collection_name
    _save_registry(registry)
    reset_tool_retriever_cache()
    return _selected_record()


def delete_knowledge_base(collection_name: str) -> None:
    registry = _load_registry()
    target = None
    kept = []
    for item in registry.get("collections", []):
        if item.get("collection_name") == collection_name:
            target = item
        else:
            kept.append(item)

    if target is None:
        raise ValueError(f"Knowledge base not found: {collection_name}")

    storage_dir = target.get("storage_dir")
    if storage_dir and os.path.abspath(storage_dir).startswith(os.path.abspath(KNOWLEDGE_BASE_DIR)) and os.path.exists(storage_dir):
        shutil.rmtree(storage_dir)

    registry["collections"] = kept
    if registry.get("selected") == collection_name:
        registry["selected"] = kept[0].get("collection_name") if kept else ""
    _save_registry(registry)
    reset_tool_retriever_cache()

