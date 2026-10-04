"""
Shared utilities for LangServe chains.
"""

from pydantic import BaseModel, Field

from src.llm_factory.factory import LLMFactory

# LangChain chat model shared by all chains.
MODEL = LLMFactory.get_langchain_chat_model("workflow_generation")


class InputChat(BaseModel):
    """Input for the chat endpoint."""

    input: str = Field(
        ...,
        description="The human input to the chat system.",
        extra={"widget": {"type": "chat", "input": "input"}},
    )


def escape_braces(prompt: str) -> str:
    """Format the prompt to be compatible with the LLM."""
    return prompt.replace("{", "{{").replace("}", "}}")


def get_json_data(file_path):
    import json

    with open(file_path, "r") as file:
        data = json.load(file)
    return data
