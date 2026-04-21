# Codebase Structure

**Analysis Date:** 2026-04-10

## Directory Layout

```
memcitadle/
├── mempalace/                  # Main package
│   ├── __init__.py              # Entry point, version import
│   ├── __main__.py              # CLI entry (python -m mempalace)
│   ├── cli.py                   # Command-line interface (mine, init, search, etc.)
│   ├── config.py                # Configuration + sanitizers
│   ├── version.py               # Version string
│   ├── es_client.py             # Elasticsearch client + PalaceClient orchestrator
│   ├── palace.py                # Shared palace utilities
│   ├── miner.py                 # Project file mining (code, docs)
│   ├── convo_miner.py           # Conversation mining (Claude, ChatGPT, Slack)
│   ├── entity_detector.py       # Auto-detect entities from content
│   ├── entity_registry.py       # Entity resolution + DBpedia lookup
│   ├── searcher.py              # Hybrid search implementation
│   ├── layers.py                # 4-tier memory context system (wake-up)
│   ├── palace_graph.py          # Graph traversal (rooms, wings, tunnels)
│   ├── knowledge_graph.py       # Temporal entity-relationship store (SQLite)
│   ├── dialect.py               # AAAK compression dialect
│   ├── normalize.py             # Text normalization
│   ├── spellcheck.py            # Spell-checking utilities
│   ├── general_extractor.py     # Pattern-based extraction
│   ├── room_detector_local.py   # Auto-detect rooms from folder structure
│   ├── mcp_server.py            # MCP tool server for Claude Code
│   ├── migrate_to_es.py         # Migration script: ChromaDB → Elasticsearch
│   ├── migrate_flat_to_wings.py # Migration script: flat → per-wing indices
│   ├── split_mega_files.py      # Split concatenated conversation files
│   ├── onboarding.py            # Interactive setup wizard
│   ├── hooks_cli.py             # Git hooks for automatic mining
│   ├── instructions_cli.py      # Instruction management
│   └── instructions/            # LLM instruction templates
├── tests/                       # Test suite
│   ├── conftest.py              # Pytest fixtures (ES client, palace setup)
│   ├── test_miner.py            # Unit tests: file chunking, mining
│   ├── test_convo_miner_unit.py # Unit tests: conversation parsing
│   ├── test_searcher.py         # Unit tests: search queries
│   ├── test_layers.py           # Unit tests: memory layers
│   ├── test_entity_detector.py  # Unit tests: entity extraction
│   ├── test_knowledge_graph_extra.py  # Unit tests: KG operations
│   ├── test_mcp_server.py       # Unit tests: MCP tool implementations
│   ├── test_es_integration.py   # Integration tests: ES backend (skipped if ES_URL not set)
│   ├── benchmarks/              # Benchmark suite
│   │   └── test_benchmarks.py   # Scale/performance tests
│   └── [other test files]       # Dialect, entity registry, hooks, etc. tests
├── benchmarks/                  # Benchmark data and scripts
│   └── [performance test files]
├── examples/                    # Example usage scripts
├── hooks/                       # Git hook templates
├── bright/                      # BRIGHT benchmark data (biology Q&A)
│   ├── bright_data/             # Category-organized biology questions
│   └── bright_results/          # Benchmark results
├── .github/                     # GitHub Actions CI
│   └── workflows/               # Lint, test, ES integration workflows
├── .planning/                   # GSD planning output
│   └── codebase/                # This directory: STACK.md, ARCHITECTURE.md, etc.
├── .agents/                     # Claude AI plugin configuration
├── .claude-plugin/              # Claude IDE integration
├── .codex-plugin/               # Codex plugin config
├── pyproject.toml               # Package metadata, dependencies, build config
├── uv.lock                      # Dependency lockfile (UV package manager)
├── mempalace.yaml               # Wing/room topology definitions
├── entities.json                # Detected entities (auto-generated)
├── .pre-commit-config.yaml      # Git hooks config (ruff)
├── .gitignore                   # Git exclusions
├── README.md                    # Main documentation
├── CONTRIBUTING.md              # Contribution guidelines
├── LICENSE                      # MIT license
└── brief.md                     # Project brief
```

