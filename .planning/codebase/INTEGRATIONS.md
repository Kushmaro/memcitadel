# External Integrations

**Analysis Date:** 2026-04-10

## APIs & External Services

**Elasticsearch:**
- **Service:** Elasticsearch Serverless (or self-hosted 9.x)
- **What it's used for:** Document storage, BM25 indexing, semantic search via server-side embeddings, aggregations for taxonomy queries
- **SDK/Client:** `elasticsearch>=9.0` Python client
- **Auth:** API key authentication (environment: `ES_KEY`, config: `es_api_key`)
- **Connection:** URL (environment: `ES_URL`, config: `es_url`)
- **Inference API:** Server-side embeddings endpoint (default: `.multilingual-e5-small-elasticsearch`)

**Model Context Protocol (MCP):**
- **Service:** MCP standard for LLM tool provision
- **What it's used for:** Expose 19 memory tools to Claude Code and other MCP-compatible clients
- **Implementation:** `memcitadel.mcp_server` module
- **Integration:** Tool discovery and JSON-RPC communication over stdio
- **Tools:** read (search, status, list, get_taxonomy) and write (add_drawer, delete_drawer) operations

## Data Storage

**Elasticsearch Indices:**
- **Primary:** Multi-index per-wing architecture
  - `citadel_{citadel}_{wing}` — One index per wing, holds all drawers (content chunks) for that wing
  - Mapping: BM25-indexed `content_raw`, semantic-indexed `content_semantic`, metadata fields (wing, room, hall, source_file, filed_at, added_by, etc.)
  - Connection: Retrieved via environment or config file
  - Client: `elasticsearch.Elasticsearch` with API key

**Metadata Index:**
- `citadel_{citadel}_structure` — Lightweight metadata index for wing/room definitions
  - Documents: `{"_id": "wing:name", "type": "wing", ...}` or `{"_id": "room:wing:name", "type": "room", ...}`
  - Used for: Taxonomy queries, cross-wing operations via wildcard pattern matching

**Cross-wing Queries:**
- Pattern: `citadel_{citadel}_*` (wildcard) for multi-wing aggregations

**Local SQLite:**
- **Database:** `~/.mempalace/knowledge_graph.sqlite3`
- **Purpose:** Temporal knowledge graph — entity triples with time validity
- **Tables:** entities, triples, temporal bounds
- **Client:** Python `sqlite3` (stdlib)
- **No external service** — fully local

**File Storage:**
- **Approach:** Local filesystem only for palace metadata
- **Paths:**
  - `~/.mempalace/palace/` — Palace directory (deprecated; ES replaces file-based storage)
  - `~/.mempalace/identity.txt` — Agent identity definition (plain text)
  - `~/.mempalace/knowledge_graph.sqlite3` — KG database
  - `~/.mempalace/wal/write_log.jsonl` — Write-ahead logs (audit trail)
  - `~/.mempalace/config.json` — Configuration (optional; env vars take precedence)

**Caching:**
- **Approach:** No external caching service
- **In-memory:** Python dict caches in PalaceClient (wing collections)
- **No Redis/Memcached** — ES replaces need for separate cache layer

## Authentication & Identity

**Auth Provider:**
- **Approach:** Custom (ES API key authentication)
- **Implementation:** Bearer token in HTTP Authorization header sent to ES
- **Configuration:**
  - Env var: `ES_KEY`
  - Config file: `es_api_key` in `~/.mempalace/config.json`
  - Priority: Env vars override config file

**No OAuth/SAML:**
- Internal tool (Claude Code integration)
- No user login system
- Per-team isolation via per-wing ES indices (scoped API keys if needed)

## Monitoring & Observability

**Error Tracking:**
- **Approach:** None configured
- **Logging:** Python `logging` module to stderr
  - Logger: `mempalace_es`, `mempalace_mcp`, `memcitadel`
  - Suppresses noisy: `elastic_transport` logger set to WARNING

**Logs:**
- **Destination:** stdout/stderr (captured by MCP client or CLI host)
- **Approach:** Structured logging with metadata (wing, room, operation)
- **Write-Ahead Logs:** JSONL audit trail in `~/.mempalace/wal/write_log.jsonl`
  - Records: operation name, parameters, timestamp, result
  - Used for: Detecting memory poisoning, rollback analysis

**No External Observability:**
- No DataDog, New Relic, or Sentry integration
- No distributed tracing

## CI/CD & Deployment

**Hosting:**
- **Deployment Target:** Local/cloud anywhere Python 3.9+ and ES access available
- **No cloud provider lock-in** — compatible with Elastic Cloud, AWS Elasticsearch, self-hosted
- **Installation:** `pip install memcitadel` or editable `pip install -e .`

**CI Pipeline:**
- **Service:** GitHub Actions (configured in `.github/`)
- **Workflows:**
  - Lint: Ruff format + check
  - Test: pytest with coverage
  - ES integration tests: Conditional on ES_URL/ES_KEY env vars

**Build:**
- **Backend:** Hatchling (PEP 517)
- **Distribution:** PyPI (membrane can be installed as `pip install memcitadel`)

## Environment Configuration

**Required Environment Variables:**
- `ES_URL` — Elasticsearch deployment URL (for ES integration tests; optional if using config file)
- `ES_KEY` — Elasticsearch API key (for ES integration tests; optional if using config file)

**Optional Environment Variables:**
- `MEMPALACE_PALACE_PATH` — Override default palace location (default: `~/.mempalace/palace`)
- `MEMPALACE_CITADEL` — Citadel name (default: `default`)
- `MEMPALACE_ES_INFERENCE_ID` — Inference endpoint ID (default: `.multilingual-e5-small-elasticsearch`)

**Secrets Location:**
- Primary: Environment variables (safest for CI/CD)
- Secondary: `~/.mempalace/config.json` (local development)
- Never: Committed to git (`.gitignore` blocks `.env`, credentials, `config.json`)

**Configuration File Location:**
- `~/.mempalace/config.json` — JSON-formatted config (optional; env vars take precedence)

## Webhooks & Callbacks

**Incoming:**
- **MCP Server:** Listens on stdio for JSON-RPC requests from MCP client (Claude Code)
- **No HTTP webhooks** — stateless tool calls only

**Outgoing:**
- **Write-Ahead Log:** One-way audit trail to `~/.mempalace/wal/write_log.jsonl`
- **No callbacks to external services**

## Service Integrations Summary

| Service | Purpose | Auth | Required |
|---------|---------|------|----------|
| Elasticsearch | Primary storage + hybrid search | API key | Yes |
| MCP (Model Context Protocol) | Tool exposure to Claude | None | Optional (for IDE use) |
| GitHub Actions | CI/lint/test | Repo token | Optional (dev) |

**No integrations with:**
- Payment systems (Stripe, etc.)
- Notification services (Slack webhooks, email)
- Cloud storage (S3, GCS)
- User auth providers (Auth0, Firebase)
- Analytics platforms

---

*Integration audit: 2026-04-10*
