#!/usr/bin/env python3
"""
migrate_flat_to_wings.py — Migrate from flat index to per-wing indices.

Reads all drawers from the legacy `mempalace_drawers` index and re-indexes
them into per-wing indices (`mempalace_wing_{name}`), creating the structure
index along the way.

Usage:
    python -m mempalace.migrate_flat_to_wings [--batch-size 500]
"""

import argparse
import sys
from collections import defaultdict

from elasticsearch import Elasticsearch

from .config import MempalaceConfig
from .es_client import (
    STRUCTURE_MAPPING,
    _build_wing_mapping,
)

# The old flat index name to migrate from
LEGACY_INDEX = "mempalace_drawers"


def migrate(batch_size=500):
    """Migrate all drawers from flat index to per-wing indices."""
    config = MempalaceConfig()

    if not config.es_api_key or (not config.es_url and not config.es_cloud_id):
        print("Error: ES not configured. Set ES_URL + ES_KEY.")
        sys.exit(1)

    if config.es_url:
        es = Elasticsearch(hosts=config.es_url, api_key=config.es_api_key, request_timeout=120)
    else:
        es = Elasticsearch(
            cloud_id=config.es_cloud_id, api_key=config.es_api_key, request_timeout=120
        )

    print(f"\n{'=' * 55}")
    print("  MemCitadel Migration: Flat Index → Per-Wing Indices")
    print(f"{'=' * 55}\n")

    # Check legacy index exists
    if not es.indices.exists(index=LEGACY_INDEX):
        print(f"  No legacy index '{LEGACY_INDEX}' found. Nothing to migrate.")
        return

    total = es.count(index=LEGACY_INDEX)["count"]
    print(f"  Source: {LEGACY_INDEX} ({total} drawers)")

    if total == 0:
        print("  Nothing to migrate.")
        return

    # Ensure structure index
    structure_index = config.es_structure_index
    if not es.indices.exists(index=structure_index):
        es.indices.create(index=structure_index, body=STRUCTURE_MAPPING)
        print(f"  Created structure index: {structure_index}")

    wing_mapping = _build_wing_mapping(config)
    prefix = config.es_index_prefix
    wings_created = set()
    rooms_seen = defaultdict(set)

    print(f"  Target: {prefix}* indices")
    print(f"{'─' * 55}\n")

    # Scroll through all documents
    offset = 0
    migrated = 0
    while offset < total:
        body = {
            "query": {"match_all": {}},
            "size": batch_size,
            "from": offset,
            "_source": True,
        }
        resp = es.search(index=LEGACY_INDEX, body=body)
        hits = resp["hits"]["hits"]

        if not hits:
            break

        # Group by wing
        wing_batches = defaultdict(list)
        for hit in hits:
            source = hit["_source"]
            wing = source.get("wing", "default")
            wing_batches[wing].append((hit["_id"], source))

        # Index into per-wing indices
        for wing, docs in wing_batches.items():
            wing_index = f"{prefix}{wing}"

            # Create wing index if needed
            if wing not in wings_created:
                if not es.indices.exists(index=wing_index):
                    es.indices.create(index=wing_index, body=wing_mapping)
                    print(f"  Created wing index: {wing_index}")
                wings_created.add(wing)

                # Register wing in structure index
                es.index(
                    index=structure_index,
                    id=f"wing:{wing}",
                    body={"type": "wing", "name": wing},
                    op_type="create",
                    ignore=[409],
                )

            # Bulk index
            operations = []
            for doc_id, source in docs:
                operations.append({"index": {"_index": wing_index, "_id": doc_id}})
                operations.append(source)

                room = source.get("room")
                if room and room not in rooms_seen[wing]:
                    rooms_seen[wing].add(room)
                    es.index(
                        index=structure_index,
                        id=f"room:{wing}:{room}",
                        body={"type": "room", "name": room, "wing": wing},
                        op_type="create",
                        ignore=[409],
                    )

            if operations:
                es.bulk(operations=operations, refresh="wait_for")

        migrated += len(hits)
        offset += len(hits)
        print(f"  Migrated {migrated}/{total} drawers...")

    # Verify counts
    print(f"\n{'─' * 55}")
    print("  Verification:")
    new_total = es.count(index=f"{prefix}*")["count"]
    print(f"    Legacy index:     {total} drawers")
    print(f"    Per-wing indices: {new_total} drawers")

    for wing in sorted(wings_created):
        wing_count = es.count(index=f"{prefix}{wing}")["count"]
        room_count = len(rooms_seen[wing])
        print(f"    {prefix}{wing}: {wing_count} drawers, {room_count} rooms")

    if total == new_total:
        print("\n  Migration complete. Counts match.")
    else:
        print(f"\n  WARNING: Count mismatch! Legacy={total}, New={new_total}")

    print(f"  The legacy index '{LEGACY_INDEX}' has NOT been deleted.")
    print(f"  To remove it: DELETE /{LEGACY_INDEX}")
    print(f"\n{'=' * 55}\n")


def main():
    parser = argparse.ArgumentParser(description="Migrate from flat index to per-wing indices")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size (default: 500)")
    args = parser.parse_args()
    migrate(batch_size=args.batch_size)


if __name__ == "__main__":
    main()