## Directory Purposes

**mempalace/ (Main Package):**
- Purpose: All source code for the library
- Contains: Miners, search, ES client, MCP server, utilities
- Key files: `es_client.py` (core), `cli.py` (entry), `mcp_server.py` (IDE integration)

**tests/ (Test Suite):**
- Purpose: Unit and integration tests
- Contains: pytest fixtures, test modules for each component
- Key files: `conftest.py` (fixtures), `test_es_integration.py` (ES backend tests)
- Markers: `benchmark`, `slow`, `stress` for test categorization

**benchmarks/ (Performance Benchmarks):**
- Purpose: Scale and performance testing
- Contains: Benchmark scripts and data
- Used for: Measuring RAG system throughput, latency at different scales

**examples/ (Usage Examples):**
- Purpose: Sample code showing how to use MemCitadel
- Contains: Mining examples, search examples, MCP integration examples

**bright/ (BRIGHT Benchmark):**
- Purpose: Biology Q&A dataset for evaluation
- Contains: Curated biology questions, answers, expected results
- Used for: Testing RAG quality on domain-specific Q&A

**.planning/codebase/ (Documentation):**
- Purpose: Architecture and structure documentation
- Contains: STACK.md, ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md
- Used by: GSD orchestrator for phase planning and execution

**.github/workflows/ (CI/CD):**
- Purpose: Automated testing and linting
- Contains: GitHub Actions workflow definitions
- Runs: Lint check, unit tests, ES integration tests (conditional)

## Key File Locations

**Entry Points:**
- `mempalace/__init__.py` — Package root, imports main CLI entry
- `mempalace/cli.py` — Command router for all subcommands
- `mempalace/__main__.py` — Python module execution entry (`python -m mempalace`)
- `mempalace/mcp_server.py` — MCP tool server for Claude Code integration

**Configuration:**
- `pyproject.toml` — Package metadata, dependencies, tool configs (ruff, pytest, coverage)
- `mempalace.yaml` — Wing/room topology definitions for mining
- `entities.json` — Detected entities (created by `mempalace init`)

**Core Logic:**
- `mempalace/es_client.py` — Elasticsearch backend (ESCollection, PalaceClient, hybrid search)
- `mempalace/miner.py` — Project file mining with chunking and room detection
- `mempalace/convo_miner.py` — Conversation mining with exchange-pair chunking
- `mempalace/searcher.py` — Search interface (hybrid BM25 + semantic)
- `mempalace/layers.py` — Memory context compression (wake-up system)
- `mempalace/knowledge_graph.py` — Temporal entity-relationship store

**Testing:**
- `tests/conftest.py` — Pytest fixtures for ES, palace, config isolation
- `tests/test_es_integration.py` — Full-stack integration tests (requires ES_URL, ES_KEY)
- `tests/test_miner.py` — File parsing, chunking, room detection tests
- `tests/test_searcher.py` — Search query and filtering tests

## Naming Conventions

**Files:**
- Module naming: `snake_case` (e.g., `es_client.py`, `palace_graph.py`)
- Test files: `test_*.py` or `*_test.py` prefix (e.g., `test_miner.py`)
- Config files: `*.yaml` or `*.json` (e.g., `mempalace.yaml`, `config.json`)
- Utility files: Clear names, no abbreviation (e.g., `entity_detector.py`, not `ent_det.py`)

**Directories:**
- Package: `mempalace/` (lowercase, no hyphens)
- Test suite: `tests/` (standard)
- Data: `bright/` (benchmark data), `benchmarks/` (scripts)
- Config: `.github/`, `.planning/`, root level for primary configs
- Internal: `.agents/`, `.claude-plugin/`, `.codex-plugin/`

**Classes:**
- PascalCase: `ESCollection`, `PalaceClient`, `KnowledgeGraph`, `Layer0`, `Layer1`
- Exceptions: PascalCase + `Error` suffix (e.g., `SearchError`)

