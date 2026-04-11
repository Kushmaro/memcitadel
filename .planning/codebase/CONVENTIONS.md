# Coding Conventions

**Analysis Date:** 2026-04-10

## Naming Patterns

**Files:**
- Lowercase with underscores: `miner.py`, `entity_detector.py`, `es_client.py`
- Suffixes indicate purpose: `*_miner.py` for miners, `*_detector.py` for detectors, `*_client.py` for clients
- Test files: `test_*.py` (e.g., `test_entity_registry.py`, `test_es_integration.py`)

**Functions:**
- Lowercase with underscores: `def chunk_exchanges()`, `def file_already_mined()`, `def detect_rooms_local()`
- Private functions prefix with underscore: `def _extract_wing_from_where()`, `def _build_wing_mapping()`, `def _translate_where()`
- Verb-first pattern: `get_collection()`, `scan_project()`, `extract_memories()`, `search_memories()`

**Variables:**
- Lowercase with underscores: `palace_path`, `wing_override`, `chunk_size`, `skip_dirs`
- Descriptive names over abbreviations: `chunk_overlap` not `overlap`, `min_chunk_size` not `min_size`
- Loop variables: `for doc, meta, dist in zip(...)`

**Types:**
- Class names PascalCase: `GitignoreMatcher`, `SearchError`, `EntityRegistry`, `MempalaceConfig`
- Constants UPPERCASE: `SKIP_DIRS`, `READABLE_EXTENSIONS`, `CHUNK_SIZE`, `COMMON_ENGLISH_WORDS`
- Exceptions end with `Error`: `SearchError`, `ValueError` (built-in)

## Code Style

**Formatting:**
- Tool: `ruff` (format + lint)
- Line length: 100 characters (`line-length = 100` in pyproject.toml)
- Quote style: Double quotes (`"` not `'`) — enforced by `quote-style = "double"`

**Linting:**
- Tool: `ruff` with rules `["E", "F", "W"]` (pyflakes, errors, warnings)
- Ignored: `E501` (line too long — handled by formatter)
- Target Python: 3.9+ (`target-version = "py39"`)

**Shebang:**
- Entry point scripts include shebang: `#!/usr/bin/env python3` (see `miner.py`, `cli.py`, `searcher.py`)

## Import Organization

**Order:**
1. Standard library imports (e.g., `os`, `sys`, `logging`, `json`, `pathlib`)
2. Third-party imports (e.g., `elasticsearch`, `yaml`, `chromadb`)
3. Local relative imports (e.g., `from .es_client import get_es_collection`)

**Path Aliases:**
- No aliases in use; relative imports only
- Imports include `noqa: E402` comment when necessary to suppress reordering (see `__init__.py`)

**Examples from codebase:**
```python
# miner.py
import os
import sys
import hashlib
import fnmatch
from pathlib import Path
from datetime import datetime
from collections import defaultdict

from .es_client import get_es_collection
from .palace import SKIP_DIRS, file_already_mined
```

## Error Handling

**Pattern:**
- Generic `except Exception:` catches broad errors when recovery is simple (return empty, skip file)
- Specific exceptions (`OSError`, `ValueError`, `json.JSONDecodeError`) when handling known failure modes
- Custom exception class `SearchError` for domain-specific errors (inherits from `Exception`)
- Bare `except Exception:` without logging used for silent recovery (e.g., file read failures)

**Examples:**
```python
# Generic recovery with no log
except Exception:
    return False

# Specific exception handling
except (OSError, ValueError):
    print(f"\n  Search error: {e}")

# Custom exception for clear semantics
raise SearchError(f"No palace found at {palace_path}")
```

**No re-raising pattern:** Most exceptions are caught and silently skipped or converted to return values (e.g., `file_already_mined()` returns `False` on any exception).

## Logging

**Framework:** Python `logging` module

**Configuration:**
- Module-level logger: `logger = logging.getLogger("mempalace_mcp")`
- Suppressed noise: `logging.getLogger("elastic_transport").setLevel(logging.WARNING)` in `__init__.py`
- Level set in `mcp_server.py`: `logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)`

