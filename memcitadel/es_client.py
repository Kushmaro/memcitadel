"""
es_client.py — Elasticsearch Serverless backend for MemCitadel
==============================================================

Enterprise-scale architecture: one ES index per wing + a structure index.

    mempalace_structure          — wing/room definitions and metadata
    mempalace_wing_{name}        — drawers for a specific wing
    mempalace_wing_*             — wildcard for cross-wing operations

PalaceClient orchestrates routing: it implements the same ChromaDB-compatible
interface as ESCollection, intercepts wing from where filters, and routes
operations to the correct per-wing index. Consuming code sees no difference.

Hybrid search: BM25 on content_raw + semantic search on content_semantic
via Elasticsearch Inference API (server-side embeddings).
"""

import copy
import logging
from datetime import datetime

from elasticsearch import Elasticsearch, NotFoundError

from .config import MempalaceConfig

logger = logging.getLogger("mempalace_es")

# Fields that hold content (excluded when extracting metadata)
_CONTENT_FIELDS = {"content_raw", "content_aaak", "content_semantic"}

# Wing index mapping — one per wing
WING_INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "content_raw": {"type": "text", "analyzer": "standard"},
            "content_aaak": {"type": "text", "analyzer": "standard"},
            "content_semantic": {
                "type": "semantic_text",
                "inference_id": None,  # filled at runtime from config
            },
            "wing": {"type": "keyword"},
            "room": {"type": "keyword"},
            "hall": {"type": "keyword"},
            "source_file": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "added_by": {"type": "keyword"},
            "filed_at": {"type": "date", "format": "strict_date_optional_time||epoch_millis"},
            "date": {"type": "keyword"},
            "topic": {"type": "keyword"},
            "type": {"type": "keyword"},
            "agent": {"type": "keyword"},
            "ingest_mode": {"type": "keyword"},
            "extract_mode": {"type": "keyword"},
            "source_mtime": {"type": "float"},
        }
    }
}

# Structure index mapping — wing/room metadata
STRUCTURE_MAPPING = {
    "mappings": {
        "properties": {
            "type": {"type": "keyword"},
            "name": {"type": "keyword"},
            "wing": {"type": "keyword"},
            "description": {"type": "text"},
            "created_at": {"type": "date"},
        }
    }
}


def _build_wing_mapping(config):
    """Return wing index mapping with inference_id from config."""
    mapping = copy.deepcopy(WING_INDEX_MAPPING)
    mapping["mappings"]["properties"]["content_semantic"]["inference_id"] = config.es_inference_id
    return mapping


# ---------------------------------------------------------------------------
# Filter translation: ChromaDB where → ES bool filter
# ---------------------------------------------------------------------------


def _translate_where(where):
    """Convert ChromaDB-style where filter to ES bool filter clauses.

    Supported patterns (all that the codebase uses):
        {"field": "value"}           → [{"term": {"field": "value"}}]
        {"$and": [{...}, {...}]}     → flattened list of term clauses
    """
    if not where:
        return []

    if "$and" in where:
        clauses = []
        for condition in where["$and"]:
            clauses.extend(_translate_where(condition))
        return clauses

    return [{"term": {k: v}} for k, v in where.items()]


def _extract_wing_from_where(where):
    """Extract wing name from a ChromaDB-style where filter.

    Returns (wing_name_or_None, remaining_where_or_None).

    Examples:
        {"wing": "code"}                                  → ("code", None)
        {"$and": [{"wing": "code"}, {"room": "testing"}]} → ("code", {"room": "testing"})
        {"room": "testing"}                                → (None, {"room": "testing"})
        None                                               → (None, None)
    """
    if not where:
        return None, None

    # Simple case: {"wing": "value"}
    if "wing" in where and "$and" not in where:
        wing = where["wing"]
        remaining = {k: v for k, v in where.items() if k != "wing"}
        return wing, remaining or None

    # Compound case: {"$and": [...]}
    if "$and" in where:
        wing = None
        remaining_conditions = []
        for condition in where["$and"]:
            if isinstance(condition, dict) and "wing" in condition and len(condition) == 1:
                wing = condition["wing"]
            else:
                remaining_conditions.append(condition)

        if not remaining_conditions:
            remaining = None
        elif len(remaining_conditions) == 1:
            remaining = remaining_conditions[0]
        else:
            remaining = {"$and": remaining_conditions}

        return wing, remaining

    return None, where


# ---------------------------------------------------------------------------
# Response formatting: ES hits → ChromaDB-shaped dicts
# ---------------------------------------------------------------------------


