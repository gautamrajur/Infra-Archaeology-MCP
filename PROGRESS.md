# Infrastructure Archaeology MCP - Progress

## Day 2 Checkpoint (Terraform Intelligence)

### What We Built

#### 1. Terraform State Parser (`src/.../terraform/state_parser.py`)
- Parses Terraform state files (v4 format)
- Extracts resource ID → Terraform address mapping
- Supports local files and JSON strings
- API: `load_from_file()`, `load_from_json()`, `find_by_id()`, `build_id_map()`

#### 2. Terraform Ownership Lookup (`src/.../tools/terraform_lookup.py`)
- `what_terraform_owns_resource()` - check if AWS resource is Terraform-managed
- ARN/ID parsing for EC2, RDS, S3
- Discovery modes: explicit, local, auto, hybrid
- Conflict detection for resources in multiple states

#### 3. Orphaned Resource Detector (`src/.../tools/orphan_detector.py`)
- `find_orphaned_resources()` - find AWS resources not in Terraform
- Scans EC2, RDS, S3 in specified region
- Integrates with AWS Cost Explorer for monthly costs
- Smart recommendations with confidence levels:
  - `high` - Safe to delete (no dependencies)
  - `medium` - Review dependencies first
  - `low` - Investigate usage (resource active)

#### 4. MCP Server Updates (`src/.../server.py`)
Three tools now registered:
| Tool | Purpose |
|------|---------|
| `who_created_resource` | CloudTrail creator lookup |
| `what_terraform_owns_resource` | Terraform ownership check |
| `find_orphaned_resources` | Orphan detection with cost |

---

### Test Status

```
30 passed in 0.34s
```

| Module | Tests | Status |
|--------|-------|--------|
| `tests/terraform/test_state_parser.py` | 3 | ✅ |
| `tests/tools/test_terraform_lookup.py` | 7 | ✅ |
| `tests/tools/test_orphan_detector.py` | 20 | ✅ |

---

### What to Tackle Next

#### Priority 1: Complete `what_terraform_owns_resource`
- [ ] Implement `_discover_local_states()` - parse `.terraform/` directory
- [ ] Implement `_discover_s3_states()` - scan S3 for state files
- [ ] Implement `_search_state_file()` - integrate with TerraformStateParser
- [ ] Add workspace extraction from state path

#### Priority 2: Terraform Cloud Integration
- [ ] Add TFC API client for state access
- [ ] Query run history for last applied timestamp
- [ ] Support TFC workspace discovery

#### Priority 3: Additional Resource Types
- [ ] Lambda functions
- [ ] DynamoDB tables
- [ ] IAM roles
- [ ] EBS volumes (standalone)

#### Priority 4: Performance & UX
- [ ] Parallel state file loading
- [ ] Caching for repeated lookups
- [ ] Progress indicators for large scans

---

### Tech Debt & TODOs

**In `terraform_lookup.py`:**
```
line 104: # TODO: Parse .terraform/terraform.tfstate for backend config
line 105: # TODO: Check for local terraform.tfstate
line 111: # TODO: List S3 buckets matching config patterns
line 112: # TODO: Search for *.tfstate files
line 199: # TODO: Load state from S3/local/TFC
line 200: # TODO: Use TerraformStateParser.find_by_id()
line 201: # TODO: Extract workspace from state path
```

**Code Quality:**
- [ ] Add type hints to `orphan_detector.py` return types
- [ ] Add logging instead of `print()` statements
- [ ] Consider async S3/boto3 calls for better performance

**Documentation:**
- [x] CONVENTIONS.md - coding standards
- [x] CLAUDE.md - project overview
- [ ] API documentation for MCP tools

---

### File Structure

```
src/infra_archaeology_mcp/
├── server.py                    # MCP entry point (3 tools)
├── aws/
│   └── cloudtrail.py           # CloudTrail client
├── terraform/
│   ├── __init__.py
│   └── state_parser.py         # TF state parsing ✅
└── tools/
    ├── creator_lookup.py       # who_created_resource
    ├── terraform_lookup.py     # what_terraform_owns_resource (partial)
    └── orphan_detector.py      # find_orphaned_resources ✅

tests/
├── terraform/
│   └── test_state_parser.py    # 3 tests ✅
└── tools/
    ├── test_terraform_lookup.py    # 7 tests ✅
    └── test_orphan_detector.py     # 20 tests ✅
```

---

*Last updated: Day 2*
