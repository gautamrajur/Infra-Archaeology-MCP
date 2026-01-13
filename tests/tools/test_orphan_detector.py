"""Tests for orphan detector"""

import pytest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from infra_archaeology_mcp.tools.orphan_detector import (
    find_orphaned_resources,
    _build_managed_id_set,
    _generate_recommendation,
)


# Sample Terraform state
SAMPLE_STATE = {
    "version": 4,
    "resources": [
        {
            "mode": "managed",
            "type": "aws_instance",
            "name": "managed_server",
            "instances": [{"attributes": {"id": "i-managed001"}}]
        },
        {
            "mode": "managed",
            "type": "aws_s3_bucket",
            "name": "managed_bucket",
            "instances": [{"attributes": {"id": "managed-bucket-123"}}]
        }
    ]
}

# Sample AWS resources (mix of managed and orphaned)
SAMPLE_AWS_RESOURCES = [
    {"resource_id": "i-managed001", "resource_type": "ec2", "name": "managed"},
    {"resource_id": "i-orphan001", "resource_type": "ec2", "name": "orphan1"},
    {"resource_id": "i-orphan002", "resource_type": "ec2", "name": "orphan2"},
    {"resource_id": "managed-bucket-123", "resource_type": "s3", "name": "managed"},
    {"resource_id": "orphan-bucket-456", "resource_type": "s3", "name": "orphan"},
]

# Sample costs
SAMPLE_COSTS = {
    "i-orphan001": 150.00,
    "i-orphan002": 50.00,
    "orphan-bucket-456": 25.00,
}


class TestBuildManagedIdSet:

    @pytest.mark.asyncio
    async def test_build_from_local_state(self):
        """Build managed ID set from local state file"""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f:
            json.dump(SAMPLE_STATE, f)
            state_path = f.name

        try:
            managed_ids = await _build_managed_id_set([state_path])
            assert "i-managed001" in managed_ids
            assert "managed-bucket-123" in managed_ids
            assert len(managed_ids) == 2
        finally:
            Path(state_path).unlink()

    @pytest.mark.asyncio
    async def test_build_from_multiple_states(self):
        """Combine IDs from multiple state files"""
        state1 = {"version": 4, "resources": [
            {"mode": "managed", "type": "aws_instance", "name": "a",
             "instances": [{"attributes": {"id": "i-aaa"}}]}
        ]}
        state2 = {"version": 4, "resources": [
            {"mode": "managed", "type": "aws_instance", "name": "b",
             "instances": [{"attributes": {"id": "i-bbb"}}]}
        ]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f1:
            json.dump(state1, f1)
            path1 = f1.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f2:
            json.dump(state2, f2)
            path2 = f2.name

        try:
            managed_ids = await _build_managed_id_set([path1, path2])
            assert "i-aaa" in managed_ids
            assert "i-bbb" in managed_ids
        finally:
            Path(path1).unlink()
            Path(path2).unlink()

    @pytest.mark.asyncio
    async def test_handle_invalid_state_gracefully(self):
        """Continue if one state file is invalid"""
        valid_state = {"version": 4, "resources": [
            {"mode": "managed", "type": "aws_instance", "name": "x",
             "instances": [{"attributes": {"id": "i-valid"}}]}
        ]}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".tfstate", delete=False) as f:
            json.dump(valid_state, f)
            valid_path = f.name

        try:
            # Include nonexistent path - should not fail
            managed_ids = await _build_managed_id_set([
                "/nonexistent/state.tfstate",
                valid_path
            ])
            assert "i-valid" in managed_ids
        finally:
            Path(valid_path).unlink()


