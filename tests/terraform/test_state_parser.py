"""Tests for Terraform State Parser"""

import pytest
import json
from infra_archaeology_mcp.terraform.state_parser import TerraformStateParser


# Sample state with EC2, S3, RDS resources
SAMPLE_STATE = {
    "version": 4,
    "terraform_version": "1.5.0",
    "serial": 5,
    "lineage": "abc123-test",
    "outputs": {},
    "resources": [
        {
            "mode": "managed",
            "type": "aws_instance",
            "name": "web_server",
            "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
            "instances": [
                {
                    "schema_version": 1,
                    "attributes": {
                        "id": "i-1234567890abcdef0",
                        "arn": "arn:aws:ec2:us-east-1:123456789012:instance/i-1234567890abcdef0",
                        "instance_type": "t3.micro",
                        "tags": {"Name": "web-server"}
                    }
                }
            ]
        },
        {
            "mode": "managed",
            "type": "aws_s3_bucket",
            "name": "app_bucket",
            "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
            "instances": [
                {
                    "schema_version": 0,
                    "attributes": {
                        "id": "my-app-bucket-12345",
                        "arn": "arn:aws:s3:::my-app-bucket-12345",
                        "bucket": "my-app-bucket-12345"
                    }
                }
            ]
        },
        {
            "mode": "managed",
            "type": "aws_db_instance",
            "name": "main_db",
            "provider": "provider[\"registry.terraform.io/hashicorp/aws\"]",
            "instances": [
                {
                    "schema_version": 1,
                    "attributes": {
                        "id": "main-db",
                        "arn": "arn:aws:rds:us-east-1:123456789012:db:main-db",
                        "engine": "postgres"
                    }
                }
            ]
        }
    ]
}


class TestTerraformStateParser:

    def test_parse_state_from_json(self):
        """Parse v4 state format and extract resources"""
        parser = TerraformStateParser()
        parser.load_from_json(json.dumps(SAMPLE_STATE))

        assert len(parser.resources) == 3

        ec2 = parser.find_by_id("i-1234567890abcdef0")
        assert ec2 is not None
        assert ec2["address"] == "aws_instance.web_server"
        assert ec2["type"] == "aws_instance"

    def test_build_id_to_terraform_map(self):
        """Build AWS resource ID -> Terraform metadata lookup"""
        parser = TerraformStateParser()
        parser.load_from_json(json.dumps(SAMPLE_STATE))

        id_map = parser.build_id_map()

        # All 3 resources mapped
        assert "i-1234567890abcdef0" in id_map
        assert "my-app-bucket-12345" in id_map
        assert "main-db" in id_map

        # EC2 metadata correct
        ec2 = id_map["i-1234567890abcdef0"]
        assert ec2["address"] == "aws_instance.web_server"
        assert ec2["type"] == "aws_instance"
        assert ec2["attributes"]["instance_type"] == "t3.micro"

    def test_handle_missing_or_invalid_state(self):
        """Graceful error handling for bad input"""
        parser = TerraformStateParser()

        with pytest.raises(FileNotFoundError):
            parser.load_from_file("/nonexistent/terraform.tfstate")

        with pytest.raises(ValueError):
            parser.load_from_json("invalid json {{{")

        # Empty state returns empty results
        parser.load_from_json(json.dumps({"version": 4, "resources": []}))
        assert len(parser.resources) == 0
        assert parser.build_id_map() == {}
