import json
import re
import asyncio
import logging
from typing import List, Dict, Any
import inspect

from llm_factory.base import Message


class DAGGenerator:
    """
    DAG dependency generator.

    Given a task description and API candidate pool, asks the LLM to output
    only execution dependencies between APIs (``task_links``). ``task_nodes``
    are no longer generated because the candidate pool supplies node data.
    """

    def __init__(self, llm_client, tool_spi_path: str):
        self.client = llm_client
        self.tool_metadata = self._load_metadata(tool_spi_path)
        self.logger = logging.getLogger("DAGGenerator")

    def _extract_response_text(self, response) -> str:
        """Normalize response formats from different LLM clients."""
        if isinstance(response, str):
            return response.strip()

        if hasattr(response, "content"):
            return response.content.strip()

        if isinstance(response, dict):
            if "content" in response:
                return response["content"].strip()

            if "choices" in response:
                return response["choices"][0]["message"]["content"].strip()

        raise TypeError(f"Unsupported LLM response type: {type(response)}")

    async def _acall_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
        **kwargs,
    ) -> str:
        """Provide a unified asynchronous LLM invocation entry point."""
        messages = [
            Message("system", system_prompt),
            Message("user", user_prompt),
        ]

        # Prefer the asynchronous interface.
        if hasattr(self.client, "acomplete") and callable(self.client.acomplete):
            response = await self.client.acomplete(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return self._extract_response_text(response)

        # Support the legacy ModelClient.call() interface.
        if hasattr(self.client, "call") and callable(self.client.call):
            sig = inspect.signature(self.client.call)

            if "override_params" in sig.parameters:
                response = self.client.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    override_params={
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                        **kwargs,
                    },
                )
            else:
                response = self.client.call(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                )

            return self._extract_response_text(response)

        # Fall back to complete() only as a last resort.
        if hasattr(self.client, "complete") and callable(self.client.complete):
            response = self.client.complete(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            return self._extract_response_text(response)

        raise TypeError(
            f"Unsupported llm_client: {type(self.client).__name__}. "
            f"It must provide acomplete(), call(), or complete()."
        )

    def _load_metadata(self, path: str) -> Dict[str, Dict]:
        with open(path, "r", encoding="utf-8") as f:
            tools = json.load(f)
            return {t["id"]: t for t in tools}

    def validate_and_fix(self, dag: Dict, pool: List[str]) -> Dict:
        """
        Validate ``task_links`` by removing edges whose source or target is
        absent from the candidate pool.
        """
        pool_set = set(pool)
        raw_task_links = dag.get("task_links", [])

        valid_task_links = []
        for link in raw_task_links:
            if not isinstance(link, dict):
                continue

            source = link.get("source")
            target = link.get("target")

            if source in pool_set and target in pool_set:
                valid_task_links.append({"source": source, "target": target})

        return {"task_links": valid_task_links}

    def compose_prompt(self, item: Dict[str, Any]) -> str:
        """Build the dependency-generation prompt."""
        pool_ids = item.get("candidate_pool", [])

        candidates_info = []
        for tid in pool_ids:
            tool = self.tool_metadata.get(tid)
            if tool:
                in_type = tool.get("input_type", [])
                out_type = tool.get("output_type", [])
                candidates_info.append(
                    f"### [Tool ID]: {tid}\n"
                    f"- Capability: {tool.get('desc', '')}\n"
                    f"- I/O Spec: {in_type} -> {out_type}"
                )

        return f"""You're a scientific workflow expert. Your role involves:

1. Analyzing the following workflow task description and the associated API list. The provided APIs are exactly the APIs required to complete the task, so you do not need to add, remove, or replace any API.

2. Based on the task description, determining the execution dependencies among these APIs. Consider both data dependencies and control-flow dependencies.

Pay special attention to parallel activities and synchronization:
- If multiple APIs are executed in parallel and a subsequent API can start only after all parallel APIs are completed, create a dependency link from each parallel API to that subsequent API.
- Do not omit a dependency merely because no explicit output parameter is passed between the APIs.
- For example, if A and B are performed in parallel, and C starts once both are completed, output both A -> C and B -> C.

You do not need to return the analysis process.

3. Ultimately, presenting only the dependency relationships among the APIs in the following JSON markdown format:
```json
{{
  "task_links": [
    {{
      "source": "source api name",
      "target": "target api name"
    }}
  ]
}}
```

Workflow task description: {item['instruction']}

API list:
{chr(10).join(candidates_info)}

Do not output anything for steps 1 and 2. Return only one JSON markdown block for step 3. Do not output any explanation, note, reasoning process, or extra text.
"""

    async def agenerate(self, item: Dict[str, Any], max_retries=3) -> Dict:
        """Generate API dependencies (``task_links``)."""
        prompt = self.compose_prompt(item)
        pool_ids = item.get("candidate_pool") or []

        for attempt in range(max_retries):
            try:
                response = await self._acall_llm(
                    system_prompt=(
                        "You are a logic engine that determines dependencies between APIs. "
                        "Output only JSON."
                    ),
                    user_prompt=prompt,
                    temperature=0.0,
                    max_tokens=2000,
                )

                match = re.search(r"(\{.*\})", response, re.DOTALL)
                raw_dag = json.loads(match.group(1)) if match else json.loads(response)

                final_dag = self.validate_and_fix(raw_dag, pool_ids)

                if not final_dag["task_links"] and attempt < max_retries - 1:
                    continue

                return final_dag

            except Exception as e:
                wait_time = (attempt + 1) * 2
                self.logger.warning(
                    f"Attempt {attempt + 1} failed for {item['id']}: {e}"
                )
                await asyncio.sleep(wait_time)

        return {"task_links": [], "error": "Max retries exceeded"}