**Patterns:**
- `logger.info()` — File operations, search results, entry points
- `logger.error()` — Exceptions, failures that should be reported
- `logger.debug()` — Debug info, argument parsing
- `logger.exception()` — Exception with full traceback: `logger.exception(f"Tool error in {tool_name}")`
- No `print()` in library code; use logger (except CLI commands)
- CLI commands use `print()` for user-facing output

**Examples:**
```python
# From searcher.py
logger.error("No palace found (ES not configured or index missing)")

# From mcp_server.py
logger.info(f"Filed drawer: {drawer_id} → {wing}/{room}")
logger.exception(f"Tool error in {tool_name}")
```

## Comments

**When to Comment:**
- File-level docstring explaining module purpose (every `.py` file)
- Class docstring for custom exceptions: `"""Raised when search cannot proceed..."""`
- Complex logic blocks separated by visual comments: `# =============================================================================`
- Section headers: `# ── Layer0 — with identity file ─────────────────────────────`

**Docstring Style:**
- Functions have one-line or multi-line docstrings in triple quotes
- Style: imperative mood ("Mine conversations") or passive ("Check if file already mined")
- Multi-line docstrings include description then parameter details (if needed)

**Examples:**
```python
def file_already_mined(collection, source_file: str, check_mtime: bool = False) -> bool:
    """Check if a file has already been filed in the palace.

    When check_mtime=True (used by project miner), returns False if the file
    has been modified since it was last mined, so it gets re-mined.
    When check_mtime=False (used by convo miner), just checks existence.
    """

def _extract_wing_from_where(where):
    """Extract wing name from a ChromaDB-style where filter.

    Returns (wing_name_or_None, remaining_where_or_None).

    Examples:
        {"wing": "code"}                                  → ("code", None)
        {"$and": [{"wing": "code"}, {"room": "testing"}]} → ("code", {"room": "testing"})
    """
```

## Function Design

**Size:**
- Typical functions are 20-50 lines
- Small helper functions (5-15 lines) marked with underscore prefix
- Top-level public functions (50+ lines) are rare; complex logic broken into private helpers

**Parameters:**
- Limited to 3-5 positional parameters
- Additional options passed as keyword arguments: `wing=None, room=None, n_results=5`
- Type hints used throughout: `def search(query: str, palace_path: str, wing: str = None)`

**Return Values:**
- Explicit return types: `-> bool`, `-> dict`, `-> list`
- No implicit `None` returns; functions either return a value or raise an exception
- Complex returns packaged as tuples for unpacking: `wing, remaining = _extract_wing_from_where(where)`

## Module Design

**Exports:**
- Files use `__all__` to declare public API: `__all__ = ["main", "__version__"]` in `__init__.py`
- Private modules (prefixed with `_`) not declared in `__all__`

**Barrel Files:**
- `memcitadel/__init__.py` exports main entry point and version
- No large barrel files; most imports are direct (e.g., `from memcitadel.searcher import search`)

## Type Hints

**Usage:**
- Function signatures always include type hints: `def search(query: str, palace_path: str)`
- Parameter hints for all arguments
- Return type hints with `->`: `-> bool`, `-> dict`, `-> list`, `-> str`
- Dict type hints use generic form: `Dict[str, float]` (with import from `typing` when needed)
- Optional parameters: `wing: str = None` (not `Optional[str]`)

**Example:**
```python
def search(
    query: str, palace_path: str, wing: str = None, room: str = None, n_results: int = 5
) -> dict:
```

## Code Organization

**Decorators:**
- `@pytest.fixture` for test fixtures
- `@classmethod` for class factory methods: `GitignoreMatcher.from_dir(cls, dir_path: Path)`
- `@property` not used (direct method calls preferred)

**Assertions vs Exceptions:**
- Assert statements used in test code only
- Production code raises exceptions for invalid input
- Test assertions: `assert wing == "code"`, `assert result["type"] == "person"`

---

*Convention analysis: 2026-04-10*
