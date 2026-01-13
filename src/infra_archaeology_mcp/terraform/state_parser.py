"""Terraform state file parser"""

import json
from pathlib import Path
from typing import Optional, Dict, List, Any


class TerraformStateParser:
    """Parse Terraform state files (v4 format)"""

    def __init__(self):
        self._state: Optional[Dict] = None
        self._resources: List[Dict] = []

    @property
    def resources(self) -> List[Dict]:
        """Parsed resources list"""
        return self._resources

    def load_from_file(self, path: str) -> None:
        """Load state from file path"""
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"State file not found: {path}")

        with open(file_path, 'r') as f:
            self.load_from_json(f.read())

    def load_from_json(self, json_str: str) -> None:
        """Load state from JSON string"""
        try:
            self._state = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}")

        self._parse_resources()

    def _parse_resources(self) -> None:
        """Extract resources from state"""
        self._resources = []

        if not self._state:
            return

        for resource in self._state.get("resources", []):
            if resource.get("mode") != "managed":
                continue

            resource_type = resource.get("type", "")
            resource_name = resource.get("name", "")
            module = resource.get("module")

            for instance in resource.get("instances", []):
                attrs = instance.get("attributes", {})
                aws_id = attrs.get("id")
                index = instance.get("index_key")

                address = self._build_address(module, resource_type, resource_name, index)

                self._resources.append({
                    "address": address,
                    "type": resource_type,
                    "name": resource_name,
                    "module": module,
                    "aws_id": aws_id,
                    "attributes": attrs
                })

    def _build_address(
        self,
        module: Optional[str],
        resource_type: str,
        name: str,
        index: Optional[Any]
    ) -> str:
        """Build Terraform resource address"""
        address = f"{resource_type}.{name}"

        if index is not None:
            if isinstance(index, int):
                address = f"{address}[{index}]"
            else:
                address = f"{address}[\"{index}\"]"

        if module:
            address = f"{module}.{address}"

        return address

    def find_by_id(self, aws_id: str) -> Optional[Dict]:
        """Find resource by AWS resource ID"""
        for resource in self._resources:
            if resource.get("aws_id") == aws_id:
                return resource
        return None

    def build_id_map(self) -> Dict[str, Dict]:
        """Build AWS ID -> Terraform metadata map"""
        return {
            r["aws_id"]: {
                "address": r["address"],
                "type": r["type"],
                "module": r["module"],
                "attributes": r["attributes"]
            }
            for r in self._resources
            if r.get("aws_id")
        }
