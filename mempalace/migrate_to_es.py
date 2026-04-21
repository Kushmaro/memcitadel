#!/usr/bin/env python3
"""
migrate_to_es.py — One-time migration from ChromaDB to Elasticsearch Serverless.

Reads all drawers from the local ChromaDB palace and bulk-indexes them into ES.
Embeddings are regenerated server-side by the ES Inference API.

Usage:
    python -m mempalace.migrate_to_es [--palace /path/to/palace]
"""

import argparse
import sys
import time

try:
    import chromadb
except ImportError:
    print("Error: chromadb is required for migration. Install it with: pip install chromadb")
    sys.exit(1)

from .backends.base import PalaceRef
from .backends.elasticsearch import ElasticsearchBackend
from .config import MempalaceConfig


def migrate(palace_path: str = None, batch_size: int = 500):
    """Migrate all drawers from ChromaDB to Elasticsearch."""
    config = MempalaceConfig()
    palace_path = palace_path or config.palace_path

    # Open ChromaDB source
    print(f"\n{'=' * 55}")
    print("  MemPalace Migration: ChromaDB → Elasticsearch")
    print(f"{'=' * 55}\n")
    print(f"  Source:  ChromaDB at {palace_path}")

    try:
        chroma_client = chromadb.PersistentClient(path=palace_path)
        chroma_col = chroma_client.get_collection("mempalace_drawers")
    except Exception as e:
        print(f"  Error: Cannot open ChromaDB palace: {e}")
        sys.exit(1)

    total = chroma_col.count()
    print(f"  Drawers: {total}")

    if total == 0:
        print("  Nothing to migrate.")
        return

    # Connect to ES destination
    try:
        es_col = ElasticsearchBackend().get_collection(
            palace=PalaceRef(id=palace_path, local_path=palace_path),
            collection_name="mempalace_drawers",
            create=True,
        )
    except Exception as e:
        print(f"  Error: Cannot connect to Elasticsearch: {e}")
        print("  Check ES_URL + ES_KEY (or MEMPALACE_ES_CLOUD_ID + MEMPALACE_ES_API_KEY) env vars.")
        sys.exit(1)

    print(f"  Target:  ES index prefix '{config.es_index_prefix}'")
    print(f"{'─' * 55}\n")

    # Migrate in batches
    offset = 0
    migrated = 0
    errors = 0

    while offset < total:
        batch = chroma_col.get(
            limit=batch_size,
            offset=offset,
            include=["documents", "metadatas"],
        )

        batch_ids = batch["ids"]
        batch_docs = batch["documents"]
        batch_metas = batch["metadatas"]

        if not batch_ids:
            break

        try:
            es_col.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
            migrated += len(batch_ids)
            print(f"  Migrated {migrated}/{total} drawers...")
        except Exception as e:
            error_str = str(e)
            if "429" in error_str:
                # Rate limited — back off and retry
                print("  Rate limited, backing off...")
                time.sleep(5)
                try:
                    es_col.upsert(ids=batch_ids, documents=batch_docs, metadatas=batch_metas)
                    migrated += len(batch_ids)
                    print(f"  Migrated {migrated}/{total} drawers (retry)...")
                except Exception as retry_e:
                    errors += len(batch_ids)
                    print(f"  Error on retry: {retry_e}")
            else:
                errors += len(batch_ids)
                print(f"  Error: {e}")

        offset += len(batch_ids)

    print(f"\n{'=' * 55}")
    print("  Migration complete.")
    print(f"  Migrated: {migrated}")
    if errors:
        print(f"  Errors:   {errors}")
    print(f"{'=' * 55}\n")


def main():
    parser = argparse.ArgumentParser(description="Migrate MemPalace from ChromaDB to Elasticsearch")
    parser.add_argument("--palace", metavar="PATH", help="Path to ChromaDB palace directory")
    parser.add_argument("--batch-size", type=int, default=500, help="Batch size (default: 500)")
    args = parser.parse_args()

    migrate(palace_path=args.palace, batch_size=args.batch_size)


if __name__ == "__main__":
    main()
