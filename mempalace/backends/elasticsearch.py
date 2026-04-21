"""Elasticsearch backend for MemCitadel — RFC 001 §10 compliant.

One ES index per wing + a structure index:

    {prefix}structure          — wing/room definitions and metadata
    {prefix}{wing}             — drawers for a specific wing
    {prefix}*                  — wildcard for cross-wing operations

``ElasticsearchBackend`` is a ``BaseBackend`` factory keyed by ``PalaceRef``.
``ESCollection`` implements ``BaseCollection`` for a single logical collection
(drawers or closets) within a palace. The drawers collection routes writes
to per-wing indices based on the ``wing`` metadata field; closets and other
collection types use a single index per palace.

Hybrid search: BM25 on ``content_raw`` + semantic on ``content_semantic`` via
Elasticsearch Inference API (server-side embeddings) fused with RRF.
"""

from __future__ import annotations

import copy
import logging
import threading
from datetime import datetime
from typing import Optional

from elasticsearch import Elasticsearch, NotFoundError

from ..config import MempalaceConfig
from .base import (
    BackendClosedError,
    BaseBackend,
    BaseCollection,
    GetResult,
    HealthStatus,
    PalaceNotFoundError,
    PalaceRef,
    QueryResult,
    UnsupportedFilterError,
    _VALID_INCLUDE_KEYS,
)

logger = logging.getLogger("mempalace_es")

# Fields that hold content (excluded when extracting metadata)
_CONTENT_FIELDS = {"content_raw", "content_aaak", "content_semantic"}

# ---------------------------------------------------------------------------
# Index mappings
# ---------------------------------------------------------------------------

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


def _build_wing_mapping(config: MempalaceConfig) -> dict:
    mapping = copy.deepcopy(WING_INDEX_MAPPING)
    mapping["mappings"]["properties"]["content_semantic"]["inference_id"] = config.es_inference_id
    return mapping


# ---------------------------------------------------------------------------
# Filter translation: ChromaDB-style where → ES bool filter
# ---------------------------------------------------------------------------

_SUPPORTED_OPS = frozenset({"$and"})


def _translate_where(where: Optional[dict]) -> list:
    """Convert ChromaDB-style where filter to ES bool filter clauses.

    Supports:
        {"field": "value"}           → [{"term": {"field": "value"}}]
        {"$and": [...]}              → flattened list of term clauses

    Raises ``UnsupportedFilterError`` on operators we don't translate, per
    RFC 001 §1.4 (silent dropping is forbidden).
    """
    if not where:
        return []

    # Reject unknown $operators
    for key in where.keys():
        if key.startswith("$") and key not in _SUPPORTED_OPS:
            raise UnsupportedFilterError(
                f"ES backend does not support operator {key!r}; supported: {sorted(_SUPPORTED_OPS)}"
            )

    if "$and" in where:
        clauses = []
        for condition in where["$and"]:
            clauses.extend(_translate_where(condition))
        return clauses

    return [{"term": {k: v}} for k, v in where.items()]


def _extract_wing_from_where(where: Optional[dict]):
    """Extract wing name from a ChromaDB-style where filter.

    Returns (wing_name_or_None, remaining_where_or_None).
    """
    if not where:
        return None, None

    if "wing" in where and "$and" not in where:
        wing = where["wing"]
        remaining = {k: v for k, v in where.items() if k != "wing"}
        return wing, remaining or None

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
# Response formatting: ES hits → typed RFC 001 results
# ---------------------------------------------------------------------------


def _validate_include(include: Optional[list[str]]) -> set:
    if not include:
        return set()
    unknown = set(include) - _VALID_INCLUDE_KEYS
    if unknown:
        raise UnsupportedFilterError(
            f"unknown include keys: {sorted(unknown)}; supported: {sorted(_VALID_INCLUDE_KEYS)}"
        )
    return set(include)


def _extract_metadata(source: dict) -> dict:
    return {k: v for k, v in source.items() if k not in _CONTENT_FIELDS}


