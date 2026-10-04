




import ast
import json
import re
from typing import Any, Dict, List, Optional


# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
def clean_json_markdown(raw_text: str) -> str:

    if not raw_text:
        return raw_text

    text = raw_text.strip()

    
    if text.startswith("```json"):
        text = text[len("```json"):].strip()

    
    elif text.startswith("```"):
        text = text[len("```"):].strip()

    
    if text.endswith("```"):
        text = text[:-3].strip()

    return text


def clean_markdown_json(raw: Any) -> str:

    if raw is None:
        return ""

    if isinstance(raw, dict):
        return json.dumps(raw, ensure_ascii=False)

    raw = str(raw).strip()

    if raw.startswith("```"):
        raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    return raw.strip()


def parse_dag(raw_dag: Any) -> Dict[str, Any]:

    if isinstance(raw_dag, dict):
        return raw_dag

    cleaned = clean_markdown_json(raw_dag)

    if not cleaned:
        raise ValueError("workflow.dag is empty")

    return json.loads(cleaned)


def parse_any_json(raw: Any):

    if raw is None:
        return None

    if isinstance(raw, (dict, list)):
        return raw

    raw = str(raw).strip()

    if not raw:
        return None

    if raw.startswith("```"):
        raw = re.sub(r"^```json\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"^```\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

    try:
        return json.loads(raw)
    except Exception:
        pass

    try:
        return ast.literal_eval(raw)
    except Exception:
        pass

    return raw


# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
def clean_user_request(text: Optional[str]) -> str:

    if not text:
        return ""

    text = text.strip()

    if text.lower().startswith("workflow:"):
        text = text[len("workflow:"):].strip()

    return text


def parse_task_steps(extracted_task: Optional[str]) -> List[str]:









    if not extracted_task:
        return []

    lines = [line.strip() for line in extracted_task.splitlines() if line.strip()]

    steps = []

    for idx, line in enumerate(lines, start=1):
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        line = re.sub(r"^Step\s*\d+\s*:\s*", "", line, flags=re.IGNORECASE)
        steps.append(f"Step {idx}: {line}")

    return steps


# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
def normalize_io_value(value) -> List[str]:

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, str):
        value = value.strip()
        
        if "," in value:
            return [v.strip() for v in value.split(",") if v.strip()]
        
        return [value] if value else []

    return [str(value)]


def get_first_existing(data: Dict[str, Any], keys: List[str]):
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def extract_api_info_from_doc_item(item: Dict[str, Any]) -> Dict[str, Any]:












    doc = item.get("doc", item)

    if not isinstance(doc, dict):
        return {}

    metadata = doc.get("metadata") or {}
    page_content = doc.get("page_content")

    info = {}

    
    if isinstance(metadata, dict):
        info.update(metadata)

    
    parsed_content = parse_any_json(page_content)

    if isinstance(parsed_content, dict):
        info.update(parsed_content)

    return info


def build_api_io_map_from_api_list(api_list_raw: Any) -> Dict[str, Dict[str, List[str]]]:









    api_list = parse_any_json(api_list_raw)

    if not api_list:
        return {}

    if not isinstance(api_list, list):
        return {}

    api_io_map = {}

    for item in api_list:
        if not isinstance(item, dict):
            continue

        info = extract_api_info_from_doc_item(item)

        if not info:
            continue

        api_name = get_first_existing(
            info,
            [
                "task",
                "api",
                "name",
                "tool_name",
                "tool",
                "task_name",
                "task name",
            ],
        )

        if not api_name:
            continue

        input_type = get_first_existing(
            info,
            [
                "input-type",
                "input_type",
                "inputTypes",
                "input_types",
                "input",
                "inputs",
            ],
        )

        output_type = get_first_existing(
            info,
            [
                "output-type",
                "output_type",
                "outputTypes",
                "output_types",
                "output",
                "outputs",
            ],
        )

        api_io_map[str(api_name)] = {
            "input-type": normalize_io_value(input_type),
            "output-type": normalize_io_value(output_type),
        }

    return api_io_map


# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
def get_api_name_from_task(task: Dict[str, Any]) -> str:
    return (
        task.get("api")
        or task.get("task")
        or task.get("task name")
        or task.get("name")
    )


def infer_arguments(task: Dict[str, Any]) -> List[str]:




    desc = task.get("task description", "") or ""

    arguments = []

    files = re.findall(
        r"[\w\-]+\.(?:mp4|wav|mp3|avi|mov|m4a|flac|png|jpg|jpeg|txt)",
        desc,
        flags=re.IGNORECASE,
    )

    arguments.extend(files)

    quoted_items = re.findall(r"'([^']+)'|\"([^\"]+)\"", desc)

    for q1, q2 in quoted_items:
        value = q1 or q2
        if value and value not in arguments:
            arguments.append(value)

    return arguments


def build_task_links(dag: Dict[str, Any]) -> List[Dict[str, str]]:

    task_list = dag.get("task_list", [])
    task_dependencies = dag.get("task_dependencies", {})

    id_to_api = {}

    for task in task_list:
        task_id = str(task.get("id"))
        api_name = task.get("api") or task.get("task name") or task.get("task")
        id_to_api[task_id] = api_name

    links = []

    for target_id, source_ids in task_dependencies.items():
        target_api = id_to_api.get(str(target_id))

        if not target_api:
            continue

        for source_id in source_ids:
            source_api = id_to_api.get(str(source_id))

            if not source_api:
                continue

            links.append({
                "source": source_api,
                "target": target_api,
            })

    return links


def build_task_nodes(dag: Dict[str, Any]) -> List[Dict[str, Any]]:

    task_list = dag.get("task_list", [])
    task_dependencies = dag.get("task_dependencies", {})

    id_to_node_index = {
        str(task.get("id")): idx
        for idx, task in enumerate(task_list)
    }

    task_nodes = []

    for task in task_list:
        task_id = str(task.get("id"))
        api_name = task.get("api") or task.get("task name") or task.get("task")

        arguments = []

        
        source_ids = task_dependencies.get(task_id, [])

        for source_id in source_ids:
            source_id = str(source_id)

            if source_id in id_to_node_index:
                arguments.append(f"<node-{id_to_node_index[source_id]}>")

        
        for arg in infer_arguments(task):
            if arg not in arguments:
                arguments.append(arg)

        task_nodes.append({
            "task": api_name,
            "arguments": arguments,
        })

    return task_nodes


def build_sampled_nodes(
    dag: Dict[str, Any],
    api_io_map: Dict[str, Dict[str, List[str]]] = None,
) -> List[Dict[str, Any]]:




    api_io_map = api_io_map or {}
    task_list = dag.get("task_list", [])
    sampled_nodes = []

    for task in task_list:
        api_name = get_api_name_from_task(task)

        node = {"task": api_name}

        
        if task.get("input-type") is not None:
            node["input-type"] = normalize_io_value(task.get("input-type"))

        if task.get("output-type") is not None:
            node["output-type"] = normalize_io_value(task.get("output-type"))

        
        if "input-type" not in node and api_name in api_io_map:
            node["input-type"] = api_io_map[api_name].get("input-type", [])

        if "output-type" not in node and api_name in api_io_map:
            node["output-type"] = api_io_map[api_name].get("output-type", [])

        sampled_nodes.append(node)

    return sampled_nodes


def get_workflow_id(req_input, cfg=None):

    if isinstance(cfg, dict):
        metadata = cfg.get("metadata") or {}
        workflow_id = (
            metadata.get("workflow_id")
            or metadata.get("workflowId")
            or metadata.get("id")
        )
        if workflow_id is not None:
            return int(workflow_id)

    if isinstance(req_input, dict):
        workflow_id = (
            req_input.get("workflow_id")
            or req_input.get("workflowId")
            or req_input.get("id")
        )
        if workflow_id is not None:
            return int(workflow_id)

    return None
