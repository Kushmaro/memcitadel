# Technology Stack

**Analysis Date:** 2026-04-10

## Languages

**Primary:**
- Python 3.9+ — Core application language, all business logic and ingest pipelines

**Secondary:**
- YAML — Configuration files (`mempalace.yaml`), memory palace topology definitions
- JSON — Entity metadata, configuration serialization, knowledge graph exports

## Runtime

**Environment:**
- Python 3.9, 3.10, 3.11, 3.12 — Full support specified in `pyproject.toml`

**Package Manager:**
- UV (Rust-based pip replacement) — Lockfile: `uv.lock` present
- PEP 517 build system: Hatchling

## Frameworks & Core Dependencies

**Backend:**
- `elasticsearch>=9.0` — Elasticsearch Serverless backend, primary storage
  - Replaces ChromaDB from original MemPalace
  - Used for hybrid BM25 + semantic search via RRF (Reciprocal Rank Fusion)
  - Server-side embeddings via Elasticsearch Inference API

**Configuration:**
- `pyyaml>=6.0,<7` — YAML parsing for `mempalace.yaml` topology files

**Testing:**
- `pytest>=7.0` — Test runner
- `pytest-cov>=4.0` — Code coverage measurement
- `chromadb` — Legacy testing support (backward compatibility in test fixtures)

**Code Quality:**
- `ruff>=0.4.0` — Linter and formatter
  - Config: `pyproject.toml` with line-length=100
  - Rules: E, F, W (errors, pyflakes, warnings)
  - Ignores: E501 (line-too-long, handled by formatter)
- `pre-commit` — Git hooks (ruff-pre-commit v0.9.0)
  - Hooks: ruff check + ruff format on commit

**Development:**
- `psutil>=5.9` — System monitoring for benchmark/resource tests

**Optional:**
- `autocorrect>=2.0` — Spell-checking for memory content (spellcheck extra)

## Key Dependencies

**Critical:**
- `elasticsearch>=9.0` — Elasticsearch Python client, handles all ES queries
  - Supports ES Serverless and self-hosted 9.x deployments
  - Used in `es_client.py` for CRUD, hybrid search, aggregations
  - Provides `Elasticsearch` and `NotFoundError` exceptions

**Data/Storage:**
- SQLite 3 (stdlib) — Local knowledge graph storage
  - Path: `~/.mempalace/knowledge_graph.sqlite3`
  - Schema: entities, triples, temporal validity tables
  - No external dependency required

**Utilities:**
- `pathlib` (stdlib) — Path manipulation for cross-platform file handling
- `hashlib` (stdlib) — Document ID generation, content hashing
- `json` (stdlib) — Data serialization
- `sqlite3` (stdlib) — Knowledge graph persistence

## Configuration

**Environment Variables (Priority 1):**
```
ES_URL          — Elasticsearch deployment URL (e.g., https://deployment.es.cloud.elastic.co)
ES_KEY          — Elasticsearch API key for authentication
MEMPALACE_PALACE_PATH  — Override default palace location (~/.mempalace/palace)
MEMPALACE_CITADEL      — Citadel name for multi-tenant scenarios (default: "default")
MEMPALACE_ES_INFERENCE_ID  — Inference endpoint for semantic embeddings
```

**Config File (Priority 2):**
- Location: `~/.mempalace/config.json`
- Format: JSON with keys matching env var names (snake_case)
- Example:
  ```json
  {
    "es_url": "https://deployment.es.cloud.elastic.co",
    "es_api_key": "your-api-key",
    "es_inference_id": ".multilingual-e5-small-elasticsearch"
  }
  ```

**Build Configuration:**
- `pyproject.toml` — Poetry/PEP 517 metadata and tool configs
  - Build backend: hatchling
  - Test markers: `benchmark`, `slow`, `stress`
  - Coverage threshold: 85% (fail_under)

## Platform Requirements

**Development:**
- Python 3.9+ (local)
- Elasticsearch deployment (Elastic Cloud or self-hosted 9.x)
- ES API key with permissions: `index:management`, `data:write`, `data:read`
- Git (for pre-commit hooks)
- UV package manager (optional but recommended)

**Production:**
- Python 3.9+ runtime
- Elasticsearch Serverless or self-hosted ES 9.x
- Network access to ES cluster (HTTPS)
- Storage: `~/.mempalace/` directory (~10-50GB depending on palace size)
  - `palace/` — Index metadata (ES stores actual content)
  - `knowledge_graph.sqlite3` — Local KG database
  - `wal/` — Write-ahead logs for MCP operations
  - `identity.txt` — Agent identity definition
  - `config.json` — Configuration

**MCP Server Integration:**
- MCP (Model Context Protocol) compatible with Claude Code
- Installation: `claude mcp add memcitadel -- python -m mempalace.mcp_server`
- Runs as subprocess, communicates via stdio

## Entry Points

**CLI:**
- Command: `memcitadel` (from `pyproject.toml` scripts)
- Module: `mempalace.cli:main`
- Supports: mine, init, search, wake-up, status, mcp, hooks, instructions commands

**MCP Server:**
- Module: `mempalace.mcp_server`
- Provides 19 tools for read/write palace access
- Compatible with Claude and other LLM MCP clients

## Special Notes

**Elasticsearch-Specific:**
- Semantic text embeddings generated server-side (Inference API)
- Default inference endpoint: `.multilingual-e5-small-elasticsearch`
- RRF (Reciprocal Rank Fusion) merges BM25 + semantic scoring without local model loading
- Index-per-wing architecture: `citadel_{citadel}_{wing}` for physical isolation
- Structure index: `citadel_{citadel}_structure` for metadata

**No Local ML Dependencies:**
- Unlike MemPalace (which uses all-MiniLM-L6-v2), MemCitadel relies entirely on ES server-side embeddings
- Reduces Python dependencies and eliminates model download overhead

---

*Stack analysis: 2026-04-10*
