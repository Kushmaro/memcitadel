# Architecture

**Analysis Date:** 2026-04-10

## Pattern Overview

**Overall:** Enterprise-scale RAG with per-wing Elasticsearch indices + local knowledge graph

**Key Characteristics:**
- **Index-per-Wing** — Each project/team/agent gets its own Elasticsearch index for physical isolation
- **Hybrid Search** — BM25 (keyword) + semantic search combined via Reciprocal Rank Fusion (RRF)
- **Server-Side Embeddings** — No local ML model; ES Inference API generates vectors
- **Spatial Memory Model** — Wings/Rooms/Halls hierarchy from original MemPalace
- **Temporal Knowledge Graph** — SQLite local graph with time-valid entity relationships
- **Write-Ahead Logs** — JSONL audit trail for memory integrity verification

## Layers

**Presentation/MCP Layer:**
- Purpose: Expose 19 memory tools to Claude Code and LLM clients
- Location: `memcitadel/mcp_server.py`
- Contains: Tool implementations (read: search, status, list; write: add_drawer, delete_drawer)
- Depends on: Searcher, PalaceClient, knowledge graph
- Used by: Claude Code IDE via MCP protocol

**CLI Layer:**
- Purpose: Command-line interface for mining, searching, initialization
- Location: `memcitadel/cli.py`
- Contains: cmd_mine, cmd_init, cmd_search, cmd_wake_up, cmd_status, etc.
- Depends on: Miners, searcher, palace utilities
- Used by: Human operators, automation scripts

**Mining/Ingest Layer:**
- Purpose: Transform raw files/conversations into indexed drawers
- Location: `memcitadel/miner.py`, `memcitadel/convo_miner.py`, `memcitadel/entity_detector.py`
- Contains: File scanning, room detection, entity extraction, chunking
- Depends on: PalaceClient (ES), configuration
- Used by: CLI (mine command)
- Key modules:
  - `miner.py` — Project file mining (code, docs, notes)
  - `convo_miner.py` — Conversation export mining (Claude, ChatGPT, Slack)
  - `entity_detector.py` — Automatic person/project extraction from content

**Search/Query Layer:**
- Purpose: Retrieve content from memory palace
- Location: `memcitadel/searcher.py`
- Contains: Hybrid BM25 + semantic search, wing/room filtering, scoring
- Depends on: PalaceClient (ES queries)
- Used by: MCP tools, CLI search command, layers system

**Knowledge Graph Layer:**
- Purpose: Temporal entity-relationship triples with validity windows
- Location: `memcitadel/knowledge_graph.py`
- Contains: KG schema (entities, triples, temporal bounds), query/add/update operations
- Depends on: SQLite (local)
- Used by: MCP server (optional enrichment)
- Storage: `~/.mempalace/knowledge_graph.sqlite3`

**Memory Layers (Context Compression):**
- Purpose: 4-tier memory system for context-efficient wake-up
- Location: `memcitadel/layers.py`
- Contains:
  - Layer 0 (~100 tokens): Identity from `identity.txt`
  - Layer 1 (~500-800 tokens): Essential story (top drawers from ES)
  - Layer 2 (~200-500 each): On-demand topic context
  - Layer 3 (unlimited): Full semantic search
- Used by: Wake-up command, context injection for agents

**Elasticsearch Backend Layer:**
- Purpose: Orchestrate per-wing indices, hybrid search, CRUD operations
- Location: `memcitadel/es_client.py`
- Contains:
  - `ESCollection` — Single index operations (add, query, get, delete)
  - `PalaceClient` — Multi-index routing (intercepts wing metadata, dispatches to per-wing indices)
  - Wing mapping definition: `content_raw` (text), `content_semantic` (dense vectors), metadata fields
  - Structure index mapping: wing and room definitions
- Depends on: `elasticsearch` Python client
- Used by: All other layers

**Configuration Layer:**
- Purpose: Centralize env/file/defaults for all settings
- Location: `memcitadel/config.py`
- Contains: MempalaceConfig class, input sanitizers, validation
- Used by: All other modules

## Data Flow

**Ingest Flow (Mining):**
1. CLI invokes `cmd_mine` with directory path
2. `miner.py` scans files, respects `.gitignore` patterns, skips node_modules/venv/etc.
3. For each file: read → detect room via keywords or mempalace.yaml → chunk (800 chars, 100 char overlap)
4. For each chunk: create metadata (wing, room, hall, source_file, chunk_index, filed_at)
5. `PalaceClient.add()` routes by wing → individual `ESCollection` in `citadel_{citadel}_{wing}` index
6. ES processes `content_raw` as BM25, `content_semantic` via Inference API
7. Write-ahead log records operation to `~/.mempalace/wal/write_log.jsonl`

**Search Flow:**
1. User queries via CLI or MCP tool
2. `searcher.py` or MCP tool extracts query + optional wing/room filters
3. `PalaceClient.query()` converts filters to ES bool clauses
4. ES executes hybrid search:
   - BM25 on `content_raw` (lexical match)
   - Semantic on `content_semantic` (dense vector similarity)
   - RRF merges both rankings (no external combining logic)
5. Results returned as drawer chunks with metadata
6. MCP/CLI formats and returns to user