def _hits_to_get_result(hits: list, include_set: set) -> GetResult:
    ids = [h["_id"] for h in hits]
    documents = (
        [h["_source"].get("content_raw", "") for h in hits] if "documents" in include_set else []
    )
    metadatas = (
        [_extract_metadata(h["_source"]) for h in hits] if "metadatas" in include_set else []
    )
    # Embeddings are server-side; we don't retrieve them.
    embeddings = [] if "embeddings" in include_set else None
    return GetResult(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)


def _hits_to_query_result(hits: list, include_set: set) -> QueryResult:
    ids = [[h["_id"] for h in hits]]
    documents = (
        [[h["_source"].get("content_raw", "") for h in hits]]
        if "documents" in include_set
        else [[] for _ in ids]
    )
    metadatas = (
        [[_extract_metadata(h["_source"]) for h in hits]]
        if "metadatas" in include_set
        else [[] for _ in ids]
    )
    if "distances" in include_set or not include_set:
        if hits:
            max_score = max(h["_score"] for h in hits) or 1.0
            distances = [[round(1.0 - (h["_score"] / max_score), 4) for h in hits]]
        else:
            distances = [[]]
    else:
        distances = [[] for _ in ids]
    embeddings = [[]] if "embeddings" in include_set else None
    return QueryResult(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
        distances=distances,
        embeddings=embeddings,
    )


def _include_to_source(include_set: set):
    """Map RFC 001 include set to ES _source filtering."""
    if not include_set:
        return True

    fields = []
    if "documents" in include_set:
        fields.extend(["content_raw", "content_aaak"])
    if "metadatas" in include_set:
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
# ESCollection — BaseCollection implementation
# ---------------------------------------------------------------------------


