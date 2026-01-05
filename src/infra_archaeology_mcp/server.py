import asyncio
import json
import os
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from infra_archaeology_mcp.tools.creator_lookup import who_created_resource

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
    