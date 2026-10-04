"""
LLM Factory - Anthropic Claude Client
Supports Anthropic Claude models.
"""

from typing import List, Optional
import asyncio

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

from .base import BaseLLMClient, Message, LLMResponse, Usage


class AnthropicClient(BaseLLMClient):
    """
    Anthropic Claude client.

    Supported models:
    - claude-3-5-sonnet-20241022
    - claude-3-5-haiku-20241022
    - claude-3-opus-20240229
    """

    def __init__(self,
                 api_key: str,
                 model: str = "claude-3-5-sonnet-20241022",
                 timeout: int = 60,
                 max_retries: int = 3,
                 **kwargs):
        """
        Initialize an Anthropic client.

        Args:
            api_key: API key.
            model: Model name.
            timeout: Request timeout in seconds.
            max_retries: Maximum retry count.
            **kwargs: Additional parameters.
        """
        if not ANTHROPIC_AVAILABLE:
            raise ImportError(
                "anthropic package is required. "
                "Install it with: pip install anthropic"
            )

        super().__init__(api_key, None, model, **kwargs)
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries
        )
        self.timeout = timeout
        self.max_retries = max_retries

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
            **kwargs: Additional parameters.

        Returns:
            LLM response.
        """
        # Separate system messages from chat messages.
        system_msg = ""
        chat_messages = []

        for msg in messages:
            if msg.role == "system":
                system_msg = msg.content
            else:
                chat_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        try:
            response = await self.client.messages.create(
                model=self.model,
                system=system_msg,
                messages=chat_messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **{**self.kwargs, **kwargs}
            )

            # Parse the response.
            content = response.content[0].text

            return LLMResponse(
                content=content,
                model=response.model,
                usage=Usage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens + response.usage.output_tokens
                ),
                raw_response=response,
                finish_reason=response.stop_reason
            )

        except Exception as e:
            raise Exception(f"Anthropic API error: {str(e)}")

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
        return "Anthropic"

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
        # Separate system messages from chat messages.
        system_msg = ""
        chat_messages = []

        for msg in messages:
            if msg.role == "system":
                system_msg = msg.content
            else:
                chat_messages.append({
                    "role": msg.role,
                    "content": msg.content
                })

        async with self.client.messages.stream(
            model=self.model,
            system=system_msg,
            messages=chat_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            **{**self.kwargs, **kwargs}
        ) as stream:
            async for text in stream.text_stream:
                yield text
