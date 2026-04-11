# Testing Patterns

**Analysis Date:** 2026-04-10

## Test Framework

**Runner:**
- `pytest` 7.0+ (defined in `pyproject.toml` as `pytest>=7.0`)
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`

**Assertion Library:**
- `assert` statements (standard pytest)
- No custom assertion libraries; plain Python `assert` used throughout

**Run Commands:**
```bash
pytest tests/                        # Run all tests
pytest tests/ -v                     # Verbose output
pytest tests/ -m 'not benchmark'     # Skip benchmark tests
pytest tests/ --cov                  # With coverage report
pytest tests/test_entity_registry.py # Single test file
pytest -k test_lookup_known_person   # Run by test name pattern
```

**Coverage:**
- Tool: `pytest-cov` 4.0+
- Requirement: 85% minimum (`fail_under = 85` in pyproject.toml)
- Command: `pytest --cov=memcitadel --cov-report=html`
- Excluded from coverage: `if __name__` blocks, lines marked `pragma: no cover`
- Source under test: `memcitadel/` directory only

## Test File Organization

**Location:**
- Separate from source: `tests/` directory at project root
- Not co-located with source files

**Naming:**
- Pattern: `test_*.py` (e.g., `test_entity_registry.py`, `test_miner.py`)
- Test functions: `test_*` (e.g., `test_common_english_words_has_expected_entries`)
- Test classes: `Test*` (e.g., `class TestExtractWingFromWhere`)

**Directory Structure:**
```
tests/
├── conftest.py                    # Shared fixtures
├── test_entity_registry.py        # Unit tests for entity_registry module
├── test_es_integration.py         # Integration tests for Elasticsearch
├── test_general_extractor.py      # Unit tests for memory extraction
├── test_miner.py                  # Unit tests for file mining
├── test_layers.py                 # Unit tests for context layers
└── ...                            # Other test modules
```

## Test Markers

**Available Markers:**
- `benchmark` — Scale/performance benchmark tests (skipped by default)
- `slow` — Tests taking >30 seconds (skipped by default)
- `stress` — Destructive scale tests with 100K+ records (skipped by default)

**Default Run Excludes:**
```
addopts = "-m 'not benchmark and not slow and not stress'"
```

**Usage in Tests:**
```python
@pytest.mark.benchmark
def test_search_performance_1m_drawers():
    """Benchmark search on 1M drawer index."""

@pytest.mark.slow
def test_full_project_mining():
    """Takes 45 seconds."""

@pytest.mark.stress
def test_100k_drawer_stress():
    """Destructive test — creates massive index."""
```

## Test Structure

**Common Test Patterns:**

### Simple Unit Test
```python
def test_common_english_words_has_expected_entries():
    assert "ever" in COMMON_ENGLISH_WORDS
    assert "grace" in COMMON_ENGLISH_WORDS
    assert "will" in COMMON_ENGLISH_WORDS
