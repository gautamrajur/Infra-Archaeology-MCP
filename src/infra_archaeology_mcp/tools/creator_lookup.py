"""
Tool: who_created_resource
Finds the creator of a cloud resource
"""

import boto3
from datetime import datetime
from infra_archaeology_mcp.aws.cloudtrail import CloudTrailClient, EVENT_MAPPINGS

async def who_created_resource(
    resource_id: str,
    resource_type: str,
    region: str = "us-east-1"
) -> dict:
    """
    Find who created a specific cloud resource
    Args:
        resource_id: The resource identifier (e.g., i-1234567890abcdef0)
        resource_type: Type of resource ('ec2', 'rds', 's3')
        region: AWS region
    Returns:
        Dictionary with creator information
    """
    
    resource_info = await _get_resource_info(resource_id, resource_type, region)
    
    ct_client = CloudTrailClient(region=region)
    event_names = EVENT_MAPPINGS.get(resource_type, [])
    
    creation_event = ct_client.find_create_event(resource_id, event_names)
    
    result = {
        "resource_id": resource_id,
        "resource_type": resource_type,
        "region": region,
        **resource_info
    }
    
    if creation_event:
        result.update({
            "creator": creation_event["creator"],
            "created_at": creation_event["created_at"],
            "creation_method": _parse_user_agent(creation_event["user_agent"]),
            "source_ip": creation_event["source_ip"],
            "cloudtrail_event_id": creation_event["event_id"]
        })
    else:
        result.update({
            "creator": "Unknown (CloudTrail logs not available)",
            "plausible cause": f"Resource may be older than 90 days or CloudTrail not enabled"
        })
    
    return result

async def _get_resource_info(resource_id: str, resource_type: str, region: str) -> dict:
    #Get more more info for the current resource event
    session = boto3.Session(region_name=region)
    
    if resource_type == "ec2":
        ec2 = session.client('ec2')
        try: 
            response = ec2.describe_instances(InstanceIds=[resource_id])
            if response['Reservations']:
                instance = response['Reservations'][0]['Instances'][0]
                return {
                    "state": instance['State']['Name'],
                    "instance_type": instance['InstanceType'],
                    "launch_time": instance['LaunchTime'].isoformat(),
                    "tags": {tag['Key']: tag['Value'] for tag in instance.get('Tags', [])}
                }
        except Exception as e:
            return {"error": f"Failed to get EC2 info: {str(e)}"}
        
    elif resource_type == "rds":
        rds = session.client('rds')
        try:
            response = rds.describe_db_instances(DBInstanceIdentifier=resource_id)
            if response['DBInstances']:
                db = response['DBInstances'][0]
                return {
                    "state": db['DBInstanceStatus'],
                    "engine": db['Engine'],
                    "instance_class": db['DBInstanceClass'],
                    "created_time": db['InstanceCreateTime'].isoformat() if 'InstanceCreateTime' in db else None
                }
        except Exception as e:
            return {"error": f"Failed to get RDS info: {str(e)}"}
    
    elif resource_type == "s3":
        s3 = session.client('s3')
        try:
            # S3 bucket names are the resource_id
            response = s3.get_bucket_location(Bucket=resource_id)
            tags_response = s3.get_bucket_tagging(Bucket=resource_id)
            return {
                "location": response['LocationConstraint'] or 'us-east-1',
                "tags": {tag['Key']: tag['Value'] for tag in tags_response.get('TagSet', [])}
            }
        except Exception as e:
            # Bucket might not have tags
            return {"note": "Bucket exists but tagging not available"}
    
    return {}
#type of creation used for resource
def _parse_user_agent(user_agent: str) -> str:
    """Parse user agent to determine creation method"""
    if 'console' in user_agent.lower():
        return "AWS Console"
    elif 'terraform' in user_agent.lower():
        return "Terraform"
    elif 'cloudformation' in user_agent.lower():
        return "CloudFormation"
    elif 'aws-cli' in user_agent.lower():
        return "AWS CLI"
    else:
        return f"API ({user_agent[:50]}...)"