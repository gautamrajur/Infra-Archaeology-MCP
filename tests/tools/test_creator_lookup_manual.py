"""Quick local test without MCP"""
import asyncio
from infra_archaeology_mcp.tools.creator_lookup import who_created_resource

async def test():
    # Replace with YOUR actual EC2 instance ID
    result = await who_created_resource(
        resource_id="i-012888cafd3ec60e7",  # CHANGE THIS
        resource_type="ec2",
        region="us-east-2"  # CHANGE THIS
    )
    
    print("Result:")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    import json
    asyncio.run(test())
    
    
#I have an EC2 instance i-012888cafd3ec60e7 in us-east-2.Who created it?