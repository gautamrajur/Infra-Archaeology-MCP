"""Tool: find_orphaned_resources - detect AWS resources not in Terraform"""

import boto3
import aioboto3
from datetime import datetime, timedelta
from typing import Optional
from infra_archaeology_mcp.terraform.state_parser import TerraformStateParser


async def find_orphaned_resources(
    region: str,
    state_sources: Optional[list[str]] = None,
    resource_types: list[str] = ["ec2", "rds", "s3"]
) -> dict:
    """
    Find AWS resources not managed by any Terraform state.

    Args:
        region: AWS region to scan
        state_sources: List of state file paths (S3 URIs or local paths)
        resource_types: Resource types to check

    Returns:
        summary + list of orphaned resources sorted by monthly cost
    """
    if not state_sources:
        return {"error": "state_sources required", "orphaned_resources": []}

    # Step 1: Build set of all Terraform-managed IDs (O(n) once)
    managed_ids = await _build_managed_id_set(state_sources)

    # Step 2: Fetch all AWS resources in region
    aws_resources = await _fetch_aws_resources(region, resource_types)

    # Step 3: Filter to orphaned (O(1) per resource)
    orphaned = [r for r in aws_resources if r["resource_id"] not in managed_ids]

    # Step 4: Enrich with cost data
    resource_ids = [r["resource_id"] for r in orphaned]
    costs = await _fetch_costs(region, resource_ids)

    for resource in orphaned:
        resource["monthly_cost"] = costs.get(resource["resource_id"], 0.0)
        resource["recommendation"] = _generate_recommendation(resource)

    # Step 5: Sort by cost (highest first)
    orphaned.sort(key=lambda r: r["monthly_cost"], reverse=True)

    total_cost = sum(r["monthly_cost"] for r in orphaned)

    return {
        "summary": {
            "total_orphaned": len(orphaned),
            "total_monthly_cost": round(total_cost, 2),
            "region": region,
            "resource_types_scanned": resource_types,
            "terraform_states_checked": len(state_sources)
        },
        "orphaned_resources": orphaned
    }


async def _build_managed_id_set(state_sources: list[str]) -> set[str]:
    """Load all state files and build set of managed resource IDs"""
    managed_ids = set()

    for source in state_sources:
        try:
            parser = TerraformStateParser()

            if source.startswith("s3://"):
                state_json = await _fetch_state_from_s3(source)
                parser.load_from_json(state_json)
            else:
                parser.load_from_file(source)

            id_map = parser.build_id_map()
            managed_ids.update(id_map.keys())

        except Exception as e:
            # Log but continue - don't fail if one state is unreadable
            print(f"Warning: Failed to load {source}: {e}")

    return managed_ids


async def _fetch_state_from_s3(s3_uri: str) -> str:
    """Fetch Terraform state from S3"""
    # Parse s3://bucket/key
    parts = s3_uri.replace("s3://", "").split("/", 1)
    bucket = parts[0]
    if len(parts) < 2 or parts[1].strip() == '':
        key = 'terraform.tfstate'
    else:
        key = parts[1]

    async with aioboto3.client('s3') as s3:
        response = await s3.get_object(Bucket=bucket, Key=key)
    return response["Body"].read().decode("utf-8")


async def _fetch_aws_resources(region: str, resource_types: list[str]) -> list[dict]:
    """Fetch all resources of specified types from AWS"""
    resources = []

    if "ec2" in resource_types:
        resources.extend(await _fetch_ec2_instances(region))

    if "rds" in resource_types:
        resources.extend(await _fetch_rds_instances(region))

    if "s3" in resource_types:
        resources.extend(await _fetch_s3_buckets(region))

    return resources


async def _fetch_ec2_instances(region: str) -> list[dict]:
    """Fetch all EC2 instances with dependency info"""
    ec2 = boto3.client("ec2", region_name=region)
    resources = []

    paginator = ec2.get_paginator("describe_instances")
    for page in paginator.paginate():
        for reservation in page["Reservations"]:
            for instance in reservation["Instances"]:
                if instance["State"]["Name"] == "terminated":
                    continue

                tags = {t["Key"]: t["Value"] for t in instance.get("Tags", [])}

                # Dependency info for recommendations
                volumes = [b["Ebs"]["VolumeId"] for b in instance.get("BlockDeviceMappings", []) if "Ebs" in b]
                security_groups = [sg["GroupId"] for sg in instance.get("SecurityGroups", [])]
                has_public_ip = instance.get("PublicIpAddress") is not None
                has_elastic_ip = any(
                    ni.get("Association", {}).get("IpOwnerId") != "amazon"
                    for ni in instance.get("NetworkInterfaces", [])
                    if "Association" in ni
                )

                resources.append({
                    "resource_id": instance["InstanceId"],
                    "resource_type": "ec2",
                    "name": tags.get("Name", ""),
                    "instance_type": instance.get("InstanceType"),
                    "state": instance["State"]["Name"],
                    "launch_time": instance["LaunchTime"].isoformat(),
                    "tags": tags,
                    # Dependency fields
                    "attached_volumes": volumes,
                    "security_groups": security_groups,
                    "has_public_ip": has_public_ip,
                    "has_elastic_ip": has_elastic_ip,
                })

    return resources


