"""
LLM Factory - Base Module
Defines the base interface for all LLM clients.
"""

import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, AsyncIterator, Any
from dataclasses import dataclass, field
from enum import Enum


def run_sync(coro):
    """
    Run a coroutine from synchronous code.

    If the caller already has a running event loop, as in FastAPI or uvicorn,
    execute the coroutine in a separate thread and event loop to avoid a
    ``This event loop is already running`` error.
    """
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    except RuntimeError:
        return asyncio.run(coro)


class MessageRole(Enum):
    """Message-role enumeration."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """LLM message."""
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        """Convert the message to a dictionary."""
        return {"role": self.role, "content": self.content}


@dataclass
class Usage:
    """Token-usage statistics."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other):
        """Support aggregation."""
        return Usage(
            prompt_tokens=self.prompt_tokens + other.prompt_tokens,
            completion_tokens=self.completion_tokens + other.completion_tokens,
            total_tokens=self.total_tokens + other.total_tokens
        )


@dataclass
class LLMResponse:
    """LLM response."""
    content: str
    model: str
    usage: Optional[Usage] = None
    raw_response: Optional[Any] = None
    finish_reason: Optional[str] = None

    def __str__(self) -> str:
        return f"LLMResponse(model={self.model}, content={self.content[:100]}...)"


class BaseLLMClient(ABC):
    """
    Base interface for all LLM clients.

    Subclasses must implement:
    - ``acomplete``: asynchronous completion
    - ``complete``: synchronous completion
    - ``provider_name``: provider name
    """

    def __init__(self,
                 api_key: str,
                 base_url: Optional[str] = None,
                 model: Optional[str] = None,
                 **kwargs):
        """
        Initialize an LLM client.

        Args:
            api_key: API key.
            base_url: API base URL.
            model: Model name.
            **kwargs: Additional parameters.
        """
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.kwargs = kwargs

    @staticmethod
    def _run_sync(coro):
        """
        Run a coroutine from synchronous code.

        If an event loop is already running, as in FastAPI or uvicorn, execute
        the coroutine in a separate thread and loop to avoid a nested-loop
        error.
        """
        try:
            asyncio.get_running_loop()
            # The event loop is running; use a new thread.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        except RuntimeError:
            # No event loop is running; execute directly.
            return asyncio.run(coro)

    @abstractmethod
    async def acomplete(self,
                        messages: List[Message],
                        temperature: float = 0.7,
                        max_tokens: int = 2000,
                        **kwargs) -> LLMResponse:
        """
        Perform one asynchronous completion.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature from 0 to 1; lower is more deterministic.
            max_tokens: Maximum number of generated tokens.
            **kwargs: Additional parameters.

        Returns:
            LLM response.
        """
        pass

    @abstractmethod
    def complete(self,
                 messages: List[Message],
                 temperature: float = 0.7,
                 max_tokens: int = 2000,
                 **kwargs) -> LLMResponse:
        """
        Perform one synchronous completion.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature.
            max_tokens: Maximum number of generated tokens.
            **kwargs: Additional parameters.

        Returns:
            LLM response.
        """
        pass

    async def astream(self,
                      messages: List[Message],
                      temperature: float = 0.7,
                      max_tokens: int = 2000,
                      **kwargs) -> AsyncIterator[str]:
        """
        Stream output asynchronously when supported.

        Args:
            messages: Messages to send.
            temperature: Sampling temperature.
            max_tokens: Maximum number of generated tokens.
            **kwargs: Additional parameters.

        Yields:
            Text chunks from the stream.
        """
        raise NotImplementedError("Streaming not implemented for this client")

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the provider name."""
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model})"