**Wake-Up Flow (Context Compression):**
1. `layers.py` Layer0 reads `identity.txt` (~100 tokens)
2. Layer1 fetches top N drawers from ES by score/recency (~500-800 tokens)
3. Optionally Layer2 loads on-demand context for specific wing/room
4. Total: 600-900 tokens of context ready for agent
5. Agent makes decisions; full Layer3 search available if needed

**State Management:**
- **Drawer State:** Elasticsearch indices (persistent, immutable content)
- **Metadata State:** Structure index + drawer metadata fields (searchable, appendable)
- **KG State:** SQLite local database (temporal, queryable)
- **Config State:** Environment + `~/.mempalace/config.json` (singleton, read at startup)
- **Session State:** PalaceClient wing collection cache (in-memory, ephemeral)

## Key Abstractions

**Wing:**
- Purpose: Top-level isolation unit (project, team, person, agent)
- Examples: `engineering`, `product`, `atlas` (agent diary)
- Pattern: Each wing → one ES index → one namespace
- Used for: Physical isolation, per-wing ILM policies, scoped API keys

**Room:**
- Purpose: Topic or domain within a wing
- Examples: `auth`, `billing`, `infrastructure`, `decisions`
- Pattern: Auto-detected from folder structure or explicitly named in `mempalace.yaml`
- Used for: Hierarchical search filtering, organization

**Drawer:**
- Purpose: Single verbatim text chunk (never summarized)
- Pattern: One ES document with ID, content_raw, metadata
- Lifecycle: Immutable once filed (can only delete)
- Used for: Exact retrieval, trustworthy memories

**Hall:**
- Purpose: Memory type category (corridor within wing)
- Values: `hall_facts`, `hall_events`, `hall_discoveries`, `hall_preferences`, `hall_advice`
- Pattern: Metadata field, optional, for semantic memory organization
- Used for: Classification during mining, optional filtering

**Tunnel:**
- Purpose: Cross-wing connection when same room name appears in multiple wings
- Example: `auth` room in both Engineering and Product wings → tunnel link
- Pattern: Computed from graph traversal (not pre-indexed)
- Used for: Org chart navigation, graph queries

**Citadel:**
- Purpose: Namespace for all indices in a multi-tenant scenario
- Pattern: `citadel_{citadel}_{wing}` naming convention
- Default: `citadel_default_*`
- Used for: Multi-org isolation at Elasticsearch level

**Knowledge Graph Entity:**
- Purpose: Named entity with temporal history
- Example: Person (Alice), project (MemPalace), concept (Byzantine Agreement)
- Pattern: Stored in SQLite `entities` table, linked to triples
- Used for: Relationship queries, time-based filtering

## Entry Points

**CLI Entry:**
- Location: `memcitadel.cli:main`
- Triggers: `memcitadel` command (from `pyproject.toml` scripts)
- Responsibilities:
  - Route subcommand (mine, init, search, wake-up, status, mcp, hooks, instructions)
  - Parse args, load config
  - Invoke appropriate module (miners, searcher, layers, etc.)

**MCP Server Entry:**
- Location: `memcitadel.mcp_server`
- Triggers: `python -m memcitadel.mcp_server` (installed as MCP tool)
- Responsibilities:
  - Listen for JSON-RPC calls on stdio
  - Implement 19 tools (read/write)
  - Log all writes to WAL before execution
  - Return results in MCP format

**Programmatic Entry:**
- Location: `memcitadel.palace:get_collection()`
- Used by: Tests, external integrations
- Returns: PalaceClient singleton (if ES configured)

## Error Handling

**Strategy:** Graceful degradation with clear error messages

**Patterns:**
- Config errors (missing ES_URL) → Early exit with setup instructions
- ES connectivity errors (network, auth) → Caught as `NotFoundError`, retry with backoff or fail with message
- Validation errors (name sanitization) → ValueError with field-specific guidance
- Missing palace → Return empty results (no index created until first mining)
- Oversized content (>100K chars) → Reject with size limit message

**Examples:**
- `searcher.py:SearchError` — Raised when no palace found or search fails
- `config.py:ValueError` — Sanitization checks (path traversal, null bytes, length)
- `es_client.py` — Catch `NotFoundError` for missing indices, ignore_unavailable=True for optional operations

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module
- Loggers: Per-module (`mempalace_es`, `mempalace_mcp`, etc.)
- Levels: INFO (default), WARNING (suppressed for elastic_transport)
- Destinations: stderr (captured by MCP client or terminal)

**Validation:**
- Approach: Input sanitization via `sanitize_name()`, `sanitize_content()` in config.py
- Scope: Wing/room names (max 128 chars, alphanumeric + limited punctuation)
- Content: Max 100K chars per drawer
- Pattern: Raises ValueError with clear reason before processing

**Authentication:**
- Approach: ES API key in header (elasticsearch client handles)
- Scope: All ES operations (query, index, delete)
- Fallback: No fallback; operation fails if auth fails

**Namespacing:**
- Wing isolation: One index per wing → queries naturally scoped
- Citadel isolation: Prefix all indices with `citadel_{citadel}_` → multi-tenant safe
- ID uniqueness: Content-based hashing (SHA256) ensures same content → same ID globally

---

*Architecture analysis: 2026-04-10*