def _extract_metadata(source):
    """Extract metadata fields from ES _source, excluding content fields."""
    return {k: v for k, v in source.items() if k not in _CONTENT_FIELDS}


def _hits_to_get_format(hits, include):
    """Convert ES hits to ChromaDB get() format (flat lists)."""
    include = include or []
    result = {"ids": [h["_id"] for h in hits]}

    if "documents" in include:
        result["documents"] = [h["_source"].get("content_raw", "") for h in hits]
    if "metadatas" in include:
        result["metadatas"] = [_extract_metadata(h["_source"]) for h in hits]

    return result


def _hits_to_query_format(hits, include):
    """Convert ES hits to ChromaDB query() format (nested lists)."""
    include = include or []
    result = {"ids": [[h["_id"] for h in hits]]}

    if "documents" in include:
        result["documents"] = [[h["_source"].get("content_raw", "") for h in hits]]
    if "metadatas" in include:
        result["metadatas"] = [[_extract_metadata(h["_source"]) for h in hits]]
    if "distances" in include:
        if hits:
            max_score = max(h["_score"] for h in hits) or 1.0
            result["distances"] = [[round(1.0 - (h["_score"] / max_score), 4) for h in hits]]
        else:
            result["distances"] = [[]]

    return result


def _include_to_source(include):
    """Map ChromaDB include param to ES _source filtering."""
    if not include:
        return True

    fields = []
    if "documents" in include:
        fields.extend(["content_raw", "content_aaak"])
    if "metadatas" in include:
        fields.extend(
            [
                "wing",
                "room",
                "hall",
                "source_file",
                "chunk_index",
                "added_by",
                "filed_at",
                "date",
                "topic",
                "type",
                "agent",
                "ingest_mode",
                "extract_mode",
                "source_mtime",
            ]
        )
    return fields if fields else True


# ---------------------------------------------------------------------------
# ESCollection — per-index building block
# ---------------------------------------------------------------------------


class ESCollection:
    """Elasticsearch-backed collection for a single index."""

    def __init__(self, es, index_name, config):
        self.es = es
        self.index_name = index_name
        self.config = config

    def count(self):
        resp = self.es.count(index=self.index_name)
        return resp["count"]

    def add(self, ids, documents, metadatas):
        self._bulk_index(ids, documents, metadatas)

    def upsert(self, ids, documents, metadatas):
        self._bulk_index(ids, documents, metadatas)

    def _bulk_index(self, ids, documents, metadatas):
        operations = []
        for doc_id, doc_text, meta in zip(ids, documents, metadatas):
            operations.append({"index": {"_index": self.index_name, "_id": doc_id}})
            body = {"content_raw": doc_text, "content_semantic": doc_text}
            for k, v in meta.items():
                if k not in _CONTENT_FIELDS:
                    body[k] = v
            operations.append(body)
        if operations:
            self.es.bulk(operations=operations, refresh="wait_for")

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        if ids:
            body = {"query": {"ids": {"values": ids}}, "size": limit}
        elif where:
            es_filter = _translate_where(where)
            body = {"query": {"bool": {"filter": es_filter}}, "size": limit, "from": offset}
        else:
            body = {"query": {"match_all": {}}, "size": limit, "from": offset}

        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_get_format(resp["hits"]["hits"], include or [])

    def query(self, query_texts, n_results=5, where=None, include=None):
        query_text = query_texts[0]
        bm25_query = {"match": {"content_raw": query_text}}
        semantic_query = {"semantic": {"field": "content_semantic", "query": query_text}}

        if where:
            es_filter = _translate_where(where)
            bm25_query = {"bool": {"must": [bm25_query], "filter": es_filter}}
            semantic_query = {"bool": {"must": [semantic_query], "filter": es_filter}}

        body = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": bm25_query}},
                        {"standard": {"query": semantic_query}},
                    ]
                }
            },
            "size": n_results,
        }
        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def query_vector_only(self, query_texts, n_results=5, include=None):
        query_text = query_texts[0]
        body = {
            "query": {"semantic": {"field": "content_semantic", "query": query_text}},
            "size": n_results,
        }
        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def delete(self, ids):
        operations = []
        for doc_id in ids:
            operations.append({"delete": {"_index": self.index_name, "_id": doc_id}})
        if operations:
            self.es.bulk(operations=operations, refresh="wait_for")


# ---------------------------------------------------------------------------
# PalaceClient — multi-index orchestrator
# ---------------------------------------------------------------------------


