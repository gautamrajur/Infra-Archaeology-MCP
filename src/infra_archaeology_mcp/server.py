import asyncio
import json
import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from infra_archaeology_mcp.tools.creator_lookup import who_created_resource
from infra_archaeology_mcp.tools.terraform_lookup import what_terraform_owns_resource
from infra_archaeology_mcp.tools.orphan_detector import find_orphaned_resources

app = Server("infrastructure-archaeology")

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="who_created_resource",
            desciption="Find who created a cloud resource (EC2, RDS, S3) and when"
                        "Searches CloudTrail logs to identify the creator, timestamp, and method",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_id" : {
                        "type": "string",
                        "desciption": "The resource ID (e.g., i-1234567890abcdef0 for EC2, db-instance-name for RDS)"
                    },
                    "resource_type": {
                        "type": "string",
                        "description": "Type of resource: 'ec2', 'rds', or 's3'",
                        "enum": ["ec2", "rds", "s3"]
                    },
                    "region": {
                        "type": "string",
                        "description": "AWS region (optional, defaults to us-east-1)",
                        "default": "us-east-1"
                    }
                },
                "required": ["resource_id", "resource_type"]
            }
        ),
        Tool(
            name="what_terraform_owns_resource",
            description="Check if AWS resource is Terraform-managed, return ownership details",
            inputSchema={
                "type": "object",
                "properties": {
                    "resource_arn": {
                        "type": "string",
                        "description": "AWS ARN or bare resource ID (e.g., i-abc123, arn:aws:ec2:...)"
                    },
                    "state_sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "State locations: S3 URIs, local paths, or TFC paths"
                    },
                    "discovery_mode": {
                        "type": "string",
                        "enum": ["explicit", "local", "auto", "hybrid"],
                        "default": "hybrid",
                        "description": "How to find state files"
                    }
                },
                "required": ["resource_arn"]
            }
        ),
        Tool(
            name="find_orphaned_resources",
            description="Find AWS resources not managed by Terraform, sorted by cost",
            inputSchema={
                "type": "object",
                "properties": {
                    "region": {
                        "type": "string",
                        "description": "AWS region to scan"
                    },
                    "state_sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Terraform state locations (S3 URIs or local paths)"
                    },
                    "resource_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["ec2", "rds", "s3"]},
                        "default": ["ec2", "rds", "s3"],
                        "description": "Resource types to scan"
                    }
                },
                "required": ["region", "state_sources"]
            }
        )
    ]
    
@app.call_tool()
async def call_tools(name: str, arguments: dict) -> list[TextContent]:
    if name == "who_created_resource":
        try:
            result = await who_created_resource(
                resource_id=arguments["resource_id"],
                resource_type=arguments["resource_type"],
                region=arguments.get("region", "us-east-1")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]

    if name == "what_terraform_owns_resource":
        try:
            result = await what_terraform_owns_resource(
                resource_arn=arguments["resource_arn"],
                state_sources=arguments.get("state_sources"),
                discovery_mode=arguments.get("discovery_mode", "hybrid")
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]

    if name == "find_orphaned_resources":
        try:
            result = await find_orphaned_resources(
                region=arguments["region"],
                state_sources=arguments["state_sources"],
                resource_types=arguments.get("resource_types", ["ec2", "rds", "s3"])
            )
            return [TextContent(
                type="text",
                text=json.dumps(result, indent=2)
            )]
        except Exception as e:
            return [TextContent(
                type="text",
                text=f"Error: {str(e)}"
            )]

    raise ValueError(f"Unknown tool: {name}")
    
async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )

if __name__ == "__main__":
    asyncio.run(main())
    