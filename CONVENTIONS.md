# Code Conventions

## Naming

### Methods
- Use verb_noun format: `load_from_json()`, `build_id_map()`, `find_by_id()`
- Avoid redundant prefixes: `get_resource_mapping()` → `build_id_map()`
- Keep names under 25 chars when possible

### Variables
- `id_map` not `resource_id_to_terraform_metadata_mapping`
- `ec2` not `ec2_resource_instance`
- Abbreviate only common terms: `tf` (terraform), `ec2`, `rds`, `s3`

### Test Methods
- `test_<action>_<subject>`: `test_parse_state_from_json`
- No "should" or "when" phrases

## Comments

### Docstrings
- One line, max 60 chars
- State what it does, not how
- Skip if method name is self-explanatory

```python
# Good
def build_id_map(self):
    """Build AWS resource ID -> Terraform metadata lookup"""

# Bad
def build_id_map(self):
    """This method iterates through all resources and creates a dictionary
    that maps AWS resource IDs to their corresponding Terraform metadata
    including the address, type, and attributes."""
```

### Inline Comments
- Explain "why", not "what"
- Max 40 chars
- Use sparingly

```python
# Good
parser.resources = []  # reset before reload

# Bad
parser.resources = []  # set the resources list to an empty list
```

## Code Style

### Imports
- stdlib → third-party → local
- One import per line for local modules

### Error Handling
- Raise specific exceptions: `FileNotFoundError`, `ValueError`
- No bare `except:`
- Error messages under 50 chars

### Type Hints
- Use for public methods
- Skip for obvious cases (`self`, simple returns)

## File Structure

```
src/infra_archaeology_mcp/
├── server.py           # MCP entry point
├── aws/                # AWS API clients
├── terraform/          # Terraform parsing
└── tools/              # MCP tool implementations
```

## Testing

### Structure
Mirror src/ layout in tests/:
```
tests/
├── __init__.py
├── terraform/              # matches src/.../terraform/
│   ├── __init__.py
│   └── test_state_parser.py
├── tools/                  # matches src/.../tools/
│   ├── __init__.py
│   ├── test_terraform_lookup.py
│   └── test_creator_lookup_manual.py  # manual/integration tests
└── aws/                    # matches src/.../aws/
    └── __init__.py
```

### Naming
- File: `test_<module_name>.py`
- Class: `Test<ClassName>`
- Method: `test_<action>_<subject>`

### Rules
- One test class per module
- Fixtures at top of file
- No mocks unless necessary
- Manual tests suffixed with `_manual.py` (excluded from pytest)

### Running Tests
```bash
pytest tests/ -v                              # all tests
pytest tests/terraform/ -v                    # module tests
pytest tests/ --ignore=tests/**/*_manual.py   # skip manual
```
