"""
Prompt manager for loading templates from the prompts directory.
"""

from pathlib import Path
from typing import Dict, Optional
import string


class PromptManager:
    """Prompt-template manager."""

    def __init__(self, prompts_dir: str = "prompts"):
        """
        Initialize the prompt manager.

        Args:
            prompts_dir: Prompt directory. Relative paths resolve from backend.
        """
        self._cache: Dict[str, str] = {}
        prompts_path = Path(prompts_dir)
        if not prompts_path.is_absolute():
            # Resolve from backend so paths remain valid after relocation.
            backend_dir = Path(__file__).resolve().parents[2]
            prompts_path = backend_dir / prompts_path
        self.prompts_dir = prompts_path

    def load_prompt(self, prompt_path: str, use_cache: bool = True) -> str:
        """
        Load a prompt template.

        Args:
            prompt_path: Path relative to the prompts directory.
            use_cache: Whether to use the cache.

        Returns:
            Prompt text.
        """
        # Check the cache.
        if use_cache and prompt_path in self._cache:
            return self._cache[prompt_path]

        # Load the file.
        full_path = self.prompts_dir / prompt_path
        if not full_path.exists():
            raise FileNotFoundError(f"Prompt file not found: {full_path}")

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Cache the template.
        if use_cache:
            self._cache[prompt_path] = content

        return content

    def format_prompt(self, prompt_path: str, **kwargs) -> str:
        """
        Load and format a prompt template.

        Args:
            prompt_path: Prompt file path.
            **kwargs: Formatting arguments.

        Returns:
            Formatted prompt text.
        """
        template = self.load_prompt(prompt_path)
        return template.format(**kwargs)

    # ==================== Rubric Generator Prompts ====================
    def get_system_prompt(self) -> str:
        """Return the rubric generator's system prompt."""
        return self.load_prompt("rubric_generator/system.txt")

    def get_universal_prompt(self, **kwargs) -> str:
        """
        Return the universal-rubric generation prompt.

        Args:
            **kwargs: Formatting values including domain, task counts and
                types, common tools, complexity, tool diversity, modalities,
                and requested dimension count.

        Returns:
            Formatted prompt text.
        """
        return self.format_prompt("rubric_generator/universal.txt", **kwargs)

    def get_task_prompt(self, **kwargs) -> str:
        """
        Return the task-specific rubric generation prompt.

        Args:
            **kwargs: Formatting values for the request, steps, tools, DAG
                nodes, and links.

        Returns:
            Formatted prompt text.
        """
        return self.format_prompt("rubric_generator/task_specific.txt", **kwargs)

    # ==================== Evaluation Prompts ====================
    def get_evaluation_prompt(self, **kwargs) -> str:
        """
        Return the task-specific DAG evaluation prompt.

        Args:
            **kwargs: Formatting values for the rubric and DAG descriptions,
                tool validation, conformance analysis, dimension names, and
                dimension count.

        Returns:
            Formatted prompt text.
        """
        return self.format_prompt("evaluation/dag_evaluation.txt", **kwargs)

    def get_generic_evaluation_prompt(self, **kwargs) -> str:
        """
        Return the generic rubric evaluation prompt based on workflow and API evidence.

        Args:
            **kwargs: Formatting values for the rubric and DAG descriptions,
                selected API metadata, and dimension count.

        Returns:
            Formatted prompt text.
        """
        return self.format_prompt("evaluation/generic_rubric_evaluation.txt", **kwargs)


# Global singleton.
_global_prompt_manager: Optional[PromptManager] = None


def get_prompt_manager(prompts_dir: str = "prompts") -> PromptManager:
    """
    Return the global prompt manager.

    Args:
        prompts_dir: Prompt directory path.

    Returns:
        Prompt manager instance.
    """
    global _global_prompt_manager

    if _global_prompt_manager is None:
        _global_prompt_manager = PromptManager(prompts_dir)

    return _global_prompt_manager