class PalaceClient:
    """Routes operations to per-wing indices. Drop-in replacement for ESCollection.

    Intercepts wing from where filters and metadata to route to the correct
    mempalace_wing_{name} index. Cross-wing operations use wildcard pattern.
    """

    def __init__(self, es, config):
        self.es = es
        self.config = config
        self._prefix = config.es_index_prefix
        self._wildcard = f"{self._prefix}*"
        self._structure_index = config.es_structure_index
        self._wing_cache = {}  # wing_name → ESCollection

    def _wing_index(self, wing):
        """Return the index name for a wing."""
        return f"{self._prefix}{wing}"

    def _get_wing(self, wing, create=False):
        """Return an ESCollection for a specific wing, creating the index if needed."""
        if wing not in self._wing_cache:
            index_name = self._wing_index(wing)
            if create and not self.es.indices.exists(index=index_name):
                mapping = _build_wing_mapping(self.config)
                self.es.indices.create(index=index_name, body=mapping)
                self._upsert_structure("wing", wing)
            self._wing_cache[wing] = ESCollection(self.es, index_name, self.config)
        return self._wing_cache[wing]

    def _resolve_index(self, wing):
        """Return index name or wildcard pattern."""
        if wing:
            return self._wing_index(wing)
        return self._wildcard

    def _upsert_structure(self, entry_type, name, wing=None):
        """Lazily create a wing or room entry in the structure index."""
        if not self.es.indices.exists(index=self._structure_index):
            self.es.indices.create(index=self._structure_index, body=STRUCTURE_MAPPING)

        if entry_type == "wing":
            doc_id = f"wing:{name}"
            body = {"type": "wing", "name": name, "created_at": datetime.now().isoformat()}
        else:
            doc_id = f"room:{wing}:{name}"
            body = {
                "type": "room",
                "name": name,
                "wing": wing,
                "created_at": datetime.now().isoformat(),
            }

        self.es.index(
            index=self._structure_index, id=doc_id, body=body, op_type="create", ignore=[409]
        )  # ignore conflict if already exists

    # --- ChromaDB-compatible interface ---

    def count(self):
        try:
            resp = self.es.count(index=self._wildcard)
            return resp["count"]
        except NotFoundError:
            return 0

    def add(self, ids, documents, metadatas):
        self._routed_bulk(ids, documents, metadatas)

    def upsert(self, ids, documents, metadatas):
        self._routed_bulk(ids, documents, metadatas)

    def _routed_bulk(self, ids, documents, metadatas):
        """Bulk index, routing each doc to its wing index based on metadata."""
        # Group by wing
        wing_batches = {}
        for doc_id, doc_text, meta in zip(ids, documents, metadatas):
            wing = meta.get("wing", "default")
            if wing not in wing_batches:
                wing_batches[wing] = ([], [], [])
            wing_batches[wing][0].append(doc_id)
            wing_batches[wing][1].append(doc_text)
            wing_batches[wing][2].append(meta)

        for wing, (w_ids, w_docs, w_metas) in wing_batches.items():
            col = self._get_wing(wing, create=True)
            col._bulk_index(w_ids, w_docs, w_metas)
            # Lazily register rooms in structure index
            rooms_seen = {m.get("room") for m in w_metas if m.get("room")}
            for room in rooms_seen:
                self._upsert_structure("room", room, wing=wing)

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        if ids:
            # IDs are globally unique — search across all wing indices
            index = self._wildcard
            body = {"query": {"ids": {"values": ids}}, "size": limit}
        else:
            wing, remaining = _extract_wing_from_where(where)
            index = self._resolve_index(wing)
            if remaining:
                es_filter = _translate_where(remaining)
                body = {"query": {"bool": {"filter": es_filter}}, "size": limit, "from": offset}
            else:
                body = {"query": {"match_all": {}}, "size": limit, "from": offset}

        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self.es.search(index=index, body=body)
        except NotFoundError:
            return _hits_to_get_format([], include or [])

        return _hits_to_get_format(resp["hits"]["hits"], include or [])

    def query(self, query_texts, n_results=5, where=None, include=None):
        wing, remaining = _extract_wing_from_where(where)
        index = self._resolve_index(wing)
        query_text = query_texts[0]

        bm25_query = {"match": {"content_raw": query_text}}
        semantic_query = {"semantic": {"field": "content_semantic", "query": query_text}}

        if remaining:
            es_filter = _translate_where(remaining)
            bm25_query = {"bool": {"must": [bm25_query], "filter": es_filter}}
            semantic_query = {"bool": {"must": [semantic_query], "filter": es_filter}}

        body = {
            "retriever": {
                "rrf": {
                    "retrievers": [
                        {"standard": {"query": bm25_query}},
                        {"standard": {"query": semantic_query}},
                    ]
                }
            },
            "size": n_results,
        }
        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self.es.search(index=index, body=body)
        except NotFoundError:
            return _hits_to_query_format([], include or [])

        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def query_vector_only(self, query_texts, n_results=5, include=None):
        """Pure semantic search across all wings — for duplicate detection."""
        query_text = query_texts[0]
        body = {
            "query": {"semantic": {"field": "content_semantic", "query": query_text}},
            "size": n_results,
        }
        source_fields = _include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self.es.search(index=self._wildcard, body=body)
        except NotFoundError:
            return _hits_to_query_format([], include or [])

        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def delete(self, ids):
        """Delete documents by ID across all wing indices."""
        try:
            self.es.delete_by_query(
                index=self._wildcard,
                body={"query": {"ids": {"values": ids}}},
                refresh=True,
            )
        except NotFoundError:
            pass

    def update_aaak(self, doc_id, aaak_text, wing=None, extra_fields=None):
        """Partial update: set content_aaak on an existing document without touching content_raw."""
        index = self._wing_index(wing) if wing else self._wildcard
        body = {"content_aaak": aaak_text}
        if extra_fields:
            body.update(extra_fields)
        self.es.update(index=index, id=doc_id, body={"doc": body}, refresh="wait_for")

    # --- Aggregation helpers (for mcp_server.py optimization) ---

    def list_wing_names(self):
        """Return list of wing names from existing indices."""
        try:
            indices = self.es.indices.get(index=self._wildcard)
            prefix_len = len(self._prefix)
            return sorted(name[prefix_len:] for name in indices.keys())
        except NotFoundError:
            return []

    def wing_count(self, wing):
        """Count drawers in a specific wing."""
        try:
            return self.es.count(index=self._wing_index(wing))["count"]
        except NotFoundError:
            return 0

    def room_aggregation(self, wing=None):
        """Return {room: count} for a wing or all wings."""
        index = self._wing_index(wing) if wing else self._wildcard
        body = {"size": 0, "aggs": {"rooms": {"terms": {"field": "room", "size": 10000}}}}
        try:
            resp = self.es.search(index=index, body=body)
        except NotFoundError:
            return {}
        return {b["key"]: b["doc_count"] for b in resp["aggregations"]["rooms"]["buckets"]}

    def taxonomy(self):
        """Return {wing: {room: count}} using nested aggregation."""
        body = {
            "size": 0,
            "aggs": {
                "wings": {
                    "terms": {"field": "wing", "size": 10000},
                    "aggs": {"rooms": {"terms": {"field": "room", "size": 10000}}},
                }
            },
        }
        try:
            resp = self.es.search(index=self._wildcard, body=body)
        except NotFoundError:
            return {}
        result = {}
        for wb in resp["aggregations"]["wings"]["buckets"]:
            result[wb["key"]] = {rb["key"]: rb["doc_count"] for rb in wb["rooms"]["buckets"]}
        return result


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_es_client = None
_palace_client = None


