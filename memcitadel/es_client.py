"""
es_client.py — Elasticsearch Serverless backend for MemPalace
==============================================================

Replaces ChromaDB with Elasticsearch Serverless.
Provides ESCollection with the same interface as ChromaDB's Collection
so consuming code (mcp_server, searcher, miner, layers, palace_graph,
convo_miner) needs minimal changes.

Hybrid search: BM25 on content_raw + semantic search on content_semantic
via Elasticsearch Inference API (server-side embeddings).
"""

import logging

from elasticsearch import Elasticsearch, NotFoundError

from .config import MempalaceConfig

logger = logging.getLogger("mempalace_es")

# Fields that hold content (excluded when extracting metadata)
_CONTENT_FIELDS = {"content_raw", "content_aaak", "content_semantic"}

# Index mapping — created on first use if index doesn't exist
INDEX_MAPPING = {
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


def _build_mapping(config):
    """Return index mapping with inference_id from config."""
    import copy

    mapping = copy.deepcopy(INDEX_MAPPING)
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
        # Normalize scores to ChromaDB-style distances (0 = identical, higher = worse).
        # ChromaDB uses cosine distance; consuming code does `similarity = 1 - dist`.
        # We normalize ES scores to [0, 1] similarity, then convert: dist = 1 - sim.
        if hits:
            max_score = max(h["_score"] for h in hits) or 1.0
            result["distances"] = [
                [round(1.0 - (h["_score"] / max_score), 4) for h in hits]
            ]
        else:
            result["distances"] = [[]]

    return result


# ---------------------------------------------------------------------------
# ESCollection — drop-in replacement for ChromaDB Collection
# ---------------------------------------------------------------------------


class ESCollection:
    """Elasticsearch-backed collection with ChromaDB-compatible interface."""

    def __init__(self, es, index_name, config):
        self.es = es
        self.index_name = index_name
        self.config = config

    def count(self):
        resp = self.es.count(index=self.index_name)
        return resp["count"]

    def add(self, ids, documents, metadatas):
        """Index documents. Raises on duplicate IDs (mirrors ChromaDB add behavior)."""
        self._bulk_index(ids, documents, metadatas)

    def upsert(self, ids, documents, metadatas):
        """Index documents, overwriting if ID exists."""
        self._bulk_index(ids, documents, metadatas)

    def _bulk_index(self, ids, documents, metadatas):
        """Bulk index documents into ES."""
        operations = []
        for doc_id, doc_text, meta in zip(ids, documents, metadatas):
            operations.append({"index": {"_index": self.index_name, "_id": doc_id}})
            body = {"content_raw": doc_text, "content_semantic": doc_text}
            # Merge metadata fields into the document body
            for k, v in meta.items():
                if k not in _CONTENT_FIELDS:
                    body[k] = v
            operations.append(body)

        if operations:
            self.es.bulk(operations=operations, refresh="wait_for")

    def get(self, ids=None, where=None, include=None, limit=10000, offset=0):
        """Filtered retrieval (no semantic search)."""
        if ids:
            body = {"query": {"ids": {"values": ids}}, "size": limit}
        elif where:
            es_filter = _translate_where(where)
            body = {
                "query": {"bool": {"filter": es_filter}},
                "size": limit,
                "from": offset,
            }
        else:
            body = {"query": {"match_all": {}}, "size": limit, "from": offset}

        # Determine which _source fields to return
        source_fields = self._include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_get_format(resp["hits"]["hits"], include or [])

    def query(self, query_texts, n_results=5, where=None, include=None):
        """Hybrid search: BM25 on content_raw + semantic on content_semantic via RRF."""
        query_text = query_texts[0]

        # Build two retrievers for RRF
        bm25_query = {"match": {"content_raw": query_text}}
        semantic_query = {"semantic": {"field": "content_semantic", "query": query_text}}

        # If where filter specified, wrap each retriever in a bool with filter
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

        source_fields = self._include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def query_vector_only(self, query_texts, n_results=5, include=None):
        """Pure semantic search — used for duplicate detection where cosine-like scores matter."""
        query_text = query_texts[0]

        body = {
            "query": {"semantic": {"field": "content_semantic", "query": query_text}},
            "size": n_results,
        }

        source_fields = self._include_to_source(include)
        if source_fields is not True:
            body["_source"] = source_fields

        resp = self.es.search(index=self.index_name, body=body)
        return _hits_to_query_format(resp["hits"]["hits"], include or [])

    def delete(self, ids):
        """Delete documents by ID."""
        operations = []
        for doc_id in ids:
            operations.append({"delete": {"_index": self.index_name, "_id": doc_id}})

        if operations:
            self.es.bulk(operations=operations, refresh="wait_for")

    def _include_to_source(self, include):
        """Map ChromaDB include param to ES _source filtering."""
        if not include:
            return True

        fields = []
        if "documents" in include:
            fields.extend(["content_raw", "content_aaak"])
        if "metadatas" in include:
            # Return all non-content fields
            fields.extend([
                "wing", "room", "hall", "source_file", "chunk_index",
                "added_by", "filed_at", "date", "topic", "type",
                "agent", "ingest_mode", "extract_mode", "source_mtime",
            ])
        # "distances" doesn't affect _source — derived from _score
        return fields if fields else True


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_es_client = None
_es_collection = None


def get_es_collection(create=False):
    """Return a cached ESCollection instance. Creates index if create=True."""
    global _es_client, _es_collection

    config = MempalaceConfig()

    if not config.es_api_key or (not config.es_url and not config.es_cloud_id):
        logger.error("ES not configured. Set ES_URL + ES_KEY (or MEMPALACE_ES_CLOUD_ID + MEMPALACE_ES_API_KEY).")
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

        if _es_collection is None:
            index_name = config.es_index_name

            if create:
                if not _es_client.indices.exists(index=index_name):
                    mapping = _build_mapping(config)
                    _es_client.indices.create(index=index_name, body=mapping)
            else:
                if not _es_client.indices.exists(index=index_name):
                    return None

            _es_collection = ESCollection(_es_client, index_name, config)

        return _es_collection
    except Exception as e:
        logger.error(f"ES connection failed: {e}")
        return None
