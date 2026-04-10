"""
test_es_integration.py — Integration tests for the Elasticsearch backend.

Tests the full stack: PalaceClient routing, ESCollection CRUD, hybrid search,
aggregation helpers, and end-to-end flows against a real ES deployment.

Requires ES_URL and ES_KEY environment variables to be set.
Uses unique test index prefixes to avoid colliding with production data.

Run with: pytest tests/test_es_integration.py -v
"""

import os
import uuid

import pytest

# Skip entire module if ES is not configured
pytestmark = pytest.mark.skipif(
    not os.environ.get("ES_URL") or not os.environ.get("ES_KEY"),
    reason="ES_URL and ES_KEY not set — skipping ES integration tests",
)


@pytest.fixture(scope="module")
def test_prefix():
    """Unique index prefix for this test run to avoid collisions."""
    return f"test_mempalace_{uuid.uuid4().hex[:8]}_wing_"


@pytest.fixture(scope="module")
def test_structure_index(test_prefix):
    return f"test_mempalace_{test_prefix.split('_wing_')[0].split('_', 2)[-1]}_structure"


@pytest.fixture(scope="module")
def es_client():
    """Raw Elasticsearch client for setup/teardown."""
    from elasticsearch import Elasticsearch

    return Elasticsearch(
        hosts=os.environ["ES_URL"],
        api_key=os.environ["ES_KEY"],
        request_timeout=120,
    )


