import json
from pathlib import Path
from typing import Dict, List, Optional


class ToolDescription:
    def __init__(self, tool_id: str, desc: str, input_types: List[str], output_types: List[str]):
        self.id = tool_id
        self.desc = desc
        self.input_types = input_types
        self.output_types = output_types

    def accepts_input(self, input_type: str) -> bool:
        return input_type in self.input_types

    def produces_output(self, output_type: str) -> bool:
        return output_type in self.output_types

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "desc": self.desc,
            "input_types": self.input_types,
            "output_types": self.output_types,
        }


class ToolDescriptionLoader:
    def __init__(self, tool_desc_path: Optional[str] = None):
        if tool_desc_path is None:
            try:
                from knowledge_service import get_selected_tool_spi_path

                tool_desc_path = get_selected_tool_spi_path()
            except Exception:
                backend_dir = Path(__file__).resolve().parents[2]
                tool_desc_path = backend_dir / "knowledge_bases" / "multimedia-tools" / "tools_spi.json"

        self.tool_desc_path = Path(tool_desc_path)
        self._tools: Optional[Dict[str, ToolDescription]] = None

    def load(self) -> Dict[str, ToolDescription]:
        if self._tools is not None:
            return self._tools

        print(f"[load] Loading tool descriptions from {self.tool_desc_path}...")

        with open(self.tool_desc_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, list):
            tool_items = data
        elif isinstance(data, dict):
            tool_items = data.get("nodes") or data.get("tools") or []
        else:
            tool_items = []

        self._tools = {}
        for tool_data in tool_items:
            input_types = tool_data.get("input-type") or tool_data.get("input_type") or []
            output_types = tool_data.get("output-type") or tool_data.get("output_type") or []
            if isinstance(input_types, str):
                input_types = [item.strip() for item in input_types.split(",") if item.strip()]
            if isinstance(output_types, str):
                output_types = [item.strip() for item in output_types.split(",") if item.strip()]

            tool = ToolDescription(
                tool_id=tool_data.get("id") or tool_data.get("name") or tool_data.get("tool_id"),
                desc=tool_data.get("desc") or tool_data.get("description") or "",
                input_types=input_types,
                output_types=output_types,
            )
            if tool.id:
                self._tools[tool.id] = tool

        print(f"[done] Loaded {len(self._tools)} tool descriptions")
        return self._tools

    def get_tool(self, tool_id: str) -> Optional[ToolDescription]:
        if self._tools is None:
            self.load()
        return self._tools.get(tool_id)

    def get_all_tools(self) -> Dict[str, ToolDescription]:
        if self._tools is None:
            self.load()
        return self._tools

    def get_tool_summary(self) -> Dict:
        tools = self.get_all_tools()
        input_types = set()
        output_types = set()

        for tool in tools.values():
            input_types.update(tool.input_types)
            output_types.update(tool.output_types)

        return {
            "total_tools": len(tools),
            "input_modalities": sorted(list(input_types)),
            "output_modalities": sorted(list(output_types)),
            "modality_count": {
                "input": len(input_types),
                "output": len(output_types),
            },
        }
