"""
Rubric-related constants and utilities.
"""

from typing import Any, Dict, List, Optional


UNIVERSAL_RUBRICS = [
    {
        "theme": "Structural Integrity & Logical Flow",
        "tips": [
            "Verify that the graph contains zero circular dependencies (cycles) between tasks.",
            "Ensure that \"Prerequisite\" tasks (e.g., URL Extraction) are completed before \"Dependent\" tasks (e.g., Video Processing) begin.",
            "Check that the final node in the DAG produces the specific output modality requested by the user (e.g., if the user wants a video, the terminal node must be a video-generating tool).",
            "Confirm that every node in the graph has a clear path to the final output, avoiding \"dead-end\" processing steps.",
        ],
        "weight": 1.0,
        "description": "This dimension ensures the task plan is a valid Directed Acyclic Graph (DAG) and that the sequence of operations follows a rational, executable order. Without logical correctness, the pipeline will fail to execute or produce nonsensical results.",
    },
    {
        "theme": "Functional Requirement Coverage",
        "tips": [
            "Map every input provided by the user (Video, Audio, Text, etc.) to at least one starting node in the DAG.",
            "Cross-reference the user's requested transformations (e.g., \"change speed\" and \"add sentiment analysis\") against the tool list to ensure no requested action is skipped.",
            "Ensure that all constraints mentioned in the prompt (e.g., \"synchronize audio\") are represented by a specific tool node.",
            "Verify that the output of the DAG satisfies the user's \"Definition of Done\" (e.g., a translated, speed-adjusted video).",
        ],
        "weight": 1.0,
        "description": "This assesses whether the plan actually addresses every part of the user's prompt. In complex multimedia tasks (avg. complexity ~10.6), it is easy to overlook a specific transformation or analysis step.",
    },
    {
        "theme": "Modality & Type Consistency",
        "tips": [
            "Check that the output modality of a parent node matches the required input modality of its child node (e.g., Video-to-Audio must feed into a tool that accepts Audio).",
            "Identify missing \"Bridge\" tools, such as ensuring a Video-to-Text tool is used before attempting Text Sentiment Analysis on a video file.",
            "Verify that multi-input tools (like Video Synchronization) receive all required modalities simultaneously from their respective parent nodes.",
            "Ensure that URL inputs are passed through a URL Extractor/Downloader before being treated as raw media files.",
        ],
        "weight": 1.0,
        "description": "Multimedia processing involves 5 input and 6 output types. This dimension checks if the \"pipes\" between tools are compatible, preventing runtime errors caused by passing the wrong data type.",
    },
    {
        "theme": "Resource & Path Optimization",
        "tips": [
            "Identify and remove redundant nodes (e.g., calling Video-to-Audio twice for the same file instead of branching the output of one node).",
            "Check for \"Parallelization Potential\"—independent tasks (like Image-to-Text and Audio-to-Text) should be structured as parallel branches rather than a forced serial sequence.",
            "Evaluate if the plan uses the minimum number of steps required to reach the goal without sacrificing quality.",
            "Ensure that heavy processing (like Video-to-Video) isn't performed if a lighter tool (like Image-to-Video) could achieve the same result based on the inputs.",
        ],
        "weight": 1.0,
        "description": "Efficiency matters in multimedia processing due to high computational costs. This dimension evaluates if the DAG achieves the goal using the most direct and least redundant path.",
    },
    {
        "theme": "Semantic Tool Alignment",
        "tips": [
            "Verify that the tool selected is the most specific one available (e.g., using \"Voice Changer\" for audio modification rather than a generic audio editor).",
            "Check if the tool's intended use case matches the data (e.g., don't use \"Text Sentiment Analysis\" if the user specifically asked for \"URL Extraction\").",
            "Ensure that tools with similar names are not confused (e.g., distinguishing between Image-to-Video and Video-to-Image).",
        ],
        "weight": 1.0,
        "description": "With 40 different tools, choosing the *right* tool for the specific context is vital. This dimension assesses if the selected tool's function matches the semantic intent of the user's request.",
    },
    {
        "theme": "Operational Robustness",
        "tips": [
            "Check for \"Synchronization Points\"—if a video and audio are processed separately, ensure there is a \"Video Synchronization\" or \"Merging\" node before the final output.",
            "Evaluate the handling of multi-modal outputs; if a tool produces both audio and text outputs, ensure both data types are properly consumed or stored.",
            "Inspect fallback and error-handling logic, such as allowing a Text-to-Speech node to still run if the input text is empty.",
            "Ensure that tools with side effects (e.g., deleting temporary files) don't interfere with later nodes.",
        ],
        "weight": 1.0,
        "description": "Multimedia tasks often involve unpredictable data. This dimension evaluates how well the plan handles complex scenarios and ensures the output is stable and synchronized.",
    },
]


def merge_rubrics(
    universal_rubric: Optional[List[dict]],
    final_rubric: Optional[List[dict]],
) -> List[dict]:
    """Merge universal and final task-specific rubrics, deduplicating by theme."""
    merged = []
    seen = set()

    for rubric_list in [universal_rubric or [], final_rubric or []]:
        for item in rubric_list:
            theme = item.get("theme")
            if not theme:
                continue
            if theme not in seen:
                merged.append(item)
                seen.add(theme)

    return merged


def normalize_simulation_report(report_obj: Any) -> dict:
    """Normalize a simulation report object to a consistent dictionary format."""
    from .serializers import to_serializable

    report_dict = to_serializable(report_obj)

    return {
        "task_id": report_dict.get("task_id"),
        "step_scores": report_dict.get("step_scores", {}),
        "discriminatory_power": report_dict.get("discriminatory_power", {}),
        "high_discrimination_steps": report_dict.get("high_discrimination_steps", []),
        "low_discrimination_steps": report_dict.get("low_discrimination_steps", []),
        "model_rankings": report_dict.get("model_rankings", {}),
        "summary": report_dict.get("summary", {}),
    }
