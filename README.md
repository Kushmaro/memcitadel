<div align="center">

# MemCitadel

### What if your AI's memory could scale to millions of documents?

<br>

Imagine MemPalace — the elegant Wings/Rooms/Halls architecture for AI memory — but without the ceiling. No local ChromaDB limits. No single-machine bottleneck. Every conversation, every decision, every document your organization has ever produced, searchable in milliseconds with hybrid BM25 + semantic retrieval. Per-team isolation. Per-project retention policies. Enterprise security.

**That's MemCitadel.** A fork of [MemPalace](https://github.com/milla-jovovich/mempalace) rebuilt on Elasticsearch Serverless. Same spatial memory model. Infinite scale.

<br>

</div>

---

## What Is This?

MemCitadel is an enterprise-scale RAG system that gives AI agents persistent, structured memory backed by Elasticsearch Serverless. It takes MemPalace's "Memory Palace" architecture — where information is organized into **wings** (projects, teams, people), **rooms** (topics), and **drawers** (verbatim content) — and runs it on infrastructure built for millions of documents.

**What changed from MemPalace:**

| | MemPalace | MemCitadel |
|--|-----------|------------|
| **Storage** | ChromaDB (local files) | Elasticsearch Serverless (cloud) |
| **Search** | Vector similarity only | Hybrid: BM25 + semantic via RRF |
| **Embeddings** | Local model (all-MiniLM-L6-v2) | ES Inference API (server-side) |
| **Architecture** | Single flat collection | Index-per-wing (physical isolation) |
| **Scale** | Thousands of drawers | Millions+ |
| **Isolation** | None | Per-wing indices, per-wing ILM |
| **MCP Tools** | 19 tools | Same 19 tools, same interface |

**What stayed the same:** The Memory Palace spatial model, the MCP server interface, AAAK compression dialect, the knowledge graph, agent diaries, and every tool that agents already use. An agent that works with MemPalace works with MemCitadel without changes.

---

## Architecture

```
mempalace_structure              metadata index (wing/room definitions)
mempalace_wing_engineering       drawers for the engineering wing
mempalace_wing_product           drawers for the product wing
mempalace_wing_atlas             drawers for agent "atlas" (diary, observations)
mempalace_wing_*                 wildcard for cross-wing operations
```

### Index-Per-Wing

Every wing gets its own Elasticsearch index. This is the core architectural decision:

- **Physical isolation** — one wing's heavy indexing doesn't impact another's search latency
- **Per-wing ILM** — archive old projects to warm/cold storage, keep active wings hot
- **Per-wing security** — scope API keys to specific wings for tenant isolation
- **Faster queries** — searching within a wing hits only that wing's shards, not the entire dataset

Cross-wing operations (status, taxonomy, palace graph traversal) use the `mempalace_wing_*` wildcard pattern. These are admin/analytics operations — the hot path is always wing-scoped.

### Hybrid Search

Every search combines two retrieval strategies via Reciprocal Rank Fusion (RRF):

1. **BM25** on `content_raw` — lexical matching, exact terms, keyword recall
2. **Semantic search** on `content_semantic` — conceptual similarity via dense vectors

The `content_semantic` field uses Elasticsearch's `semantic_text` type with the Inference API. Embeddings are generated server-side — no local model, no Python ML dependencies.

Wing and room filters are injected into both retrievers as `bool.filter` clauses, ensuring strict logical isolation without affecting scoring.

### Structure Index

A lightweight metadata index (`mempalace_structure`) stores wing and room definitions:

```json
{"_id": "wing:engineering", "type": "wing", "name": "engineering", "created_at": "..."}
{"_id": "room:engineering:auth", "type": "room", "wing": "engineering", "name": "auth"}
```

Taxonomy and status queries use ES aggregations — no full-scan counting in Python.

---

## The Memory Palace

The spatial model is inherited from MemPalace. Information is organized like a building:

```
  WING: Engineering                          WING: Product
  ┌────────────────────────────┐             ┌────────────────────────────┐
  │                            │             │                            │
  │  ┌────────┐  ──hall──  ┌────────┐        │  ┌────────┐  ──hall──  ┌────────┐
  │  │  auth  │            │  infra │        │  │  auth  │            │ pricing│
  │  └───┬────┘            └────────┘        │  └───┬────┘            └────────┘
  │      │                                   │      │
  │      ▼                                   │      ▼
  │  ┌────────┐    ┌────────┐                │  ┌────────┐    ┌────────┐
  │  │ Closet │──▶ │ Drawer │                │  │ Closet │──▶ │ Drawer │
  │  └────────┘    └────────┘                │  └────────┘    └────────┘
  └──────┼─────────────────────┘             └──────┼─────────────────────┘
         │                                          │
         └──────────── tunnel ─────────────────────┘
              (same room "auth" in both wings)
```

**Wings** — top-level isolation units. A project, a team, a person, an agent. Each wing is its own ES index.

**Rooms** — topics within a wing. `auth`, `billing`, `infrastructure`, `decisions`. Auto-detected from your file structure during mining.

**Halls** — corridors connecting rooms within a wing. Memory types: `hall_facts`, `hall_events`, `hall_discoveries`, `hall_preferences`, `hall_advice`.

**Tunnels** — cross-wing connections. When the same room name appears in multiple wings (e.g., "auth" in both Engineering and Product), a tunnel links them. Enables graph traversal across domains.

**Drawers** — the actual content. Verbatim text, never summarized. Each drawer is one ES document with full metadata.

---

## Quick Start

### Prerequisites

- Python 3.9+
- An Elasticsearch Serverless deployment ([create one](https://cloud.elastic.co/))
- An ES API key with index permissions

### Install

```bash
pip install memcitadel
```

### Configure

Set your Elasticsearch connection:

```bash
export ES_URL="https://your-deployment.es.cloud.elastic.co"
export ES_KEY="your-api-key"
```

Or add to `~/.mempalace/config.json`:

```json
{
  "es_url": "https://your-deployment.es.cloud.elastic.co",
  "es_api_key": "your-api-key"
}
```

### Mine your data

```bash
# Initialize a project
memcitadel init ~/projects/myapp

# Mine project files into the palace
memcitadel mine ~/projects/myapp

# Mine conversations (Claude, ChatGPT, Slack exports)
memcitadel mine ~/chats/ --mode convos

# Search
memcitadel search "why did we switch to GraphQL"

# Status
memcitadel status
```

### Connect to your AI

```bash
# MCP server for Claude, ChatGPT, Cursor, Gemini
claude mcp add memcitadel -- python -m memcitadel.mcp_server
```

Your AI now has 19 MCP tools to navigate the palace. Ask it anything:

> *"What did we decide about auth last month?"*

The AI calls `mempalace_search`, gets verbatim results from the right wing, and answers.

---

## MCP Tools

### Palace (read)

| Tool | What |
|------|------|
| `mempalace_status` | Palace overview + AAAK spec + memory protocol |
| `mempalace_list_wings` | Wings with drawer counts |
| `mempalace_list_rooms` | Rooms within a wing |
| `mempalace_get_taxonomy` | Full wing → room → count tree |
| `mempalace_search` | Hybrid BM25 + semantic search with wing/room filters |
| `mempalace_check_duplicate` | Check before filing (semantic similarity) |
| `mempalace_get_aaak_spec` | AAAK dialect reference |

### Palace (write)

| Tool | What |
|------|------|
| `mempalace_add_drawer` | File verbatim content into a wing/room |
| `mempalace_delete_drawer` | Remove a drawer by ID |

### Knowledge Graph

| Tool | What |
|------|------|
| `mempalace_kg_query` | Entity relationships with temporal filtering |
| `mempalace_kg_add` | Add facts with validity windows |
| `mempalace_kg_invalidate` | Mark facts as ended |
| `mempalace_kg_timeline` | Chronological entity story |
| `mempalace_kg_stats` | Graph overview |

### Navigation

| Tool | What |
|------|------|
| `mempalace_traverse` | Walk the palace graph from a room across wings |
| `mempalace_find_tunnels` | Find rooms bridging two wings |
| `mempalace_graph_stats` | Graph connectivity overview |

### Agent Diary

| Tool | What |
|------|------|
| `mempalace_diary_write` | Write session observations in AAAK |
| `mempalace_diary_read` | Read recent diary entries |

---

## Knowledge Graph

Temporal entity-relationship triples stored in SQLite (local). Facts have validity windows — when something stops being true, invalidate it.

```python
from memcitadel.knowledge_graph import KnowledgeGraph

kg = KnowledgeGraph()
kg.add_triple("Maya", "assigned_to", "auth-migration", valid_from="2026-01-15")
kg.add_triple("Maya", "completed", "auth-migration", valid_from="2026-02-01")

kg.query_entity("Maya", as_of="2026-01-20")
# → [Maya → assigned_to → auth-migration (active)]

kg.invalidate("Kai", "works_on", "Orion", ended="2026-03-01")
# Historical queries still find it. Current queries don't.
```

---

## AAAK Dialect

AAAK is a lossy abbreviation system for packing repeated entities into fewer tokens. Readable by any LLM without a decoder.

```
FAM: ALC→JOR | 2D(kids): RIL(18,sports) MAX(11,chess+swimming) | BEN(contributor)
```

Agents learn the AAAK spec automatically from the `mempalace_status` response. Diary entries are written in AAAK for compression. The storage layer keeps raw verbatim text — AAAK is a context-loading optimization, not the storage format.

---

## The Memory Stack

| Layer | What | Size | When |
|-------|------|------|------|
| **L0** | Identity — who is this AI? | ~50 tokens | Always loaded |
| **L1** | Critical facts — team, projects, preferences | ~120 tokens | Always loaded |
| **L2** | Room recall — filtered by wing/room | On demand | When topic comes up |
| **L3** | Deep search — hybrid BM25 + semantic across the palace | On demand | When explicitly asked |

Wake-up cost: ~170 tokens for L0 + L1. The rest of the context window stays free.

---

## How It Differs from MemPalace

MemPalace is designed as a local-first personal memory tool. MemCitadel takes the same concepts and rebuilds the data layer for production:

- **ChromaDB → Elasticsearch Serverless**: From a local embedded database to a managed cloud service built for scale. Hybrid search (BM25 + semantic) instead of vector-only.
- **Single collection → Index-per-wing**: Physical isolation between wings. Independent scaling, ILM, and security per wing.
- **Local embeddings → ES Inference API**: No local ML model. Embeddings generated server-side. Swap models by changing the inference endpoint, not the code.
- **Python counting → ES aggregations**: Status and taxonomy queries use native ES aggregations instead of pulling all metadata into Python.

The MCP tool interface is identical. Agents don't know or care which backend is running.

---

## Credits

MemCitadel is a fork of [MemPalace](https://github.com/milla-jovovich/mempalace) by Milla Jovovich and Ben Sigman. The Memory Palace architecture, AAAK dialect, knowledge graph, and MCP tool design are their work. MemCitadel replaces the storage backend and adds enterprise-scale infrastructure.

## License

MIT