```

### Test with Fixtures
```python
def test_load_from_nonexistent_dir(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    assert registry.people == {}
    assert registry.projects == []
    assert registry.mode == "personal"
```

### Test with Setup/Teardown via Try-Finally
```python
def test_project_mining():
    tmpdir = tempfile.mkdtemp()
    try:
        project_root = Path(tmpdir).resolve()
        # ... test code ...
        assert col.count() > 0
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
```

### Test Class Pattern
```python
class TestExtractWingFromWhere:
    def test_none(self):
        wing, remaining = _extract_wing_from_where(None)
        assert wing is None
        assert remaining is None

    def test_simple_wing(self):
        wing, remaining = _extract_wing_from_where({"wing": "code"})
        assert wing == "code"
        assert remaining is None
```

## Fixtures

**Scope and Lifetime:**
- `function` (default): Reset between tests
- `module`: Reused within test module
- `session`: Reused across entire test session

**Key Fixtures from conftest.py:**

### Home Directory Isolation
```python
@pytest.fixture(scope="session", autouse=True)
def _isolate_home():
    """Ensure HOME points to a temp dir for entire test session."""
```
**Purpose:** Prevents tests from touching user's real `~/.mempalace` directory

### Temporary Directories
```python
@pytest.fixture
def tmp_dir():
    """Create and auto-cleanup a temporary directory."""
    d = tempfile.mkdtemp(prefix="mempalace_test_")
    yield d
    shutil.rmtree(d, ignore_errors=True)
```

### Palace and Collections
```python
@pytest.fixture
def palace_path(tmp_dir):
    """Path to an empty palace directory inside tmp_dir."""
    p = os.path.join(tmp_dir, "palace")
    os.makedirs(p)
    return p

@pytest.fixture
def collection(palace_path):
    """A ChromaDB collection pre-seeded in the temp palace."""
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    yield col
    client.delete_collection("mempalace_drawers")
```

### Pre-seeded Collections
```python
@pytest.fixture
def seeded_collection(collection):
    """Collection with representative test drawers."""
    collection.add(
        ids=[
            "drawer_proj_backend_aaa",
            "drawer_proj_backend_bbb",
            "drawer_proj_frontend_ccc",
        ],
        documents=["..."],
        metadatas=[{...}, {...}, {...}],
    )
    return collection
```

### Knowledge Graph
```python
@pytest.fixture
def kg(tmp_dir):
    """An isolated KnowledgeGraph using a temp SQLite file."""
    db_path = os.path.join(tmp_dir, "test_kg.sqlite3")
    return KnowledgeGraph(db_path=db_path)

@pytest.fixture
def seeded_kg(kg):
    """KnowledgeGraph pre-loaded with sample entities and triples."""
    kg.add_entity("Alice", entity_type="person")
    kg.add_triple("Alice", "parent_of", "Max", valid_from="2015-04-01")
    return kg
```

### MCP Cache Reset
```python
@pytest.fixture(autouse=True)
def _reset_mcp_cache():
    """Reset MCP server's cached ChromaDB client between tests."""
    def _clear_cache():
        try:
            from mempalace import mcp_server
            mcp_server._client_cache = None
            mcp_server._collection_cache = None
        except (ImportError, AttributeError):
            pass
    _clear_cache()
    yield
    _clear_cache()
```

### ES Integration Test Fixtures
```python
@pytest.fixture(scope="module")
def test_prefix():
    """Unique index prefix for this test run to avoid collisions."""
    return f"test_citadel_{uuid.uuid4().hex[:8]}_"

@pytest.fixture(scope="module")
def es_client():
    """Raw Elasticsearch client for setup/teardown."""
    from elasticsearch import Elasticsearch
    return Elasticsearch(
        hosts=os.environ["ES_URL"],
        api_key=os.environ["ES_KEY"],
        request_timeout=120,
    )
```

## Mocking

**Framework:** `unittest.mock` (standard library)

**Import Pattern:**
```python
from unittest.mock import patch, MagicMock
```

**Mocking Patterns:**

### Patching Functions
```python
def test_research_caches_result(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    mock_result = {
        "inferred_type": "person",
        "confidence": 0.80,
        "wiki_summary": "Saoirse is an Irish given name.",
    }
    with patch("mempalace.entity_registry._wikipedia_lookup", return_value=mock_result):
        result = registry.research("Saoirse", auto_confirm=True)
    assert result["inferred_type"] == "person"
```

### Patching Classes
```python
def test_layer1_no_palace():
    """Layer1 returns helpful message when no palace exists."""
    with patch("mempalace.layers.MempalaceConfig") as mock_cfg:
        mock_cfg.return_value.palace_path = "/nonexistent/palace"
        layer = Layer1(palace_path="/nonexistent/palace")
    result = layer.generate()
    assert "No palace found" in result
```

### Creating Mock Objects
```python
def _mock_chromadb_for_layer(docs, metas):
    """Return a mock PersistentClient whose collection.get returns docs/metas."""
    mock_col = MagicMock()
    mock_col.get.side_effect = [
        {"documents": docs, "metadatas": metas},
        {"documents": [], "metadatas": []},  # Second call returns empty
    ]
    mock_client = MagicMock()
    mock_client.get_collection.return_value = mock_col
    return mock_client
```

**What to Mock:**
- External APIs (Wikipedia lookups, Elasticsearch if not integration testing)
- Filesystem operations (in unit tests)
- Expensive computations (during unit tests)

**What NOT to Mock:**
- Core business logic (test real implementation)
- Data structures (test actual collections, dicts)
- Integration layers (when writing integration tests)

## Test Data

**Fixtures vs Factories:**
- Fixtures used for shared setup (see above)
- Inline test data used for simple tests (no factory pattern)

**Example: Simple Inline Data**
```python
def test_seed_registers_people(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[
            {"name": "Riley", "relationship": "daughter", "context": "personal"},
            {"name": "Devon", "relationship": "friend", "context": "personal"},
        ],
        projects=["MemPalace"],
    )
    assert "Riley" in registry.people
    assert registry.people["Riley"]["relationship"] == "daughter"
```

## Integration Testing

**ES Integration Tests:**
- File: `tests/test_es_integration.py`
- Requires environment variables: `ES_URL`, `ES_KEY`
- Skipped if not set: `pytestmark = pytest.mark.skipif(...)`
- Module-scoped fixtures create unique test indices
- Cleanup: All test indices deleted after test run

**Skip Condition:**
```python
pytestmark = pytest.mark.skipif(
    not os.environ.get("ES_URL") or not os.environ.get("ES_KEY"),
    reason="ES_URL and ES_KEY not set — skipping ES integration tests",
)
```

## Test Coverage Gaps

**Patterns Observed:**
- Unit tests heavily focus on individual functions (pure functions)
- Integration tests cover end-to-end flows (mining → search → retrieval)
- Error paths covered: `test_*_error`, `test_*_failure` patterns
- Edge cases covered: empty inputs, missing files, malformed data

**Example Coverage Pattern:**
```python
# From test_entity_registry.py
# Edge case: empty names are skipped
def test_seed_skips_empty_names(tmp_path):
    registry = EntityRegistry.load(config_dir=tmp_path)
    registry.seed(
        mode="personal",
        people=[{"name": "", "relationship": "", "context": "personal"}],
        projects=[],
    )
    assert len(registry.people) == 0
```

## Common Test Helpers

**File Writing Helper:**
```python
def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
```

**File Scanning Helper:**
```python
def scanned_files(project_root: Path, **kwargs):
    files = scan_project(str(project_root), **kwargs)
    return sorted(path.relative_to(project_root).as_posix() for path in files)
```

**ChromaDB Cleanup:**
```python
# From conftest.py
@pytest.fixture
def collection(palace_path):
    client = chromadb.PersistentClient(path=palace_path)
    col = client.get_or_create_collection("mempalace_drawers")
    yield col
    client.delete_collection("mempalace_drawers")  # Cleanup after test
    del client
```

## Running Specific Test Subsets

**By file:**
```bash
pytest tests/test_entity_registry.py
```

**By function name:**
```bash
pytest -k "test_lookup"
```

**By test class:**
```bash
pytest tests/test_es_integration.py::TestExtractWingFromWhere
```

**By marker:**
```bash
pytest -m "benchmark"  # Only benchmarks
pytest -m "not slow"   # Skip slow tests
```

**With coverage:**
```bash
pytest --cov=memcitadel --cov-report=term-missing tests/
```

---

*Testing analysis: 2026-04-10*
