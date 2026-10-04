import json
import os
import time
import re
from typing import List, Dict, Any
try:
    from src.llm_factory.factory import LLMFactory
    from src.llm_factory.base import Message
except ImportError:
    from llm_factory.factory import LLMFactory
    from llm_factory.base import Message

# This file is four directory levels below the backend directory.
BACKEND_DIR = os.path.abspath(__file__)
for _ in range(4):
    BACKEND_DIR = os.path.dirname(BACKEND_DIR)


# Shared query-rewriting prompt replacing LangChain's rewrite_query.py.
REWRITE_QUERY_PROMPT = (
    "You are an API Search Query Optimizer.\n"
    "Task: Rewrite user workflow steps into technical search queries.\n"
    "### RULES:\n"
    "1. OUTPUT FORMAT: Output EXACTLY one line per step. No explanations, no intro, no bullet points.\n"
    "2. CONTENT: Combine [Original Action] + [Technical Keywords from Knowledge Base].\n"
    "3. CONSISTENCY: If the user provides 3 steps, you MUST output exactly 3 lines.\n"
    "Example:\n"
    "User: 'Make text English'\n"
    "Output: 'Translate text to English, GoogleTranslate API, Language Detection'"
)


class QueryRewriter:
    def __init__(
        self,
        vector_store=None,
        base_cache_dir=os.path.join(BACKEND_DIR, "data", "cache"),
    ):
        self.model_client = LLMFactory.get_role_client("query_rewrite")
        self.vector_store = vector_store

        raw_model_name = self.model_client.model
        safe_model_name = re.sub(r'[\\/:*?"<>|]', "_", raw_model_name)

        self.cache_path = os.path.join(
            base_cache_dir, safe_model_name, "rewrite_cache.json"
        )

        self.cache = self._load_cache()

        self.system_prompt = REWRITE_QUERY_PROMPT

    def _load_cache(self) -> Dict[str, List[str]]:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"⚠️ Load cache failed: {e}")
                return {}
        return {}

    def _save_cache(self):
        # Ensure the model-specific cache directory exists.
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Save cache failed: {e}")

    def rewrite(self, tool_steps: List[str], max_retries: int = 3) -> List[str]:
        cleaned_steps = [s.strip() for s in tool_steps if s.strip()]
        if not cleaned_steps:
            return []

        # Include step content in the cache key to isolate different tasks.
        cache_key = "\n".join(cleaned_steps)
        if cache_key in self.cache:
            return self.cache[cache_key]

        # Retrieve candidate-tool context.
        candidate_context = ""
        if self.vector_store:
            seen_ids = set()
            tool_info = []
            for step in cleaned_steps:
                results = self.vector_store.search(step, k=5)
                for res in results:
                    tid = res.get("id")
                    if tid and tid not in seen_ids:
                        tool_info.append(f"- {tid}: {res.get('desc', '')}")
                        seen_ids.add(tid)
            if tool_info:
                candidate_context = (
                    "\n### Candidate Tools Knowledge Base:\n" + "\n".join(tool_info)
                )

        user_content = (
            f"{candidate_context}\n\nRewrite these user steps into technical search queries:\n"
            + "\n".join([f"- {s}" for s in cleaned_steps])
        )

        for attempt in range(max_retries):
            try:
                response = self.model_client.complete(
                    messages=[
                        Message(role="system", content=self.system_prompt),
                        Message(role="user", content=user_content),
                    ],
                    temperature=0,
                )
                response_content = response.content.strip()

                # Debug the raw LLM response.
                # print(f"🔍 [Rewrite DEBUG] raw response ({len(response_content)} chars):")
                # print(response_content)
                # print(f"🔍 [Rewrite DEBUG] split lines: {len(response_content.split(chr(10)))}")
                # === END DEBUG ===

                rewritten_lines = []
                for line in response_content.split("\n"):
                    line = line.strip()
                    if not line:
                        continue

                    # Apply defensive output cleanup.
                    clean_line = (
                        line.lstrip("- ")
                        .lstrip("123456789. ")
                        .split(":")[-1]
                        .strip()
                        .strip(",")
                        .strip('"')
                    )
                    if clean_line:
                        rewritten_lines.append(clean_line)
                    # Debug each parsed line.
                    # print(f"  line='{line}' -> clean='{clean_line}' (kept={bool(clean_line)})")
                    # === END DEBUG ===

                # Verify that the output preserves the input line count.
                if len(rewritten_lines) == len(cleaned_steps):
                    self.cache[cache_key] = rewritten_lines
                    self._save_cache()
                    return rewritten_lines
                else:
                    print(
                        f"⚠️ Line mismatch [{self.model_client.model}]: {len(rewritten_lines)}/{len(cleaned_steps)}"
                    )
                    print(f"  expected steps: {cleaned_steps}")
                    print(f"  parsed lines:   {rewritten_lines}")

            except Exception as e:
                print(f"⚠️ Rewrite attempt {attempt + 1} failed: {e}")
                time.sleep(2**attempt)

        return cleaned_steps