async def _fetch_rds_instances(region: str) -> list[dict]:
    """Fetch all RDS instances with dependency info"""
    rds = boto3.client("rds", region_name=region)
    resources = []

    paginator = rds.get_paginator("describe_db_instances")
    for page in paginator.paginate():
        for db in page["DBInstances"]:
            # Dependency info
            has_snapshots = db.get("LatestRestorableTime") is not None
            has_replicas = len(db.get("ReadReplicaDBInstanceIdentifiers", [])) > 0
            is_replica = db.get("ReadReplicaSourceDBInstanceIdentifier") is not None
            is_public = db.get("PubliclyAccessible", False)

            resources.append({
                "resource_id": db["DBInstanceIdentifier"],
                "resource_type": "rds",
                "name": db["DBInstanceIdentifier"],
                "engine": db["Engine"],
                "instance_class": db["DBInstanceClass"],
                "state": db["DBInstanceStatus"],
                "tags": {},
                # Dependency fields
                "has_snapshots": has_snapshots,
                "has_replicas": has_replicas,
                "is_replica": is_replica,
                "is_public": is_public,
            })

    return resources


async def _fetch_s3_buckets(region: str) -> list[dict]:
    """Fetch all S3 buckets with access info"""
    s3 = boto3.client("s3", region_name=region)
    resources = []

    response = s3.list_buckets()
    for bucket in response.get("Buckets", []):
        bucket_name = bucket["Name"]

        try:
            loc = s3.get_bucket_location(Bucket=bucket_name)
            bucket_region = loc.get("LocationConstraint") or "us-east-1"

            if bucket_region != region:
                continue

            # Check recent access and object count
            is_empty = False
            recently_accessed = False
            try:
                objects = s3.list_objects_v2(Bucket=bucket_name, MaxKeys=1)
                is_empty = objects.get("KeyCount", 0) == 0
            except Exception:
                pass

            # Check if versioning enabled (indicates active use)
            has_versioning = False
            try:
                ver = s3.get_bucket_versioning(Bucket=bucket_name)
                has_versioning = ver.get("Status") == "Enabled"
            except Exception:
                pass

            resources.append({
                "resource_id": bucket_name,
                "resource_type": "s3",
                "name": bucket_name,
                "created": bucket["CreationDate"].isoformat(),
                "tags": {},
                # Dependency fields
                "is_empty": is_empty,
                "has_versioning": has_versioning,
            })
        except Exception:
            continue

    return resources


async def _fetch_costs(region: str, resource_ids: list[str]) -> dict[str, float]:
    """Fetch monthly costs for resources from Cost Explorer"""
    if not resource_ids:
        return {}

    try:
        ce = boto3.client("ce", region_name="us-east-1")  # CE is global

        end = datetime.now()
        start = end - timedelta(days=30)

        response = ce.get_cost_and_usage(
            TimePeriod={
                "Start": start.strftime("%Y-%m-%d"),
                "End": end.strftime("%Y-%m-%d")
            },
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "RESOURCE_ID"}],
            Filter={
                "Dimensions": {
                    "Key": "RESOURCE_ID",
                    "Values": resource_ids
                }
            }
        )

        costs = {}
        for result in response.get("ResultsByTime", []):
            for group in result.get("Groups", []):
                resource_id = group["Keys"][0]
                amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                costs[resource_id] = costs.get(resource_id, 0) + amount

        return costs

    except Exception as e:
        # Cost Explorer may not be enabled or accessible
        print(f"Warning: Cost Explorer unavailable: {e}")
        return {}


def _generate_recommendation(resource: dict) -> dict:
    """Generate deletion recommendation based on resource state"""
    resource_type = resource.get("resource_type")
    confidence = "high"
    action = "Safe to delete"
    reasons = []

    if resource_type == "ec2":
        has_dependencies = False

        if resource.get("attached_volumes"):
            has_dependencies = True
            confidence = "medium"
            action = "Review dependencies"
            reasons.append(f"{len(resource['attached_volumes'])} attached volumes")

        if resource.get("has_elastic_ip"):
            has_dependencies = True
            confidence = "medium"
            action = "Review dependencies"
            reasons.append("Has Elastic IP")

        if resource.get("state") == "running":
            confidence = "low"
            action = "Investigate usage"
            reasons.append("Instance is running")
        elif resource.get("state") == "stopped":
            if not has_dependencies:
                confidence = "high"
                action = "Safe to delete"
                reasons.append("Stopped with no volumes")

    elif resource_type == "rds":
        if resource.get("has_replicas"):
            confidence = "low"
            action = "Review dependencies"
            reasons.append("Has read replicas")

        if resource.get("is_replica"):
            confidence = "medium"
            action = "Review dependencies"
            reasons.append("Is a read replica")

        if resource.get("state") == "available":
            confidence = "low"
            action = "Investigate usage"
            reasons.append("Database is running")

        if resource.get("state") == "stopped":
            confidence = "medium"
            action = "Review before delete"
            reasons.append("Database is stopped")

    elif resource_type == "s3":
        if resource.get("is_empty"):
            confidence = "high"
            action = "Safe to delete"
            reasons.append("Bucket is empty")
        else:
            confidence = "medium"
            action = "Review contents"
            reasons.append("Bucket has objects")

        if resource.get("has_versioning"):
            confidence = "low"
            action = "Investigate usage"
            reasons.append("Versioning enabled")

    # Cost consideration
    monthly_cost = resource.get("monthly_cost", 0)
    if monthly_cost > 100:
        reasons.append(f"${monthly_cost:.2f}/month - high cost")
    elif monthly_cost == 0:
        reasons.append("No recent cost data")

    return {
        "confidence": confidence,
        "action": action,
        "reasons": reasons
    }
