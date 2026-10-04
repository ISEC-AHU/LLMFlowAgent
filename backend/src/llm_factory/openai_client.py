"""
LLM Factory - OpenAI Compatible Client
Supports the OpenAI API and compatible providers such as Azure, Qwen, and Zhipu.
"""

import aiohttp
import asyncio
from typing import List, Optional, Dict, Any
import json

from .base import BaseLLMClient, Message, LLMResponse, Usage


class OpenAIClient(BaseLLMClient):
    """
    Client for OpenAI and compatible APIs.

    Supported providers:
    - OpenAI (https://api.openai.com/v1)
    - Azure OpenAI
    - Alibaba Qwen (https://dashscope.aliyuncs.com/compatible-mode/v1)
    - Zhipu AI (https://open.bigmodel.cn/api/paas/v4)
    - DeepSeek (https://api.deepseek.com)
    - Other OpenAI-compatible APIs
    """

    def __init__(self,
                 api_key: str,
                 base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4",
                 timeout: int = 60,
                 max_retries: int = 3,
                 **kwargs):
        """
        Initialize an OpenAI-compatible client.

        Args:
            api_key: API key.
            base_url: API base URL.
            model: Model name.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry count.
            **kwargs: Additional parameters.
        """
        super().__init__(api_key, base_url, model, **kwargs)
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.max_retries = max_retries
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

    async def acomplete(self,
                        messages: List[Message],
                        temperature: float = 0.7,
                        max_tokens: int = 2000,
                        **kwargs) -> LLMResponse:
        """
        Perform an asynchronous completion.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature.
            max_tokens: Maximum token count.
            **kwargs: Additional parameters merged into the request body.

        Returns:
            LLM response.
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs
        }

        # Add configured options.
        if self.kwargs:
            payload.update(self.kwargs)

        # Retry failed requests.
        for attempt in range(self.max_retries):
            try:
                async with aiohttp.ClientSession(timeout=self.timeout) as session:
                    async with session.post(url, headers=self.headers, json=payload) as resp:
                        if resp.status != 200:
                            error_text = await resp.text()
                            raise Exception(f"API error (status {resp.status}): {error_text}")

                        data = await resp.json()

                        # Parse the response.
                        choice = data["choices"][0]
                        usage = data.get("usage", {})

                        return LLMResponse(
                            content=choice["message"]["content"],
                            model=data.get("model", self.model),
                            usage=Usage(
                                prompt_tokens=usage.get("prompt_tokens", 0),
                                completion_tokens=usage.get("completion_tokens", 0),
                                total_tokens=usage.get("total_tokens", 0)
                            ) if usage else None,
                            raw_response=data,
                            finish_reason=choice.get("finish_reason")
                        )

            except asyncio.TimeoutError:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # Exponential backoff.
                    continue
                raise Exception(f"Request timeout after {self.timeout.total} seconds")
            except Exception as e:
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise e

    def complete(self,
                 messages: List[Message],
                 temperature: float = 0.7,
                 max_tokens: int = 2000,
                 **kwargs) -> LLMResponse:
        """
        Perform a synchronous completion.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature.
            max_tokens: Maximum token count.
            **kwargs: Additional parameters.

        Returns:
            LLM response.
        """
        return self._run_sync(
            self.acomplete(messages, temperature, max_tokens, **kwargs)
        )

    @property
    def provider_name(self) -> str:
        """Return the provider name."""
        return "OpenAI"

    async def astream(self,
                      messages: List[Message],
                      temperature: float = 0.7,
                      max_tokens: int = 2000,
                      **kwargs):
        """
        Stream output asynchronously.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature.
            max_tokens: Maximum token count.
            **kwargs: Additional parameters.

        Yields:
            Text chunks from the stream.
        """
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "messages": [msg.to_dict() for msg in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            **kwargs
        }

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.post(url, headers=self.headers, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    raise Exception(f"API error (status {resp.status}): {error_text}")

                async for line in resp.content:
                    line = line.decode('utf-8').strip()
                    if not line or not line.startswith('data: '):
                        continue

                    data_str = line[6:]  # Remove the ``data: `` prefix.
                    if data_str == '[DONE]':
                        break

                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue
