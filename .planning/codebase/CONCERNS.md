# Codebase Concerns

**Analysis Date:** 2026-04-10

## Tech Debt

**AAAK Embedding Quality Degradation:**
- Issue: Compressed AAAK dialect is stored and embedded as-is, reducing semantic search quality. The dialect uses codes and abbreviations (e.g., `ALC=Alice, PROJ: projects`) that degrade embedding vectors compared to expanded natural language.
- Files: `mempalace/mcp_server.py` (lines 495-498), `mempalace/dialect.py`
- Impact: Diary search and cross-wing traversal may miss relevant memories due to poor embeddings on compressed text
- Fix approach: Expand AAAK to natural language before embedding (pre-embedding expansion), then store both raw AAAK (metadata) and expanded version (content_semantic). Document notes this is deferred to "future versions."

**Hard-coded Pagination Limit (10000):**
- Issue: Multiple read operations use `limit=10000` as a maximum retrieval size, assuming all data fits in memory. This is a soft ceiling that breaks silently if a palace exceeds 10k items.
- Files: `mempalace/mcp_server.py` (lines 182, 200-201, 221, 541), `mempalace/es_client.py` (lines 254, 416), `mempalace/miner.py`
- Impact: Palace statistics, wing/room enumeration, and aggregations will be incomplete if wing has more than 10k drawers. No error raised — just truncated results.
- Fix approach: Implement proper cursor-based pagination with offset, or make limit configurable per operation. For MCP server status calls, use ES aggregations instead of fetching all docs.

**Bare Exception Handlers:**
- Issue: 63+ instances of `except Exception` or bare `except` with `pass`, swallowing all errors including transient failures, bugs, and connection timeouts
- Files: `mempalace/miner.py`, `mempalace/config.py`, `mempalace/searcher.py`, `mempalace/onboarding.py`, `mempalace/spellcheck.py`, `mempalace/cli.py`, `mempalace/mcp_server.py` (127-128), `mempalace/migrate_to_es.py`
- Impact: Failures silently degrade (bad gitignore handling, missing mtime, config load failures). Debugging is hard. Silent failures in WAL logging (line 95-96) could hide write-ahead log corruption.
- Fix approach: Catch specific exceptions (ValueError, OSError, NotFoundError). Log all catches. For production code (mcp_server, es_client), escalate failures to caller instead of silently passing.

**Bare pass Statements in Error Paths:**
- Issue: File permission changes in `mcp_server.py` (lines 73-76, 92-94) catch OSError and NotImplementedError but silently pass, hiding permission setup failures on Windows or restricted filesystems
- Files: `mempalace/mcp_server.py` (lines 73-76, 92-94), `mempalace/config.py`
- Impact: WAL file may not have correct permissions on some systems, creating security/consistency issues. No indication to operator that permissions failed.
- Fix approach: Log warnings when permission changes fail. For security-critical paths like WAL, raise an error or use platform-specific fallbacks.

## Known Bugs

**MCP Tool Result Format Inconsistency:**
- Symptoms: Some tools return errors as `{"error": "..."}` while others return `{"success": False, "error": "..."}`. Clients must check both formats.
- Files: `mempalace/mcp_server.py` - tool_check_duplicate (274-275), tool_add_drawer (319, 365), tool_delete_drawer (375, 394), tool_kg_add (415), vs. _no_palace (105-108), tool_search (returns SearchError exception)
- Trigger: Call different MCP tools and examine response structure. Some wrap errors in success field, others use bare error keys.
- Workaround: Always check both `{"success": False}` and bare `{"error": ...}` patterns when handling tool responses.

**Incomplete Taxonomy Fallback on Error:**
- Symptoms: tool_status() catches all exceptions on taxonomy generation (line 127-128) and silently returns empty `wings: {}` and `rooms: {}`. Caller can't distinguish "no data" from "error retrieving data".
- Files: `mempalace/mcp_server.py` (lines 121-128)
- Trigger: Elasticsearch connection drops after count() succeeds but before taxonomy() runs
- Workaround: None — client receives incomplete status without indication of failure

## Security Considerations

**Write-Ahead Log Stored in User Home (~/.mempalace/wal/):**
- Risk: WAL file contains full drawer metadata and content previews (first 200 chars). Located in user home where filesystem permissions may be weaker than application data. File is chmod 0o600 but this fails silently on some platforms.
- Files: `mempalace/mcp_server.py` (lines 71-96), `/Users/omerkushmaro/.mempalace/wal/write_log.jsonl`
- Current mitigation: File created with 0o600 (user-only). Append-only logging. Directory created with 0o700 (but mkdir -p may not enforce this on all systems).
- Recommendations: 
  - Make WAL directory configurable and document security implications
  - Consider encrypting WAL entries if sensitive data (names, conversations) is included
  - Validate that `chmod` succeeds; raise error if it fails on Unix-like systems
  - Document that clearing WAL is safe (it's append-only, not needed for crash recovery)

**Input Sanitization via Regex:**
- Risk: Wing/room/entity names validated by regex `^[a-zA-Z0-9][a-zA-Z0-9_ .'-]{0,126}[a-zA-Z0-9]?$` is restrictive but allows periods and quotes. Potential for LDAP injection or similar if these fields are later used in queries (e.g., logging, LDAP filter construction).
- Files: `mempalace/config.py` (lines 19, 44-45), `mempalace/mcp_server.py` (lines 315-316)
- Current mitigation: Validation is applied at MCP entry point. Content length capped at 100k characters.
- Recommendations:
  - Document intended use of these fields (Elasticsearch keywords, AAAK codes, directory names)
  - If used in any query language (SQL, LDAP, Lucene), validate separately with parameterized queries
  - Consider stricter character set (alphanumeric + underscore only)

**No Authentication on MCP Server:**
- Risk: MCP server exposes read/write tools (add_drawer, delete_drawer, kg_add, kg_invalidate, diary_write) with no authentication. Any process with access to stdin/stdout can modify the palace.
- Files: `mempalace/mcp_server.py` (all WRITE TOOLS section, lines 307-525)
- Current mitigation: Assumes MCP transport (stdio) is secure (e.g., running locally in Claude Code). WAL provides audit trail for reviews, but no access control.
- Recommendations:
  - Document that MCP server should only be exposed to trusted clients
  - Consider adding an optional `--api-key` mode for remote deployments
  - For shared systems, require explicit confirmation for write operations

## Performance Bottlenecks

**Cross-Wing Aggregation Fetches All Documents:**
- Problem: `tool_list_wings()` (lines 182-188) and fallback in `tool_get_taxonomy()` (lines 221-227) fetch all 10k metadata records and aggregate in memory when ES methods are unavailable
- Files: `mempalace/mcp_server.py` (lines 182-188, 221-227)
- Cause: Code assumes ESCollection may lack aggregation methods, so falls back to full scan. For modern ES, this is unnecessary and slow.
- Improvement path: Remove fallback code; assume PalaceClient always has `taxonomy()`, `room_aggregation()`, etc. If ever using older ES or ChromaDB, use their native aggregation APIs instead of in-memory aggregation.

**PalaceClient Wing Cache Not Shared:**
- Problem: Each PalaceClient instance (one per config load) maintains its own `_wing_cache` dict. If multiple threads/processes load config, they each keep separate ES connections and collections.
- Files: `mempalace/es_client.py` (line 337)
- Cause: No singleton for PalaceClient — each `get_es_collection()` call creates a new config, which could theoretically create duplicates
- Improvement path: Ensure `get_es_collection()` (line 570) is the only entry point and only caches once. Consider module-level lock for initialization.

**WAL Append Lock Contention:**
- Problem: Every write operation (add_drawer, delete_drawer, kg_add, kg_invalidate, diary_write) opens, writes, and closes `write_log.jsonl`. With high concurrency, file open/close becomes a bottleneck.
- Files: `mempalace/mcp_server.py` (lines 80-96)
- Cause: No batching, no write buffer, no queue
- Improvement path: Keep WAL file open, flush every N writes or on timeout. Dedicate a background thread to WAL writes if using WAL for recovery.

## Fragile Areas

**Knowledge Graph SQLite Concurrency:**
- Files: `mempalace/knowledge_graph.py` (line 93)
- Why fragile: SQLite with `check_same_thread=False` allows any thread to access the connection, but SQLite is not thread-safe. Multiple threads writing simultaneously can corrupt the database.
- Safe modification: 
  - Use a threading.Lock around all KG read/write operations
  - OR: Create a new connection per thread and use WAL mode (already enabled)
  - Test concurrent KG updates in test suite
- Test coverage: `tests/test_knowledge_graph.py` appears to be single-threaded; no concurrent write tests exist

**Dialect Parsing Assumes Stable Format:**
- Files: `mempalace/dialect.py` (1075 lines)
- Why fragile: AAAK format is defined in comments and code (emotion codes, flags, structure). No version field or migration path. If format changes, old AAAK entries will parse incorrectly.
- Safe modification: 
  - Add a version header to AAAK entries (e.g., `AAAK_V1: ...`)
  - Write migration functions before changing format
  - Test parsing of old AAAK entries
- Test coverage: Limited parsing tests; no tests for corrupted or malformed AAAK

**ES Index Mapping Evolution:**
- Files: `mempalace/es_client.py` (lines 33-70)
- Why fragile: Mapping is created once per wing index. Adding new fields requires manual index recreation or reindexing. No versioning of mapping or migration logic.
- Safe modification:
  - Document which fields are legacy vs. current
  - Add mapping version to structure index
  - Implement index aliasing for zero-downtime updates
- Test coverage: Tests create new indices; no tests for updating mappings on existing indices

## Scaling Limits

**Pagination Soft Ceiling at 10k items:**
- Current capacity: Any palace with <10k total drawers works fully. Beyond 10k, some operations silently truncate.
- Limit: MCP status calls, wing/room enumeration, and some migration queries use `limit=10000`
- Scaling path: Replace hard limits with cursor-based pagination or ES aggregations. Use scrolling APIs for full scans.

**ES Wildcard Pattern at Unbounded Wing Count:**
- Current capacity: Tested with 2-3 wings; wildcard queries scale to ~50-100 wings (typical). Beyond that, index metadata becomes large.
- Limit: Each wing is a separate ES index. Querying all wings uses index=`citadel_*`, which becomes slow >200 wings.
- Scaling path: Partition by citadel (already done). For many wings, consider shard-per-wing or wing sharding strategy.

**SQLite KG at Scale:**
- Current capacity: Tested with <50k facts. SQLite can handle 100k-1M rows easily, but `query_entity()` with cross-references gets slow.
- Limit: No query optimization for large graph traversal (e.g., multi-hop friend-of-friend queries)
- Scaling path: Add indices on common traversal patterns, or migrate to Neo4j/graph DB if needed.

## Dependencies at Risk

**Elasticsearch Python Client API Stability:**
- Risk: Code uses low-level `es.bulk()`, `es.search()`, `es.indices.get()` which may change between major versions. No version pin or compatibility layer.
- Impact: ES 7.x vs 8.x have minor API changes (e.g., `api_key` parameter, TLS defaults)
- Migration plan: 
  - Pin elasticsearch>=8.0 in requirements
  - Test against 8.x release notes
  - Create wrapper class for ES operations if not already done (PalaceClient is partial wrapper)

**Elasticsearch Inference API Dependency:**
- Risk: Semantic search uses `inference_id: None` (filled at runtime from config). If Elasticsearch deprecates or restructures inference API, embeddings break.
- Impact: Semantic search stops working until inference model is redeployed
- Migration plan:
  - Document current inference model (`.multilingual-e5-small-elasticsearch`)
  - Keep fallback BM25-only search option
  - Monitor Elasticsearch inference API changelog

**ChromaDB Backward Compatibility (Migration Path):**
- Risk: Migration script `migrate_to_es.py` depends on ChromaDB API to read old collections. If users still have ChromaDB palaces and ChromaDB version changes, migration fails.
- Impact: Users stuck on old ChromaDB version
- Migration plan:
  - Mark ChromaDB support as "legacy" in docs
  - Version-lock ChromaDB for migration tool only
  - Consider removing after 1-2 releases

## Missing Critical Features

**No Backup/Restore Mechanism:**
- Problem: ES indices can fail. No backup export. No restore-from-backup option. WAL is audit trail only, not recovery.
- Blocks: Can't safely backup palace before major operations. Can't recover from ES cluster failure.
- Recommendation: 
  - Add `mempalace backup <dir>` command (export all drawers as JSONL)
  - Add `mempalace restore <backup.jsonl>` command
  - Document ES native backup procedures

**No Data Validation/Integrity Check:**
- Problem: No tool to verify that content matches embeddings, that metadata is consistent, or that KG facts reference valid entities.
- Blocks: Silent data corruption (e.g., bad embedding, missing drawer) goes undetected
- Recommendation:
  - Add `mempalace validate` command
  - Check: all drawers are queryable, KG references exist, metadata is well-formed
  - Report corruption and offer repair options

**No Bulk Delete or Cleanup:**
- Problem: Only `tool_delete_drawer()` deletes individual drawers. No way to bulk delete by wing, room, or date range.
- Blocks: Can't clean up a wing without deleting one drawer at a time
- Recommendation:
  - Add `mempalace delete-wing <wing>` command
  - Add `mempalace delete-room <wing> <room>` command
  - Add confirmation prompt

## Test Coverage Gaps

**No Concurrent Write Tests for KG:**
- What's not tested: Multiple threads/processes writing facts simultaneously to knowledge_graph
- Files: `tests/test_knowledge_graph.py`
- Risk: SQLite corruption or lost writes due to `check_same_thread=False` without locking
- Priority: High (concurrency bug is hard to debug)

**No Malformed AAAK Parsing Tests:**
- What's not tested: AAAK parser behavior on invalid input (missing fields, wrong format, corrupt codes)
- Files: `mempalace/dialect.py` (1075 lines) — only positive path tested in `tests/test_dialect.py`
- Risk: Parsing errors silently degrade or crash
- Priority: Medium (edge case, but impacts data integrity)

**No ES Mapping Migration Tests:**
- What's not tested: Adding new fields to ES indices, reindexing, mapping changes
- Files: `mempalace/es_client.py`
- Risk: Production index updates will break if migration is untested
- Priority: Medium (only relevant when schema changes)

**No Large-Scale Pagination Tests:**
- What's not tested: Operations with >10k drawers (wing listing, taxonomy, full scans)
- Files: `tests/test_es_integration.py` (451 lines) — uses small test data
- Risk: Silent truncation at 10k limit will be discovered in production
- Priority: High (scaling limit is hidden)

**No WAL Recovery/Replay Tests:**
- What's not tested: Write operation replay from WAL after crash
- Files: `mempalace/mcp_server.py` (lines 66-96)
- Risk: If WAL is used for recovery (future work), replay logic could be broken
- Priority: Low (recovery not yet implemented)

---

*Concerns audit: 2026-04-10*