@pytest.fixture(scope="module")
def palace(es_client, test_prefix, monkeypatch_module):
    """A PalaceClient with unique test indices."""
    from memcitadel.config import MempalaceConfig
    from memcitadel.es_client import PalaceClient, STRUCTURE_MAPPING

    config = MempalaceConfig()
    # Override prefixes to use test-specific indices
    config._test_prefix = test_prefix
    structure_index = test_prefix.replace("_wing_", "_structure")

    # Create structure index
    if not es_client.indices.exists(index=structure_index):
        es_client.indices.create(index=structure_index, body=STRUCTURE_MAPPING)

    client = PalaceClient(es_client, config)
    client._prefix = test_prefix
    client._wildcard = f"{test_prefix}*"
    client._structure_index = structure_index

    yield client

    # Cleanup: delete all test indices
    try:
        es_client.indices.delete(index=f"{test_prefix}*", ignore_unavailable=True)
        es_client.indices.delete(index=structure_index, ignore_unavailable=True)
    except Exception:
        pass


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch (pytest's is function-scoped)."""
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    yield mp
    mp.undo()


# ---------------------------------------------------------------------------
# Unit tests: _extract_wing_from_where
# ---------------------------------------------------------------------------


class TestExtractWingFromWhere:
    def test_none(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where(None)
        assert wing is None
        assert remaining is None

    def test_empty_dict(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where({})
        assert wing is None
        assert remaining is None

    def test_simple_wing(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where({"wing": "code"})
        assert wing == "code"
        assert remaining is None

    def test_wing_and_room(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where(
            {"$and": [{"wing": "code"}, {"room": "testing"}]}
        )
        assert wing == "code"
        assert remaining == {"room": "testing"}

    def test_room_only(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where({"room": "testing"})
        assert wing is None
        assert remaining == {"room": "testing"}

    def test_source_file_only(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where({"source_file": "/path/to/file.py"})
        assert wing is None
        assert remaining == {"source_file": "/path/to/file.py"}

    def test_and_wing_only(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where({"$and": [{"wing": "code"}]})
        assert wing == "code"
        assert remaining is None

    def test_and_multiple_non_wing(self):
        from memcitadel.es_client import _extract_wing_from_where

        wing, remaining = _extract_wing_from_where(
            {"$and": [{"wing": "code"}, {"room": "auth"}, {"hall": "hall_facts"}]}
        )
        assert wing == "code"
        assert remaining == {"$and": [{"room": "auth"}, {"hall": "hall_facts"}]}


# ---------------------------------------------------------------------------
# Unit tests: _translate_where
# ---------------------------------------------------------------------------


class TestTranslateWhere:
    def test_none(self):
        from memcitadel.es_client import _translate_where

        assert _translate_where(None) == []

    def test_simple(self):
        from memcitadel.es_client import _translate_where

        result = _translate_where({"wing": "code"})
        assert result == [{"term": {"wing": "code"}}]

    def test_and(self):
        from memcitadel.es_client import _translate_where

        result = _translate_where({"$and": [{"wing": "code"}, {"room": "auth"}]})
        assert result == [{"term": {"wing": "code"}}, {"term": {"room": "auth"}}]


# ---------------------------------------------------------------------------
# Integration tests: PalaceClient CRUD
# ---------------------------------------------------------------------------


class TestPalaceClientCRUD:
    def test_add_and_count(self, palace):
        palace.add(
            ids=["test_drawer_1"],
            documents=["This is a test document about authentication"],
            metadatas=[{"wing": "test_wing_a", "room": "auth", "added_by": "test"}],
        )
        assert palace.count() >= 1

    def test_add_second_wing(self, palace):
        palace.add(
            ids=["test_drawer_2"],
            documents=["This document is about billing and invoices"],
            metadatas=[{"wing": "test_wing_b", "room": "billing", "added_by": "test"}],
        )
        assert palace.count() >= 2

    def test_get_by_id(self, palace):
        result = palace.get(ids=["test_drawer_1"], include=["documents", "metadatas"])
        assert result["ids"] == ["test_drawer_1"]
        assert "authentication" in result["documents"][0]
        assert result["metadatas"][0]["wing"] == "test_wing_a"
        assert result["metadatas"][0]["room"] == "auth"

    def test_get_by_wing_filter(self, palace):
        result = palace.get(
            where={"wing": "test_wing_a"}, include=["documents", "metadatas"]
        )
        assert len(result["ids"]) >= 1
        assert all(m["wing"] == "test_wing_a" for m in result["metadatas"])

    def test_get_by_wing_and_room(self, palace):
        result = palace.get(
            where={"$and": [{"wing": "test_wing_b"}, {"room": "billing"}]},
            include=["metadatas"],
        )
        assert len(result["ids"]) >= 1
        assert all(m["room"] == "billing" for m in result["metadatas"])

    def test_get_cross_wing(self, palace):
        result = palace.get(include=["metadatas"])
        wings = {m["wing"] for m in result["metadatas"]}
        assert "test_wing_a" in wings
        assert "test_wing_b" in wings

    def test_upsert_overwrites(self, palace):
        palace.upsert(
            ids=["test_drawer_1"],
            documents=["Updated document about OAuth2 authentication"],
            metadatas=[{"wing": "test_wing_a", "room": "auth", "added_by": "test"}],
        )
        result = palace.get(ids=["test_drawer_1"], include=["documents"])
        assert "OAuth2" in result["documents"][0]

    def test_delete(self, palace):
        palace.add(
            ids=["test_drawer_delete_me"],
            documents=["This will be deleted"],
            metadatas=[{"wing": "test_wing_a", "room": "temp", "added_by": "test"}],
        )
        palace.delete(ids=["test_drawer_delete_me"])
        result = palace.get(ids=["test_drawer_delete_me"], include=["documents"])
        assert len(result["ids"]) == 0


# ---------------------------------------------------------------------------
# Integration tests: Hybrid search
# ---------------------------------------------------------------------------


class TestPalaceClientSearch:
    def test_query_hybrid(self, palace):
        result = palace.query(
            query_texts=["authentication OAuth"],
            n_results=5,
            include=["documents", "metadatas", "distances"],
        )
        assert len(result["ids"][0]) >= 1
        assert len(result["documents"][0]) >= 1
        assert len(result["distances"][0]) >= 1

    def test_query_with_wing_filter(self, palace):
        result = palace.query(
            query_texts=["billing invoices"],
            n_results=5,
            where={"wing": "test_wing_b"},
            include=["documents", "metadatas", "distances"],
        )
        assert len(result["ids"][0]) >= 1
        assert all(m["wing"] == "test_wing_b" for m in result["metadatas"][0])

    def test_query_with_wing_and_room_filter(self, palace):
        result = palace.query(
            query_texts=["authentication"],
            n_results=5,
            where={"$and": [{"wing": "test_wing_a"}, {"room": "auth"}]},
            include=["metadatas"],
        )
        assert len(result["ids"][0]) >= 1
        assert all(m["room"] == "auth" for m in result["metadatas"][0])

    def test_query_vector_only(self, palace):
        result = palace.query_vector_only(
            query_texts=["authentication login"],
            n_results=5,
            include=["documents", "distances"],
        )
        assert len(result["ids"][0]) >= 1

    def test_query_no_results(self, palace):
        result = palace.query(
            query_texts=["xyzzy_nonexistent_term_12345"],
            n_results=5,
            where={"wing": "nonexistent_wing"},
            include=["documents"],
        )
        assert len(result["ids"][0]) == 0

    def test_distance_ordering(self, palace):
        result = palace.query(
            query_texts=["authentication"],
            n_results=5,
            include=["distances"],
        )
        distances = result["distances"][0]
        if len(distances) >= 2:
            # First result should have lowest distance (best match)
            assert distances[0] <= distances[1]


# ---------------------------------------------------------------------------
# Integration tests: Aggregation helpers
# ---------------------------------------------------------------------------


class TestPalaceClientAggregations:
    def test_list_wing_names(self, palace):
        wings = palace.list_wing_names()
        assert "test_wing_a" in wings
        assert "test_wing_b" in wings

    def test_wing_count(self, palace):
        count_a = palace.wing_count("test_wing_a")
        count_b = palace.wing_count("test_wing_b")
        assert count_a >= 1
        assert count_b >= 1

    def test_wing_count_nonexistent(self, palace):
        count = palace.wing_count("nonexistent_wing")
        assert count == 0

    def test_room_aggregation_all(self, palace):
        rooms = palace.room_aggregation()
        assert "auth" in rooms
        assert "billing" in rooms

    def test_room_aggregation_filtered(self, palace):
        rooms = palace.room_aggregation("test_wing_a")
        assert "auth" in rooms
        assert "billing" not in rooms

    def test_taxonomy(self, palace):
        tax = palace.taxonomy()
        assert "test_wing_a" in tax
        assert "test_wing_b" in tax
        assert "auth" in tax["test_wing_a"]
        assert "billing" in tax["test_wing_b"]


# ---------------------------------------------------------------------------
# Integration tests: Structure index
# ---------------------------------------------------------------------------


class TestStructureIndex:
    def test_wing_registered(self, palace, es_client):
        resp = es_client.get(index=palace._structure_index, id="wing:test_wing_a", ignore=[404])
        assert resp.get("found", False)
        assert resp["_source"]["type"] == "wing"
        assert resp["_source"]["name"] == "test_wing_a"

    def test_room_registered(self, palace, es_client):
        resp = es_client.get(index=palace._structure_index, id="room:test_wing_a:auth", ignore=[404])
        assert resp.get("found", False)
        assert resp["_source"]["type"] == "room"
        assert resp["_source"]["wing"] == "test_wing_a"

    def test_second_wing_registered(self, palace, es_client):
        resp = es_client.get(index=palace._structure_index, id="wing:test_wing_b", ignore=[404])
        assert resp.get("found", False)


# ---------------------------------------------------------------------------
# Integration tests: Wing isolation
# ---------------------------------------------------------------------------


class TestWingIsolation:
    def test_wing_a_search_does_not_return_wing_b(self, palace):
        result = palace.query(
            query_texts=["billing invoices"],
            n_results=10,
            where={"wing": "test_wing_a"},
            include=["metadatas"],
        )
        for meta in result["metadatas"][0]:
            assert meta["wing"] == "test_wing_a"

    def test_wing_b_search_does_not_return_wing_a(self, palace):
        result = palace.query(
            query_texts=["authentication"],
            n_results=10,
            where={"wing": "test_wing_b"},
            include=["metadatas"],
        )
        for meta in result["metadatas"][0]:
            assert meta["wing"] == "test_wing_b"

    def test_cross_wing_search_returns_both(self, palace):
        result = palace.query(
            query_texts=["document"],
            n_results=10,
            include=["metadatas"],
        )
        wings = {m["wing"] for m in result["metadatas"][0]}
        assert len(wings) >= 2


# ---------------------------------------------------------------------------
# Integration tests: ChromaDB response format compatibility
# ---------------------------------------------------------------------------


class TestResponseFormat:
    def test_get_format_flat_lists(self, palace):
        """get() should return flat lists (ChromaDB compat)."""
        result = palace.get(ids=["test_drawer_1"], include=["documents", "metadatas"])
        assert isinstance(result["ids"], list)
        assert isinstance(result["ids"][0], str)
        assert isinstance(result["documents"], list)
        assert isinstance(result["documents"][0], str)
        assert isinstance(result["metadatas"], list)
        assert isinstance(result["metadatas"][0], dict)

    def test_query_format_nested_lists(self, palace):
        """query() should return nested lists (ChromaDB compat)."""
        result = palace.query(
            query_texts=["test"], n_results=5, include=["documents", "metadatas", "distances"]
        )
        assert isinstance(result["ids"], list)
        assert isinstance(result["ids"][0], list)
        assert isinstance(result["documents"], list)
        assert isinstance(result["documents"][0], list)
        assert isinstance(result["distances"], list)
        assert isinstance(result["distances"][0], list)

    def test_get_empty_result(self, palace):
        result = palace.get(ids=["nonexistent_id_xyz"], include=["documents"])
        assert result["ids"] == []

    def test_query_empty_result(self, palace):
        result = palace.query(
            query_texts=["xyzzy"],
            n_results=5,
            where={"wing": "nonexistent"},
            include=["documents", "distances"],
        )
        assert result["ids"] == [[]]
