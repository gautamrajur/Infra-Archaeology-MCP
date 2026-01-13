"""Tool: what_terraform_owns_resource"""

import re
import os
import boto3
from pathlib import Path
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from infra_archaeology_mcp.terraform.state_parser import TerraformStateParser


# Extensible service patterns for ARN/ID parsing
# Order matters for bare ID matching: most specific patterns first
SERVICE_PATTERNS = {
    "ec2": {
        "arn_pattern": r"arn:aws:ec2:[^:]*:[^:]*:instance/(i-[a-z0-9]+)",
        "id_pattern": r"^(i-[a-z0-9]+)$",  # i- prefix is unique
        "terraform_types": ["aws_instance"]
    },
    "s3": {
        "arn_pattern": r"arn:aws:s3:::([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])",
        "id_pattern": r"^([a-z0-9][a-z0-9.-]{1,61}[a-z0-9])$",  # lowercase only
        "terraform_types": ["aws_s3_bucket"]
    },
    "rds": {
        "arn_pattern": r"arn:aws:rds:[^:]*:[^:]*:db:([a-zA-Z0-9-]+)",
        "id_pattern": r"^([a-zA-Z][a-zA-Z0-9-]{0,62})$",  # must start with letter, has uppercase
        "terraform_types": ["aws_db_instance"]
    }
}


class UnsupportedResourceError(Exception):
    """Resource type not supported"""
    pass


@dataclass
class ResourceIdentifier:
    """Parsed resource identifier"""
    service: str
    resource_id: str
    terraform_types: list[str]
    original_input: str


def parse_resource_identifier(resource_input: str) -> ResourceIdentifier:
    """Parse ARN or bare ID into service + resource_id"""
    resource_input = resource_input.strip()

    # Try ARN patterns first
    for service, patterns in SERVICE_PATTERNS.items():
        match = re.match(patterns["arn_pattern"], resource_input)
        if match:
            return ResourceIdentifier(
                service=service,
                resource_id=match.group(1),
                terraform_types=patterns["terraform_types"],
                original_input=resource_input
            )

    # Try bare ID patterns
    for service, patterns in SERVICE_PATTERNS.items():
        match = re.match(patterns["id_pattern"], resource_input)
        if match:
            return ResourceIdentifier(
                service=service,
                resource_id=match.group(1),
                terraform_types=patterns["terraform_types"],
                original_input=resource_input
            )

    raise UnsupportedResourceError(f"Cannot parse: {resource_input}")


async def discover_state_files(
    discovery_mode: str = "local",
    state_sources: Optional[list[str]] = None,
    discovery_config: Optional[dict] = None
) -> list[str]:
    """
    Find Terraform state files based on discovery mode.

    Modes:
        explicit: Use state_sources list only
        local: Parse .terraform/ and backend.tf
        auto: Scan S3 buckets from discovery_config
        hybrid: Try all, return all found
    """
    found_states = []

    if discovery_mode in ("explicit", "hybrid") and state_sources:
        found_states.extend(state_sources)

    if discovery_mode in ("local", "hybrid"):
        local_states = await _discover_local_states()
        found_states.extend(local_states)

    if discovery_mode in ("auto", "hybrid") and discovery_config:
        auto_states = await _discover_s3_states(discovery_config)
        found_states.extend(auto_states)

    return list(set(found_states))  # dedupe


async def _discover_local_states() -> list[str]:
    """Find state files from .terraform/ directory"""
    # TODO: Parse .terraform/terraform.tfstate for backend config
    # TODO: Check for local terraform.tfstate
    return []


async def _discover_s3_states(config: dict) -> list[str]:
    """Scan S3 buckets for state files"""
    # TODO: List S3 buckets matching config patterns
    # TODO: Search for *.tfstate files
    return []


