# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Infrastructure Archaeology MCP - An MCP (Model Context Protocol) server that enables AI assistants to query AWS CloudTrail to find who created cloud resources (EC2, RDS, S3). Think "git blame for cloud infrastructure."

## Development Commands

```bash
# Setup
python3 -m venv venv && source venv/bin/activate
pip install -e .
pip install -e ".[dev]"  # includes black and pytest

# Run the MCP server directly
python -m infra_archaeology_mcp.server

# Format code
black src/ tests/

# Run tests
pytest tests/

# Run local test script (requires valid AWS credentials and resource IDs)
python tests/test_local.py
```

## Architecture

```
src/infra_archaeology_mcp/
├── server.py           # MCP server entry point, defines tools and handlers
├── tools/
│   └── creator_lookup.py   # Main tool implementation: who_created_resource()
└── aws/
    └── cloudtrail.py       # CloudTrailClient class and EVENT_MAPPINGS
```

**Data Flow:**
1. `server.py` exposes the `who_created_resource` MCP tool
2. Tool calls `creator_lookup.py` which:
   - Fetches resource metadata from AWS (EC2/RDS/S3 describe APIs)
   - Queries CloudTrail via `CloudTrailClient.find_create_event()`
   - Parses user agent to determine creation method (Console/Terraform/CLI/CloudFormation)

**Key Constants:**
- `EVENT_MAPPINGS` in `cloudtrail.py`: Maps resource types to CloudTrail event names
- CloudTrail lookback: 90 days default

## AWS Configuration

The server uses:
- AWS profile: `infra-archaeology-mcp` (configured in `cloudtrail.py`)
- Config file: `config.json` for profile/region settings
- Required IAM permissions: `cloudtrail:LookupEvents`, `ec2:Describe*`, `rds:Describe*`, `s3:GetBucket*`

## MCP Integration

For Claude Desktop, add to `~/Library/Application Support/Claude/claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "infrastructure-archaeology": {
      "command": "python",
      "args": ["-m", "infra_archaeology_mcp.server"],
      "env": {
        "AWS_PROFILE": "default",
        "AWS_DEFAULT_REGION": "us-east-1"
      }
    }
  }
}
```