class TestFindOrphanedResources:

    @pytest.mark.asyncio
    async def test_returns_error_without_state_sources(self):
        """Require state_sources parameter"""
        result = await find_orphaned_resources(region="us-east-1")
        assert "error" in result

    @pytest.mark.asyncio
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_aws_resources")
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_costs")
    @patch("infra_archaeology_mcp.tools.orphan_detector._build_managed_id_set")
    async def test_filter_orphaned_resources(
        self, mock_managed, mock_costs, mock_aws
    ):
        """Filter out Terraform-managed resources"""
        mock_managed.return_value = {"i-managed001", "managed-bucket-123"}
        mock_aws.return_value = SAMPLE_AWS_RESOURCES
        mock_costs.return_value = SAMPLE_COSTS

        result = await find_orphaned_resources(
            region="us-east-1",
            state_sources=["fake/state.tfstate"]
        )

        orphan_ids = [r["resource_id"] for r in result["orphaned_resources"]]
        assert "i-orphan001" in orphan_ids
        assert "i-orphan002" in orphan_ids
        assert "orphan-bucket-456" in orphan_ids
        assert "i-managed001" not in orphan_ids
        assert "managed-bucket-123" not in orphan_ids

    @pytest.mark.asyncio
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_aws_resources")
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_costs")
    @patch("infra_archaeology_mcp.tools.orphan_detector._build_managed_id_set")
    async def test_sort_by_cost_descending(
        self, mock_managed, mock_costs, mock_aws
    ):
        """Sort orphaned resources by monthly cost (highest first)"""
        mock_managed.return_value = set()  # nothing managed
        mock_aws.return_value = SAMPLE_AWS_RESOURCES
        mock_costs.return_value = SAMPLE_COSTS

        result = await find_orphaned_resources(
            region="us-east-1",
            state_sources=["fake/state.tfstate"]
        )

        costs = [r["monthly_cost"] for r in result["orphaned_resources"]]
        assert costs == sorted(costs, reverse=True)

    @pytest.mark.asyncio
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_aws_resources")
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_costs")
    @patch("infra_archaeology_mcp.tools.orphan_detector._build_managed_id_set")
    async def test_summary_totals(
        self, mock_managed, mock_costs, mock_aws
    ):
        """Calculate correct summary totals"""
        mock_managed.return_value = {"i-managed001", "managed-bucket-123"}
        mock_aws.return_value = SAMPLE_AWS_RESOURCES
        mock_costs.return_value = SAMPLE_COSTS

        result = await find_orphaned_resources(
            region="us-east-1",
            state_sources=["fake/state.tfstate"]
        )

        assert result["summary"]["total_orphaned"] == 3
        assert result["summary"]["total_monthly_cost"] == 225.00


