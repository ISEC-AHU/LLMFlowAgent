"""
General serialization utilities.
Convert Python objects, including Pydantic models, dataclasses, and nested structures, into JSON-serializable values.
"""

from typing import Any


def to_serializable(obj: Any) -> Any:
    # Primitive values
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj

    # list / tuple / set
    if isinstance(obj, (list, tuple, set)):
        return [to_serializable(item) for item in obj]

    # dict
    if isinstance(obj, dict):
        return {key: to_serializable(value) for key, value in obj.items()}

    # Pydantic v2
    if hasattr(obj, "model_dump"):
        return to_serializable(obj.model_dump())

    # Pydantic v1
    if hasattr(obj, "dict"):
        return to_serializable(obj.dict())

    # Regular Python objects
    if hasattr(obj, "__dict__"):
        return {
            key: to_serializable(value)
            for key, value in obj.__dict__.items()
            if not key.startswith("_")
        }

    # Final fallback
    return str(obj)
