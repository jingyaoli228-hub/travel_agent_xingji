"""Copy embedded Chroma collections to a Chroma HTTP server without re-embedding.

The script only reads the source directory and uses idempotent upserts on the
target. It preserves IDs, documents, metadata, URIs and the stored embedding
vectors. Source and target must run the same pinned Chroma version.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="./data/chroma")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8001)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--manifest", default="./runtime/chroma-migration-manifest.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not (source_path / "chroma.sqlite3").exists():
        raise SystemExit(f"not a Chroma persistence directory: {source_path}")
    source = chromadb.PersistentClient(path=str(source_path))
    target = None if args.dry_run else chromadb.HttpClient(host=args.host, port=args.port)
    manifest = {"source": str(source_path), "collections": {}}

    for descriptor in source.list_collections():
        collection = source.get_collection(descriptor.name)
        count = collection.count()
        target_collection = None
        if target:
            target_collection = target.get_or_create_collection(
                descriptor.name,
                metadata=collection.metadata,
                configuration=collection.configuration_json,
            )
        dimension = None
        for offset in range(0, count, args.batch_size):
            rows = collection.get(
                limit=args.batch_size,
                offset=offset,
                include=["documents", "metadatas", "embeddings", "uris"],
            )
            embeddings = rows.get("embeddings")
            if embeddings is None:
                raise RuntimeError(f"collection {descriptor.name} did not return embeddings")
            embeddings = embeddings.tolist() if hasattr(embeddings, "tolist") else embeddings
            if embeddings and dimension is None:
                dimension = len(embeddings[0])
            if target_collection and rows["ids"]:
                kwargs = {
                    "ids": rows["ids"], "embeddings": embeddings,
                    "documents": rows.get("documents"), "metadatas": rows.get("metadatas"),
                }
                if rows.get("uris") and any(uri is not None for uri in rows["uris"]):
                    kwargs["uris"] = rows["uris"]
                target_collection.upsert(**kwargs)
        target_count = target_collection.count() if target_collection else None
        if target_count is not None and target_count < count:
            raise RuntimeError(f"target count mismatch for {descriptor.name}: {target_count} < {count}")
        manifest["collections"][descriptor.name] = {
            "source_count": count, "target_count": target_count, "embedding_dimension": dimension,
            "configuration": collection.configuration_json,
        }
        print(f"{descriptor.name}: {count} records, dimension={dimension}, target={target_count}")

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