class TestGenerateRecommendation:

    def test_ec2_stopped_no_volumes_safe(self):
        """Stopped EC2 with no volumes = safe to delete"""
        resource = {
            "resource_type": "ec2",
            "state": "stopped",
            "attached_volumes": [],
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "high"
        assert rec["action"] == "Safe to delete"

    def test_ec2_running_investigate(self):
        """Running EC2 = investigate usage"""
        resource = {
            "resource_type": "ec2",
            "state": "running",
            "attached_volumes": [],
            "monthly_cost": 50
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "low"
        assert rec["action"] == "Investigate usage"

    def test_ec2_with_volumes_review(self):
        """EC2 with volumes = review dependencies"""
        resource = {
            "resource_type": "ec2",
            "state": "stopped",
            "attached_volumes": ["vol-123", "vol-456"],
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "medium"
        assert rec["action"] == "Review dependencies"
        assert "2 attached volumes" in rec["reasons"]

    def test_rds_running_investigate(self):
        """Running RDS = investigate usage"""
        resource = {
            "resource_type": "rds",
            "state": "available",
            "monthly_cost": 200
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "low"
        assert rec["action"] == "Investigate usage"

    def test_rds_with_replicas_review(self):
        """RDS with replicas = review dependencies"""
        resource = {
            "resource_type": "rds",
            "state": "available",
            "has_replicas": True,
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "low"
        assert "Has read replicas" in rec["reasons"]

    def test_s3_empty_safe(self):
        """Empty S3 bucket = safe to delete"""
        resource = {
            "resource_type": "s3",
            "is_empty": True,
            "has_versioning": False,
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "high"
        assert rec["action"] == "Safe to delete"

    def test_s3_with_versioning_investigate(self):
        """S3 with versioning = investigate"""
        resource = {
            "resource_type": "s3",
            "is_empty": False,
            "has_versioning": True,
            "monthly_cost": 10
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "low"
        assert rec["action"] == "Investigate usage"

    def test_high_cost_flagged(self):
        """High cost resources flagged in reasons"""
        resource = {
            "resource_type": "ec2",
            "state": "stopped",
            "attached_volumes": [],
            "monthly_cost": 150
        }
        rec = _generate_recommendation(resource)
        assert any("high cost" in r for r in rec["reasons"])

    def test_ec2_with_elastic_ip(self):
        """EC2 with Elastic IP = review dependencies"""
        resource = {
            "resource_type": "ec2",
            "state": "stopped",
            "attached_volumes": [],
            "has_elastic_ip": True,
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "medium"
        assert "Has Elastic IP" in rec["reasons"]

    def test_rds_stopped(self):
        """Stopped RDS = review before delete"""
        resource = {
            "resource_type": "rds",
            "state": "stopped",
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "medium"
        assert rec["action"] == "Review before delete"

    def test_rds_is_replica(self):
        """RDS replica = review dependencies"""
        resource = {
            "resource_type": "rds",
            "state": "available",
            "is_replica": True,
            "monthly_cost": 0
        }
        rec = _generate_recommendation(resource)
        assert "Is a read replica" in rec["reasons"]

    def test_s3_not_empty_no_versioning(self):
        """S3 with objects but no versioning = review contents"""
        resource = {
            "resource_type": "s3",
            "is_empty": False,
            "has_versioning": False,
            "monthly_cost": 5
        }
        rec = _generate_recommendation(resource)
        assert rec["confidence"] == "medium"
        assert rec["action"] == "Review contents"


class TestOrphanDetectorIntegration:
    """Integration tests with readable output"""

    @pytest.mark.asyncio
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_aws_resources")
    @patch("infra_archaeology_mcp.tools.orphan_detector._fetch_costs")
    @patch("infra_archaeology_mcp.tools.orphan_detector._build_managed_id_set")
    async def test_full_report_with_cost_savings(
        self, mock_managed, mock_costs, mock_aws
    ):
        """Full orphan report with cost savings summary"""
        # Simulate realistic orphaned resources
        mock_managed.return_value = {"i-prod-001", "prod-bucket"}
        mock_aws.return_value = [
            # Managed (should be filtered)
            {"resource_id": "i-prod-001", "resource_type": "ec2", "name": "prod"},
            {"resource_id": "prod-bucket", "resource_type": "s3", "name": "prod"},
            # Orphaned EC2
            {
                "resource_id": "i-orphan-web",
                "resource_type": "ec2",
                "name": "old-web-server",
                "state": "stopped",
                "attached_volumes": [],
                "has_elastic_ip": False,
            },
            {
                "resource_id": "i-orphan-dev",
                "resource_type": "ec2",
                "name": "dev-test-instance",
                "state": "running",
                "attached_volumes": ["vol-123"],
                "has_elastic_ip": True,
            },
            # Orphaned RDS
            {
                "resource_id": "orphan-db",
                "resource_type": "rds",
                "name": "old-database",
                "state": "stopped",
                "has_replicas": False,
                "is_replica": False,
            },
            # Orphaned S3
            {
                "resource_id": "orphan-logs-bucket",
                "resource_type": "s3",
                "name": "old-logs",
                "is_empty": True,
                "has_versioning": False,
            },
        ]
        mock_costs.return_value = {
            "i-orphan-web": 45.00,
            "i-orphan-dev": 120.00,
            "orphan-db": 85.00,
            "orphan-logs-bucket": 2.50,
        }

        result = await find_orphaned_resources(
            region="us-east-1",
            state_sources=["s3://my-bucket/terraform.tfstate"]
        )

        # Verify structure
        assert result["summary"]["total_orphaned"] == 4
        assert result["summary"]["total_monthly_cost"] == 252.50

        # Verify sorted by cost (highest first)
        costs = [r["monthly_cost"] for r in result["orphaned_resources"]]
        assert costs == [120.00, 85.00, 45.00, 2.50]

        # Verify recommendations present
        for resource in result["orphaned_resources"]:
            assert "recommendation" in resource
            assert "confidence" in resource["recommendation"]
            assert "action" in resource["recommendation"]

        # Print readable report
        print("\n" + "=" * 60)
        print("ORPHANED RESOURCES REPORT")
        print("=" * 60)
        print(f"Region: {result['summary']['region']}")
        print(f"Total orphaned: {result['summary']['total_orphaned']}")
        print(f"Potential monthly savings: ${result['summary']['total_monthly_cost']:.2f}")
        print("-" * 60)

        for r in result["orphaned_resources"]:
            rec = r["recommendation"]
            print(f"\n[{rec['confidence'].upper()}] {r['resource_type'].upper()}: {r['resource_id']}")
            print(f"  Cost: ${r['monthly_cost']:.2f}/month")
            print(f"  Action: {rec['action']}")
            if rec["reasons"]:
                print(f"  Reasons: {', '.join(rec['reasons'])}")

        print("\n" + "=" * 60)