**Functions & Methods:**
- snake_case: `search_memories()`, `mine_convos()`, `get_es_collection()`
- Private: `_leading_underscore()` (e.g., `_translate_where()`, `_extract_wing_from_where()`)
- Query/get: `query_*()` for search, `get_*()` for retrieval

**Variables:**
- Constants: `UPPER_CASE` (e.g., `CHUNK_SIZE`, `MAX_FILE_SIZE`, `READABLE_EXTENSIONS`)
- Module-level: `_snake_case` for private (e.g., `_CONTENT_FIELDS`, `_WAL_DIR`)

## Where to Add New Code

**New Feature (Search, Mining, etc.):**
- Primary code: `mempalace/{feature}.py` (new module at package root)
- Example: New search strategy → `mempalace/search_strategy.py`, call from `searcher.py`
- Tests: `tests/test_{feature}.py` (parallel to source)
- Integration: Wire into `cli.py` or `mcp_server.py` if user-facing

**New Component/Module:**
- Implementation: `mempalace/{component}.py` (snake_case filename)
- Class definition: `PascalCase` (e.g., `CustomAnalyzer`)
- Public interface: Export from `__init__.py` if meant for external use
- Internal utilities: Keep in module, prefix with `_` for private functions

**Utilities (Helpers, Common Functions):**
- Shared helpers: Add to `mempalace/palace.py` (existing utilities file)
- Or create new `mempalace/utils_{name}.py` if large
- Example: `SKIP_DIRS` in `palace.py` is shared between miners

**MCP Tools (New read/write operations):**
- Definition: `mempalace/mcp_server.py` — add new tool function
- Pattern: Implement `tool_name(params) → dict` returning MCP-formatted result
- WAL: Automatically logged by `_wal_log()` helper (for write operations)
- Example: `mempalace_add_drawer()` implements add via PalaceClient + WAL

**Tests:**
- Unit tests: `tests/test_{module}.py` (co-located with source naming)
- Integration: `tests/test_es_integration.py` (grouped ES integration tests)
- Fixtures: Add to `tests/conftest.py` (pytest auto-discovers)
- Markers: Use `@pytest.mark.benchmark`, `@pytest.mark.slow`, `@pytest.mark.stress` for categorization

## Special Directories

**mempalace/instructions/ (LLM Instructions):**
- Purpose: Prompt templates for instruction extraction
- Generated: Yes (templates, not user data)
- Committed: Yes (part of source code)
- Usage: Loaded by `instructions_cli.py` for interactive setup

**bright/ (BRIGHT Benchmark):**
- Purpose: Biology Q&A evaluation dataset
- Generated: No (curated data)
- Committed: Yes (part of repo)
- Size: ~10K biology questions with answers
- Usage: Run benchmarks with `pytest tests/test_benchmarks.py -m benchmark`

**.planning/codebase/ (This Directory):**
- Purpose: Architecture/structure documentation
- Generated: Yes (GSD mapper output)
- Committed: Yes (consumed by GSD planner/executor)
- Files: STACK.md, ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, CONCERNS.md

**.env Files:**
- Purpose: Environment variables for local development
- Generated: No (user creates)
- Committed: No (`.gitignore` blocks `.env*`)
- Location: Project root or `~/.mempalace/config.json` preferred

**.pytest_cache/ & .ruff_cache/:**
- Purpose: Cache for pytest and ruff (performance)
- Generated: Yes (automatic)
- Committed: No (`.gitignore` blocks)

**~/.mempalace/ (User Home Directory):**
- Purpose: Palace metadata and local databases
- Generated: Yes (by mempalace at runtime)
- Committed: No (outside repo)
- Contains:
  - `palace/` — Palace directory (ES replaces file storage)
  - `knowledge_graph.sqlite3` — Temporal KG database
  - `identity.txt` — Agent identity (user-editable)
  - `config.json` — Configuration (user-created)
  - `wal/write_log.jsonl` — Write-ahead logs (audit trail)

---

*Structure analysis: 2026-04-10*
