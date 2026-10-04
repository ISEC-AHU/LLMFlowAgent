"""
LLM Factory Package
Unified LLM client factory with support for multiple providers.
"""

from .base import BaseLLMClient, Message, LLMResponse, Usage, MessageRole
from .factory import LLMFactory
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient

__all__ = [
    'BaseLLMClient',
    'Message',
    'LLMResponse',
    'Usage',
    'MessageRole',
    'LLMFactory',
    'OpenAIClient',
    'AnthropicClient',
]

# Version information.
__version__ = '1.0.0'
