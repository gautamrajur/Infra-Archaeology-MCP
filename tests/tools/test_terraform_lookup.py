"""Tests for terraform_lookup tool"""

import pytest
import json
import tempfile
from pathlib import Path
from infra_archaeology_mcp.tools.terraform_lookup import (
    parse_resource_identifier,
    UnsupportedResourceError,
    _search_state_file,
    _extract_workspace,
    ResourceIdentifier,
)


class TestParseResourceIdentifier:

    def test_parse_ec2_arn(self):
        """Parse EC2 instance ARN"""
        result = parse_resource_identifier(
            "arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef0"
        )
        assert result.service == "ec2"
        assert result.resource_id == "i-1234567890abcdef0"
        assert "aws_instance" in result.terraform_types

    def test_parse_ec2_bare_id(self):
        """Parse bare EC2 instance ID"""
        result = parse_resource_identifier("i-1234567890abcdef0")
        assert result.service == "ec2"
        assert result.resource_id == "i-1234567890abcdef0"

    def test_parse_rds_arn(self):
        """Parse RDS instance ARN"""
        result = parse_resource_identifier(
            "arn:aws:rds:us-east-1:123456789012:db:my-database"
        )
        assert result.service == "rds"
        assert result.resource_id == "my-database"
        assert "aws_db_instance" in result.terraform_types

    def test_parse_s3_arn(self):
        """Parse S3 bucket ARN"""
        result = parse_resource_identifier("arn:aws:s3:::my-bucket-name")
        assert result.service == "s3"
        assert result.resource_id == "my-bucket-name"
        assert "aws_s3_bucket" in result.terraform_types

    def test_parse_s3_bare_id(self):
        """Parse bare S3 bucket name"""
        result = parse_resource_identifier("my-terraform-state-bucket")
        assert result.service == "s3"
        assert result.resource_id == "my-terraform-state-bucket"

    def test_unsupported_resource(self):
        """Raise error for unsupported resource"""
        with pytest.raises(UnsupportedResourceError):
            parse_resource_identifier("arn:aws:lambda:us-east-1:123:function:foo")

    def test_invalid_input(self):
        """Raise error for invalid input"""
        with pytest.raises(UnsupportedResourceError):
            parse_resource_identifier("not-a-valid-resource-!!!")


# Sample state for testing
SAMPLE_STATE = {
    "version": 4,
    "resources": [
        {
            "mode": "managed",
            "type": "aws_instance",
            "name": "web_server",
            "instances": [
                {
                    "attributes": {
                        "id": "i-1234567890abcdef0",
                        "instance_type": "t3.micro"
                    }
                }
            ]
        },
        {
            "module": "module.vpc",
            "mode": "managed",
            "type": "aws_subnet",
            "name": "public",
            "instances": [
                {
                    "index_key": 0,
                    "attributes": {"id": "subnet-abc123"}
                }
            ]
        }
    ]
}


class TestSearchStateFile:

    @pytest.mark.asyncio
    async def test_search_local_state_file(self):
        """Find resource in local state file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f:
            json.dump(SAMPLE_STATE, f)
            state_path = f.name

        try:
            identifier = ResourceIdentifier(
                service="ec2",
                resource_id="i-1234567890abcdef0",
                terraform_types=["aws_instance"],
                original_input="i-1234567890abcdef0"
            )

            result = await _search_state_file(state_path, identifier)

            assert result is not None
            assert result["terraform_address"] == "aws_instance.web_server"
            assert result["resource_type"] == "aws_instance"
            assert result["state_location"] == state_path
        finally:
            Path(state_path).unlink()

    @pytest.mark.asyncio
    async def test_search_local_state_directory(self):
        """Find resource when given directory path"""
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "terraform.tfstate"
            with open(state_path, "w") as f:
                json.dump(SAMPLE_STATE, f)

            identifier = ResourceIdentifier(
                service="ec2",
                resource_id="i-1234567890abcdef0",
                terraform_types=["aws_instance"],
                original_input="i-1234567890abcdef0"
            )

            result = await _search_state_file(tmpdir, identifier)

            assert result is not None
            assert result["terraform_address"] == "aws_instance.web_server"

    @pytest.mark.asyncio
    async def test_search_module_resource(self):
        """Find resource inside a module"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f:
            json.dump(SAMPLE_STATE, f)
            state_path = f.name

        try:
            identifier = ResourceIdentifier(
                service="ec2",  # doesn't matter for lookup
                resource_id="subnet-abc123",
                terraform_types=["aws_subnet"],
                original_input="subnet-abc123"
            )

            result = await _search_state_file(state_path, identifier)

            assert result is not None
            assert result["terraform_address"] == "module.vpc.aws_subnet.public[0]"
            assert result["module"] == "module.vpc"
        finally:
            Path(state_path).unlink()

    @pytest.mark.asyncio
    async def test_search_resource_not_found(self):
        """Return None when resource not in state"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f:
            json.dump(SAMPLE_STATE, f)
            state_path = f.name

        try:
            identifier = ResourceIdentifier(
                service="ec2",
                resource_id="i-doesnotexist",
                terraform_types=["aws_instance"],
                original_input="i-doesnotexist"
            )

            result = await _search_state_file(state_path, identifier)
            assert result is None
        finally:
            Path(state_path).unlink()

    @pytest.mark.asyncio
    async def test_search_nonexistent_file(self):
        """Return None for missing state file"""
        identifier = ResourceIdentifier(
            service="ec2",
            resource_id="i-123",
            terraform_types=["aws_instance"],
            original_input="i-123"
        )

        result = await _search_state_file("/nonexistent/path.tfstate", identifier)
        assert result is None


class TestExtractWorkspace:

    def test_extract_from_env_directory(self):
        """Extract workspace from /env/production/ pattern"""
        assert _extract_workspace("s3://bucket/env/production/terraform.tfstate") == "production"

    def test_extract_from_environments_directory(self):
        """Extract workspace from /environments/staging/ pattern"""
        assert _extract_workspace("s3://bucket/environments/staging/terraform.tfstate") == "staging"

    def test_extract_from_workspaces_directory(self):
        """Extract workspace from /workspaces/dev/ pattern"""
        assert _extract_workspace("s3://bucket/workspaces/dev/terraform.tfstate") == "dev"

    def test_extract_from_path_segment(self):
        """Extract workspace from final directory segment"""
        assert _extract_workspace("/path/to/myproject/terraform.tfstate") == "myproject"

    def test_default_for_ambiguous_path(self):
        """Return 'default' for root-level state"""
        # When state is at bucket root, bucket name becomes workspace
        assert _extract_workspace("s3://bucket/terraform.tfstate") == "bucket"
        # Truly ambiguous returns default
        assert _extract_workspace("terraform.tfstate") == "default"

    def test_skip_generic_names(self):
        """Skip generic directory names like 'state' or 'terraform'"""
        assert _extract_workspace("s3://bucket/terraform/terraform.tfstate") == "default"
        assert _extract_workspace("s3://bucket/state/terraform.tfstate") == "default"