async def what_terraform_owns_resource(
    resource_arn: str,
    state_sources: Optional[list[str]] = None,
    discovery_mode: str = "hybrid",
    discovery_config: Optional[dict] = None
) -> dict:
    """
    Check if AWS resource is Terraform-managed, return ownership details.

    Args:
        resource_arn: AWS ARN or bare resource ID
        state_sources: Explicit state locations (S3 URIs, local paths, TFC paths)
        discovery_mode: "explicit", "local", "auto", or "hybrid"
        discovery_config: Config for auto-discovery (S3 bucket patterns, etc.)

    Returns:
        terraform_managed: bool
        conflict: bool (true if multiple states own this resource)
        matches: list of ownership records
        primary_match: most recent match (by last_applied)
        recommended_action: resolution steps if conflict
    """
    # Parse input
    try:
        identifier = parse_resource_identifier(resource_arn)
    except UnsupportedResourceError as e:
        return {
            "terraform_managed": False,
            "error": str(e),
            "matches": []
        }

    # Find state files
    state_files = await discover_state_files(
        discovery_mode=discovery_mode,
        state_sources=state_sources,
        discovery_config=discovery_config
    )

    if not state_files:
        return {
            "terraform_managed": False,
            "conflict": False,
            "matches": [],
            "error": "No state files found"
        }

    # Search each state file
    matches = []
    for state_location in state_files:
        match = await _search_state_file(state_location, identifier)
        if match:
            matches.append(match)

    # Build response
    if not matches:
        return {
            "terraform_managed": False,
            "conflict": False,
            "matches": [],
            "resource_id": identifier.resource_id,
            "service": identifier.service
        }

    # Sort by last_applied (most recent first)
    matches.sort(key=lambda m: m.get("last_applied", ""), reverse=True)

    conflict = len(matches) > 1
    result = {
        "terraform_managed": True,
        "conflict": conflict,
        "matches": matches,
        "primary_match": matches[0]
    }

    if conflict:
        result["recommended_action"] = _build_conflict_resolution(matches)

    return result


async def _search_state_file(state_location: str, identifier: ResourceIdentifier) -> Optional[dict]:
    """Search single state file for resource"""
    try:
        parser = TerraformStateParser()
        last_modified = None

        # Load state based on location type
        if state_location.startswith("s3://"):
            state_json, last_modified = await _load_state_from_s3(state_location)
            parser.load_from_json(state_json)
        elif state_location.startswith("app.terraform.io/"):
            # TFC support - not implemented yet
            return None
        else:
            # Local file or directory
            state_path = Path(state_location)
            if state_path.is_dir():
                state_path = state_path / "terraform.tfstate"
            if not state_path.exists():
                return None
            parser.load_from_file(str(state_path))
            last_modified = datetime.fromtimestamp(state_path.stat().st_mtime)

        # Search for resource
        resource = parser.find_by_id(identifier.resource_id)
        if not resource:
            return None

        # Extract workspace from path
        workspace = _extract_workspace(state_location)

        return {
            "resource_id": identifier.resource_id,
            "terraform_address": resource["address"],
            "resource_type": resource["type"],
            "module": resource.get("module"),
            "workspace": workspace,
            "state_location": state_location,
            "last_applied": last_modified.isoformat() if last_modified else None,
            "attributes": resource.get("attributes", {})
        }

    except Exception as e:
        print(f"Warning: Failed to search {state_location}: {e}")
        return None


async def _load_state_from_s3(s3_uri: str) -> tuple[str, Optional[datetime]]:
    """Load state file from S3, return content and last modified"""
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else "terraform.tfstate"

    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket, Key=key)
    content = response["Body"].read().decode("utf-8")
    last_modified = response.get("LastModified")

    return content, last_modified


def _extract_workspace(state_location: str) -> str:
    """Extract workspace name from state path"""
    # Common patterns:
    # s3://bucket/env/production/terraform.tfstate -> production
    # s3://bucket/workspaces/dev/terraform.tfstate -> dev
    # /path/to/env:production/terraform.tfstate -> production
    # Default to "default" if can't determine

    path = state_location.lower()

    # Check for env: prefix pattern
    if "env:" in path:
        match = re.search(r"env:([^/]+)", path)
        if match:
            return match.group(1)

    # Check for common directory patterns
    patterns = [
        r"/workspaces?/([^/]+)/",
        r"/env(?:ironment)?s?/([^/]+)/",
        r"/([^/]+)/terraform\.tfstate$",
    ]

    for pattern in patterns:
        match = re.search(pattern, path)
        if match:
            workspace = match.group(1)
            # Skip generic names
            if workspace not in ["terraform", "state", "tfstate", "states"]:
                return workspace

    return "default"


def _build_conflict_resolution(matches: list[dict]) -> dict:
    """Generate resolution steps for state conflicts"""
    return {
        "warning": f"Resource found in {len(matches)} state files",
        "steps": [
            "1. Identify which state should own this resource",
            "2. Run 'terraform state rm' in incorrect state(s)",
            "3. Verify with 'terraform plan' in correct state"
        ],
        "locations": [m["state_location"] for m in matches]
    }
