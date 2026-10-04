"""
LLM Factory - Factory Module
Unified LLM client factory supporting multiple providers.
"""

import os
import re
from typing import Dict, List, Optional, Any
import yaml
from pathlib import Path

from .base import BaseLLMClient, Message, LLMResponse
from .openai_client import OpenAIClient
from .anthropic_client import AnthropicClient


class LLMFactory:
    """
    Factory that manages all LLM clients through one interface.

    Supported providers:
    - openai: OpenAI GPT models
    - azure: Azure OpenAI
    - anthropic: Anthropic Claude models
    - gemini: Google Gemini models
    - qwen: Alibaba Qwen (OpenAI-compatible)
    - zhipu: Zhipu AI (OpenAI-compatible)
    - moonshot: Moonshot AI (OpenAI-compatible)
    - deepseek: DeepSeek (OpenAI-compatible)
    - baichuan: Baichuan AI (OpenAI-compatible)
    - minimax: MiniMax (OpenAI-compatible)

    Examples:
        >>> # Option 1: load from a configuration file.
        >>> LLMFactory.load_config("config/llm_providers.yaml")
        >>> client = LLMFactory.get_client("openai", model="gpt-4")
        >>> response = await client.acomplete(messages)
        >>>
        >>> # Option 2: pass parameters directly.
        >>> client = LLMFactory.get_client(
        ...     "openai",
        ...     api_key="sk-...",
        ...     model="gpt-4"
        ... )
        >>>
        >>> # Option 3: process requests in batches.
        >>> responses = await LLMFactory.batch_complete([
        ...     {"messages": messages1},
        ...     {"messages": messages2}
        ... ], provider="openai")
    """

    _clients: Dict[str, BaseLLMClient] = {}
    _config: Optional[Dict] = None
    _config_path: Optional[str] = None
    _backend_dir = Path(__file__).resolve().parents[2]
    _default_config_path = _backend_dir / "config" / "llm_providers.yaml"

    @classmethod
    def ensure_config_loaded(cls):
        if cls._config is None:
            cls.load_config(str(cls._default_config_path))

    @classmethod
    def get_config(cls) -> Dict:
        cls.ensure_config_loaded()
        return cls._config or {}

    @classmethod
    def get_provider_config(cls, provider: str) -> Dict:
        config = cls.get_config()
        return config.get("providers", {}).get(provider, {})

    @classmethod
    def get_role_config(cls, role: str, fallback: str = "workflow_generation") -> Dict[str, str]:
        config = cls.get_config()
        role_aliases = {
            "evaluation": "evaluation_rubric",
            "rubric_evaluation": "evaluation_rubric",
            "regeneration": "workflow_regeneration",
        }
        role = role_aliases.get(role, role)
        roles = config.get("roles", {})
        defaults = config.get("defaults", {})
        role_config = roles.get(role) or defaults.get(role) or roles.get(fallback) or {}
        if not isinstance(role_config, dict):
            role_config = {"provider": role_config}

        provider = role_config.get("provider", "openai")
        model = role_config.get("model") or cls.get_default_model(provider)
        result = {"provider": provider}
        if model:
            result["model"] = model
        return result

    @classmethod
    def get_role_client(cls, role: str, **kwargs) -> BaseLLMClient:
        role_config = cls.get_role_config(role)
        return cls.get_client(**role_config, **kwargs)

    @classmethod
    def get_langchain_chat_model(cls, role: str = "workflow_generation", **kwargs):
        from langchain_openai import ChatOpenAI

        role_config = cls.get_role_config(role)
        provider = role_config["provider"]
        provider_config = cls.get_provider_config(provider)
        model = role_config.get("model") or provider_config.get("default_model")
        options = provider_config.get("options", {})
        return ChatOpenAI(
            model=model,
            openai_api_key=provider_config.get("api_key"),
            base_url=provider_config.get("base_url"),
            temperature=kwargs.pop("temperature", 0),
            streaming=kwargs.pop("streaming", False),
            request_timeout=kwargs.pop("timeout", options.get("timeout")),
            max_retries=kwargs.pop("max_retries", options.get("max_retries", 3)),
            **kwargs,
        )

    @classmethod
    def get_dashscope_api_key(cls) -> str:
        qwen_config = cls.get_provider_config("qwen")
        api_key = qwen_config.get("api_key")
        if api_key:
            return api_key
        embedding_config = cls.get_role_config("embedding")
        return cls.get_provider_config(embedding_config.get("provider", "qwen")).get("api_key", "")

    @classmethod
    def get_embedding_model(cls) -> str:
        config = cls.get_role_config("embedding")
        return config.get("model", "text-embedding-v2")

    @classmethod
    def get_rerank_model(cls) -> str:
        config = cls.get_role_config("rerank")
        return config.get("model", "qwen3-rerank")

    @classmethod
    def load_config(cls, config_path: str = "config/llm_providers.yaml"):
        """
        Load a configuration file.

        Args:
            config_path: Relative or absolute configuration-file path.
        """
        # Pattern for environment-variable substitution.
        env_var_pattern = r'\$\{([^}:]+)(?::([^}]*))?\}'

        # Custom constructor for ${VAR} syntax.
        def parse_env_vars(value):
            """Resolve ${VAR_NAME} or ${VAR_NAME:default}."""
            if isinstance(value, str):
                matches = re.findall(env_var_pattern, value)
                for var_name, default in matches:
                    env_value = os.environ.get(var_name, default)
                    value = value.replace(f'${{{var_name}:{default}}}', env_value)
                    value = value.replace(f'${{{var_name}}}', env_value)
            return value

        # Parse the configuration file.
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Substitute environment variables.
            for match in re.finditer(env_var_pattern, content):
                var_name, default = match.groups()
                env_value = os.environ.get(var_name, default if default else '')
                content = content.replace(match.group(0), env_value)

        # Load the processed YAML.
        import io
        cls._config = yaml.safe_load(io.StringIO(content))

        cls._config_path = str(Path(config_path).resolve())

    @classmethod
    def get_client(cls,
                   provider: str,
                   model: Optional[str] = None,
                   **kwargs) -> BaseLLMClient:
        """
        Return an LLM client instance.

        Args:
            provider: Provider name such as openai, anthropic, qwen, or zhipu.
            model: Optional model name; defaults to the configured model.
            **kwargs: Additional parameters that override configuration values.

        Returns:
            Configured LLM client instance.

        Raises:
            ValueError: If the provider is unknown or configuration is unavailable.

        Example:
            >>> client = LLMFactory.get_client("openai", model="gpt-4")
            >>> response = await client.acomplete(messages)
        """
        # Load the default configuration when none has been loaded.
        if cls._config is None:
            default_config = cls._default_config_path
            if default_config.exists():
                cls.load_config(str(default_config))
            else:
                # Without a configuration file, require an api_key.
                if 'api_key' not in kwargs:
                    raise ValueError(
                        f"Config file not found and api_key not provided for {provider}. "
                        f"Either load config with LLMFactory.load_config() or provide api_key."
                    )
                cls._config = {'providers': {}}

        if provider not in cls._config.get('providers', {}):
            # Allow direct creation for providers absent from the configuration.
            if 'api_key' in kwargs:
                provider_config = {}
            else:
                raise ValueError(
                    f"Unknown provider: {provider}. "
                    f"Available providers: {list(cls._config.get('providers', {}).keys())}"
                )
        else:
            provider_config = cls._config['providers'][provider]

        # Explicit arguments take precedence over file configuration.
        api_key = kwargs.pop('api_key', provider_config.get('api_key'))
        if not api_key:
            raise ValueError(f"api_key not provided for {provider}")

        base_url = kwargs.pop('base_url', provider_config.get('base_url'))
        model_name = model or kwargs.pop('model', provider_config.get('default_model'))

        # Reuse cached clients for identical provider and model settings.
        cache_key = f"{provider}_{model_name}"
        if cache_key not in cls._clients:
            # Create the client for the selected provider.
            if provider in ['openai', 'azure', 'qwen', 'gemini','zhipu', 'moonshot',
                           'deepseek', 'baichuan', 'minimax']:
                # These providers expose OpenAI-compatible interfaces.
                cls._clients[cache_key] = OpenAIClient(
                    api_key=api_key,
                    base_url=base_url,
                    model=model_name,
                    **{**provider_config.get('options', {}), **kwargs}
                )
            elif provider == 'anthropic':
                cls._clients[cache_key] = AnthropicClient(
                    api_key=api_key,
                    model=model_name,
                    **{**provider_config.get('options', {}), **kwargs}
                )
            else:
                # Treat custom providers as OpenAI-compatible interfaces.
                cls._clients[cache_key] = OpenAIClient(
                    api_key=api_key,
                    base_url=base_url or provider_config.get('base_url'),
                    model=model_name,
                    **{**provider_config.get('options', {}), **kwargs}
                )

        return cls._clients[cache_key]

    @classmethod
    def get_default_model(cls, provider: str) -> Optional[str]:
        """Return a provider's default model."""
        if cls._config is None:
            return None
        return cls._config.get('providers', {}).get(provider, {}).get('default_model')

    @classmethod
    def get_rubric_generator_config(cls, stage: str = 'universal') -> Dict[str, str]:
        """
        Return rubric-generator configuration.

        Args:
            stage: Generation stage:
                - ``universal``: universal-rubric generation
                - ``draft``: draft-rubric generation
                - ``refinement``: rubric refinement

        Returns:
            Dict: {"provider": str, "model": str}

        Example:
            >>> config = LLMFactory.get_rubric_generator_config('universal')
            >>> client = LLMFactory.get_client(**config)
        """
        if cls._config is None:
            default_config = cls._default_config_path
            if default_config.exists():
                cls.load_config(str(default_config))
            else:
                # Default configuration.
                return {"provider": "openai", "model": "gpt-4"}

        defaults = cls._config.get('defaults', {})
        stage_aliases = {
            "evaluation": "evaluation_rubric",
            "rubric_evaluation": "evaluation_rubric",
            "regeneration": "workflow_regeneration",
        }
        stage = stage_aliases.get(stage, stage)
        stage_config = defaults.get(f'{stage}_rubric', {})
        if not stage_config:
            stage_config = defaults.get(stage, {})
        if not stage_config:
            stage_config = cls._config.get("roles", {}).get(stage, {})

        if isinstance(stage_config, dict):
            return {
                "provider": stage_config.get('provider', 'openai'),
                "model": stage_config.get('model', 'gpt-4')
            }
        else:
            # Support the legacy format containing only a provider name.
            return {
                "provider": stage_config if isinstance(stage_config, str) else 'openai',
                "model": cls.get_default_model(stage_config if isinstance(stage_config, str) else 'openai')
            }

    @classmethod
    def get_simulation_configs(cls) -> List[Dict[str, str]]:
        """
        Return the LLM configurations used for simulation.

        Returns:
            List[Dict]: [{"provider": str, "model": str}, ...]

        Example:
            >>> configs = LLMFactory.get_simulation_configs()
            >>> for config in configs:
            ...     client = LLMFactory.get_client(**config)
            ...     # Run the simulation.
        """
        # backend/config/llm_providers.yaml
        if cls._config is None:
            default_config = cls._default_config_path
            if default_config.exists():
                cls.load_config(str(default_config))
            else:
                # Default configuration.
                return [{"provider": "openai", "model": "gpt-4"}]

        defaults = cls._config.get('defaults', {})
        simulation_config = defaults.get('simulation', [])

        # Normalize configuration entries.
        result = []
        for item in simulation_config:
            if isinstance(item, dict):
                result.append({
                    "provider": item.get('provider', 'openai'),
                    "model": item.get('model', 'gpt-4')
                })
            elif isinstance(item, str):
                result.append({
                    "provider": item,
                    "model": cls.get_default_model(item)
                })

        return result

    @classmethod
    def get_rubric_client(cls, stage: str = 'refinement'):
        """
        Return a configured rubric-generation client.

        Args:
            stage: Generation stage (``universal``, ``draft``, or ``refinement``).

        Returns:
            Configured client instance.

        Example:
            >>> client = LLMFactory.get_rubric_client('universal')
            >>> response = await client.acomplete(messages)
        """
        config = cls.get_rubric_generator_config(stage)
        return cls.get_client(**config)