def get_es_collection(create=False):
    """Return a cached PalaceClient instance. Creates structure index if create=True."""
    global _es_client, _palace_client

    config = MempalaceConfig()

    if not config.es_api_key or (not config.es_url and not config.es_cloud_id):
        logger.error(
            "ES not configured. Set ES_URL + ES_KEY (or MEMPALACE_ES_CLOUD_ID + MEMPALACE_ES_API_KEY)."
        )
        return None

    try:
        if _es_client is None:
            if config.es_url:
                _es_client = Elasticsearch(
                    hosts=config.es_url,
                    api_key=config.es_api_key,
                    request_timeout=120,
                )
            else:
                _es_client = Elasticsearch(
                    cloud_id=config.es_cloud_id,
                    api_key=config.es_api_key,
                    request_timeout=120,
                )

        if _palace_client is None:
            if create:
                if not _es_client.indices.exists(index=config.es_structure_index):
                    _es_client.indices.create(
                        index=config.es_structure_index, body=STRUCTURE_MAPPING
                    )
            elif not _es_client.indices.exists(index=f"{config.es_index_prefix}*"):
                return None
            _palace_client = PalaceClient(_es_client, config)

        return _palace_client
    except Exception as e:
        logger.error(f"ES connection failed: {e}")
        return None