class ESCollection(BaseCollection):
    """RFC 001-compliant ES collection.

    Two modes, driven by ``collection_name``:

    * ``mempalace_drawers`` (default) — writes are routed to per-wing indices
      based on metadata["wing"]; reads span all wings via wildcard unless a
      wing filter is supplied (then scoped to that wing's index).
    * Any other name — single index at ``{prefix}{collection_name}``.
    """

    DRAWERS_NAME = "mempalace_drawers"

    def __init__(
        self,
        *,
        es: Elasticsearch,
        config: MempalaceConfig,
        collection_name: str,
        create: bool = False,
    ):
        self._es = es
        self._config = config
        self._collection_name = collection_name
        self._prefix = config.es_index_prefix
        self._wildcard = f"{self._prefix}*"
        self._structure_index = config.es_structure_index
        self._closed = False
        self._wing_cache: dict[str, str] = {}  # wing name → index name
        self._lock = threading.Lock()

        if self._is_drawers:
            # Drawers collection uses per-wing routing; nothing to eagerly create here.
            if create and not self._es.indices.exists(index=self._structure_index):
                self._es.indices.create(index=self._structure_index, body=STRUCTURE_MAPPING)
        else:
            # Non-drawers collection: single index at {prefix}{collection_name}
            self._flat_index = f"{self._prefix}{collection_name}"
            if create and not self._es.indices.exists(index=self._flat_index):
                self._es.indices.create(
                    index=self._flat_index, body=_build_wing_mapping(self._config)
                )
            elif not create and not self._es.indices.exists(index=self._flat_index):
                raise PalaceNotFoundError(
                    f"collection index {self._flat_index!r} does not exist and create=False"
                )

    @property
    def _is_drawers(self) -> bool:
        return self._collection_name == self.DRAWERS_NAME

    def _check_open(self) -> None:
        if self._closed:
            raise BackendClosedError("collection is closed")

    # ------------------------------------------------------------------
    # Wing-routing helpers (drawers mode)
    # ------------------------------------------------------------------

    def _wing_index(self, wing: str) -> str:
        return f"{self._prefix}{wing}"

    def _ensure_wing_index(self, wing: str) -> str:
        index = self._wing_index(wing)
        with self._lock:
            if wing in self._wing_cache:
                return index
            if not self._es.indices.exists(index=index):
                self._es.indices.create(index=index, body=_build_wing_mapping(self._config))
                self._upsert_structure("wing", wing)
            self._wing_cache[wing] = index
        return index

    def _upsert_structure(self, entry_type: str, name: str, wing: Optional[str] = None) -> None:
        if not self._es.indices.exists(index=self._structure_index):
            self._es.indices.create(index=self._structure_index, body=STRUCTURE_MAPPING)

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
        self._es.index(
            index=self._structure_index,
            id=doc_id,
            body=body,
            op_type="create",
            ignore=[409],
        )

    def _resolve_read_index(self, where: Optional[dict]):
        """Return (index_or_wildcard, remaining_where)."""
        if not self._is_drawers:
            return self._flat_index, where
        wing, remaining = _extract_wing_from_where(where)
        if wing:
            return self._wing_index(wing), remaining
        return self._wildcard, remaining

    # ------------------------------------------------------------------
    # RFC 001 BaseCollection interface
    # ------------------------------------------------------------------

    def count(self) -> int:
        self._check_open()
        try:
            if self._is_drawers:
                resp = self._es.count(index=self._wildcard)
            else:
                resp = self._es.count(index=self._flat_index)
            return resp["count"]
        except NotFoundError:
            return 0

    def add(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        self._check_open()
        metadatas = metadatas or [{} for _ in ids]
        self._bulk_write(ids=ids, documents=documents, metadatas=metadatas)

    def upsert(
        self,
        *,
        documents: list[str],
        ids: list[str],
        metadatas: Optional[list[dict]] = None,
        embeddings: Optional[list[list[float]]] = None,
    ) -> None:
        self._check_open()
        metadatas = metadatas or [{} for _ in ids]
        self._bulk_write(ids=ids, documents=documents, metadatas=metadatas)

    def _bulk_write(self, *, ids, documents, metadatas):
        if self._is_drawers:
            # Group by wing and route per-wing
            wing_batches: dict[str, tuple] = {}
            for doc_id, doc_text, meta in zip(ids, documents, metadatas):
                wing = (meta or {}).get("wing", "default")
                batch = wing_batches.setdefault(wing, ([], [], []))
                batch[0].append(doc_id)
                batch[1].append(doc_text)
                batch[2].append(meta or {})
            for wing, (w_ids, w_docs, w_metas) in wing_batches.items():
                index = self._ensure_wing_index(wing)
                self._bulk_to_index(index, w_ids, w_docs, w_metas)
                rooms = {m.get("room") for m in w_metas if m.get("room")}
                for room in rooms:
                    self._upsert_structure("room", room, wing=wing)
        else:
            self._bulk_to_index(self._flat_index, list(ids), list(documents), list(metadatas))

    def _bulk_to_index(self, index, ids, documents, metadatas):
        operations = []
        for doc_id, doc_text, meta in zip(ids, documents, metadatas):
            operations.append({"index": {"_index": index, "_id": doc_id}})
            body = {"content_raw": doc_text, "content_semantic": doc_text}
            for k, v in meta.items():
                if k not in _CONTENT_FIELDS:
                    body[k] = v
            operations.append(body)
        if operations:
            self._es.bulk(operations=operations, refresh="wait_for")

    def query(
        self,
        *,
        query_texts: Optional[list[str]] = None,
        query_embeddings: Optional[list[list[float]]] = None,
        n_results: int = 10,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
        include: Optional[list[str]] = None,
    ) -> QueryResult:
        self._check_open()
        if where_document:
            raise UnsupportedFilterError("where_document is not supported by the ES backend")
        if not query_texts:
            return QueryResult.empty(
                num_queries=1, embeddings_requested=bool(include and "embeddings" in include)
            )

        include_set = _validate_include(include)
        index, remaining = self._resolve_read_index(where)
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
        source_fields = _include_to_source(include_set)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self._es.search(index=index, body=body)
        except NotFoundError:
            return QueryResult.empty(
                num_queries=1, embeddings_requested="embeddings" in include_set
            )

        return _hits_to_query_result(resp["hits"]["hits"], include_set)

    def query_vector_only(
        self,
        *,
        query_texts: list[str],
        n_results: int = 5,
        include: Optional[list[str]] = None,
    ) -> QueryResult:
        """Pure semantic search (fork-specific helper used for dedup)."""
        self._check_open()
        if not query_texts:
            return QueryResult.empty(num_queries=1)

        include_set = _validate_include(include)
        index = self._wildcard if self._is_drawers else self._flat_index

        body = {
            "query": {"semantic": {"field": "content_semantic", "query": query_texts[0]}},
            "size": n_results,
        }
        source_fields = _include_to_source(include_set)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self._es.search(index=index, body=body)
        except NotFoundError:
            return QueryResult.empty(
                num_queries=1, embeddings_requested="embeddings" in include_set
            )

        return _hits_to_query_result(resp["hits"]["hits"], include_set)

    def get(
        self,
        *,
        ids: Optional[list[str]] = None,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        include: Optional[list[str]] = None,
    ) -> GetResult:
        self._check_open()
        if where_document:
            raise UnsupportedFilterError("where_document is not supported by the ES backend")

        include_set = _validate_include(include)
        # RFC 001 default is documents+metadatas; BaseCollection's `get` returns
        # what was requested, so don't inject defaults here.
        size = limit if limit is not None else 10000
        start = offset or 0

        if ids:
            # IDs are globally unique — search across all wing indices (drawers) or flat index
            index = self._wildcard if self._is_drawers else self._flat_index
            body = {"query": {"ids": {"values": list(ids)}}, "size": size}
        else:
            index, remaining = self._resolve_read_index(where)
            if remaining:
                es_filter = _translate_where(remaining)
                body = {
                    "query": {"bool": {"filter": es_filter}},
                    "size": size,
                    "from": start,
                }
            else:
                body = {"query": {"match_all": {}}, "size": size, "from": start}

        source_fields = _include_to_source(include_set)
        if source_fields is not True:
            body["_source"] = source_fields

        try:
            resp = self._es.search(index=index, body=body)
        except NotFoundError:
            return GetResult.empty()

        return _hits_to_get_result(resp["hits"]["hits"], include_set)

    def delete(
        self,
        *,
        ids: Optional[list[str]] = None,
        where: Optional[dict] = None,
    ) -> None:
        self._check_open()
        if ids:
            index = self._wildcard if self._is_drawers else self._flat_index
            try:
                self._es.delete_by_query(
                    index=index,
                    body={"query": {"ids": {"values": list(ids)}}},
                    refresh=True,
                )
            except NotFoundError:
                pass
            return

        if where:
            index, remaining = self._resolve_read_index(where)
            query = (
                {"bool": {"filter": _translate_where(remaining)}}
                if remaining
                else {"match_all": {}}
            )
            try:
                self._es.delete_by_query(index=index, body={"query": query}, refresh=True)
            except NotFoundError:
                pass
            return

        raise ValueError("delete requires ids or where")

    def close(self) -> None:
        self._closed = True

    def health(self) -> HealthStatus:
        try:
            resp = self._es.cluster.health()
            status = resp.get("status", "unknown")
            if status in ("green", "yellow"):
                return HealthStatus.healthy(f"cluster={status}")
            return HealthStatus.unhealthy(f"cluster={status}")
        except Exception as exc:
            return HealthStatus.unhealthy(f"health check failed: {exc}")

    # ------------------------------------------------------------------
    # Fork-specific helpers (not part of BaseCollection; used by miner/searcher)
    # ------------------------------------------------------------------

    def update_aaak(
        self,
        *,
        doc_id: str,
        aaak_text: str,
        wing: Optional[str] = None,
        extra_fields: Optional[dict] = None,
    ) -> None:
        """Partial update setting ``content_aaak`` without touching ``content_raw``."""
        self._check_open()
        if self._is_drawers:
            index = self._wing_index(wing) if wing else self._wildcard
        else:
            index = self._flat_index
        body = {"content_aaak": aaak_text}
        if extra_fields:
            body.update(extra_fields)
        self._es.update(index=index, id=doc_id, body={"doc": body}, refresh="wait_for")

    def list_wing_names(self) -> list[str]:
        """Return sorted list of wing names present on disk (drawers collection only)."""
        if not self._is_drawers:
            return []
        try:
            indices = self._es.indices.get(index=self._wildcard)
            prefix_len = len(self._prefix)
            names = []
            for name in indices.keys():
                suffix = name[prefix_len:]
                # Exclude the structure index
                if suffix == "structure":
                    continue
                names.append(suffix)
            return sorted(names)
        except NotFoundError:
            return []

    def wing_count(self, wing: str) -> int:
        if not self._is_drawers:
            return 0
        try:
            return self._es.count(index=self._wing_index(wing))["count"]
        except NotFoundError:
            return 0

    def room_aggregation(self, wing: Optional[str] = None) -> dict:
        index = (
            (self._wing_index(wing) if wing else self._wildcard)
            if self._is_drawers
            else self._flat_index
        )
        body = {"size": 0, "aggs": {"rooms": {"terms": {"field": "room", "size": 10000}}}}
        try:
            resp = self._es.search(index=index, body=body)
        except NotFoundError:
            return {}
        return {b["key"]: b["doc_count"] for b in resp["aggregations"]["rooms"]["buckets"]}

    def taxonomy(self) -> dict:
        """Return {wing: {room: count}} using nested aggregation."""
        index = self._wildcard if self._is_drawers else self._flat_index
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
            resp = self._es.search(index=index, body=body)
        except NotFoundError:
            return {}
        result = {}
        for wb in resp["aggregations"]["wings"]["buckets"]:
            result[wb["key"]] = {rb["key"]: rb["doc_count"] for rb in wb["rooms"]["buckets"]}
        return result


# ---------------------------------------------------------------------------
# ElasticsearchBackend — BaseBackend factory
# ---------------------------------------------------------------------------


class ElasticsearchBackend(BaseBackend):
    """Backend factory that serves palaces as per-citadel namespaces."""

    name = "elasticsearch"
    spec_version = "1.0"
    capabilities = frozenset({"hybrid_search", "server_side_embeddings"})

    def __init__(self):
        self._clients: dict[str, Elasticsearch] = {}  # citadel → ES client
        self._configs: dict[str, MempalaceConfig] = {}
        self._lock = threading.Lock()

    @classmethod
    def detect(cls, path: str) -> bool:
        # ES is a server-mode backend; local path detection is not meaningful.
        return False

    def _client_for(self, palace: PalaceRef) -> tuple[Elasticsearch, MempalaceConfig]:
        # Each PalaceRef.id maps to a citadel namespace. The config reads env/config
        # at construction; if a caller needs multi-tenant per-palace creds, they can
        # override via options in a follow-up.
        citadel = palace.id
        with self._lock:
            if citadel in self._clients:
                return self._clients[citadel], self._configs[citadel]

            config = MempalaceConfig()
            if not config.es_api_key or (not config.es_url and not config.es_cloud_id):
                raise PalaceNotFoundError(
                    "Elasticsearch is not configured. Set ES_URL + ES_KEY "
                    "(or MEMPALACE_ES_CLOUD_ID + MEMPALACE_ES_API_KEY)."
                )

            if config.es_url:
                client = Elasticsearch(
                    hosts=config.es_url,
                    api_key=config.es_api_key,
                    request_timeout=120,
                )
            else:
                client = Elasticsearch(
                    cloud_id=config.es_cloud_id,
                    api_key=config.es_api_key,
                    request_timeout=120,
                )

            self._clients[citadel] = client
            self._configs[citadel] = config
            return client, config

    def get_collection(
        self,
        *,
        palace: PalaceRef,
        collection_name: str,
        create: bool = False,
        options: Optional[dict] = None,
    ) -> ESCollection:
        client, config = self._client_for(palace)
        return ESCollection(
            es=client,
            config=config,
            collection_name=collection_name,
            create=create,
        )

    def close_palace(self, palace: PalaceRef) -> None:
        with self._lock:
            client = self._clients.pop(palace.id, None)
            self._configs.pop(palace.id, None)
        if client is not None:
            try:
                client.close()
            except Exception:
                logger.exception("error closing ES client for palace %s", palace.id)

    def close(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
            self._configs.clear()
        for client in clients:
            try:
                client.close()
            except Exception:
                logger.exception("error closing ES client during backend shutdown")

    def health(self, palace: Optional[PalaceRef] = None) -> HealthStatus:
        if palace is None:
            return HealthStatus.healthy("no palace supplied; backend is a factory")
        try:
            client, _ = self._client_for(palace)
            resp = client.cluster.health()
            status = resp.get("status", "unknown")
            if status in ("green", "yellow"):
                return HealthStatus.healthy(f"cluster={status}")
            return HealthStatus.unhealthy(f"cluster={status}")
        except Exception as exc:
            return HealthStatus.unhealthy(f"health check failed: {exc}")
