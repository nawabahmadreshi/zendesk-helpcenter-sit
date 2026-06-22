#!/usr/bin/env python3
"""
Script to index all generated Markdown guides (*.md) in the site/ directory
into ChromaDB and a BM25 Lexical Index for strict QA retrieval.
"""

import os
import sys
import json
import hashlib
from pathlib import Path
from dotenv import load_dotenv

# Prepend project root to sys.path to allow app imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

load_dotenv()

from config import Config
from app.embedding import get_chroma_collection, chunk_markdown
from app.lexical_search import LexicalIndex

import argparse

def index_all_md_guides(skip_vector: bool = False):
    cfg = Config()
    site_dir = ROOT / "site"
    if not site_dir.exists():
        print(f"Error: site/ directory does not exist. Run sync_zendesk.py first.")
        return

    print("Locating all Markdown guide files under site/...")
    md_files = list(site_dir.glob("**/*.md"))
    print(f"Found {len(md_files)} markdown files.")

    # Initialize Lexical Index
    lexical_dir = cfg.STORAGE_DIR / "site_lexical_index"
    if lexical_dir.exists():
        import shutil
        shutil.rmtree(lexical_dir)
    lexical_index = LexicalIndex(str(lexical_dir))

    all_chunks = []
    processed_count = 0

    print("Parsing and chunking Markdown files...")
    for md_file in md_files:
        # Ignore main index.html or other root files
        if md_file.parent == site_dir:
            continue

        slug = md_file.parent.name
        content = md_file.read_text(encoding="utf-8")
        
        # Parse title from the first header line or filename
        title = slug.replace("-", " ")
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Generate local article ID
        h = hashlib.sha1(slug.encode("utf-8")).hexdigest()[:12]
        article_id = f"site_{h}"

        metadata = {
            "article_id": article_id,
            "title": title,
            "integration_id": slug,
            "url": f"site/{slug}/index.html",
            "product_version": ""
        }

        # Chunk the markdown guide
        chunks = chunk_markdown(content, metadata)
        if chunks:
            all_chunks.extend(chunks)
            processed_count += 1
            if processed_count % 100 == 0:
                print(f"Parsed {processed_count}/{len(md_files)} files...")

    if not all_chunks:
        print("No document chunks extracted. Indexing skipped.")
        return

    print(f"\nExtracted {len(all_chunks)} chunks from {processed_count} files.")

    # 1. Add to Lexical BM25 Index (Free, local, instantaneous)
    print("\nBuilding BM25 Lexical search index...")
    lexical_index.add_documents(all_chunks)
    lexical_index.build_and_save()
    print("✅ BM25 Lexical search index built.")

    # 2. Add to ChromaDB Vector Index (Requires LLM embeddings, can hit rate limits)
    if not skip_vector:
        collection_name = "site_md_kb"
        persist_dir = str(cfg.vectordb_dir)
        print(f"\nInitializing Chroma DB collection: '{collection_name}' in {persist_dir}...")
        collection = get_chroma_collection(persist_dir, collection_name=collection_name)

        # Wipe the existing collection first for a clean build
        try:
            count = collection.count()
            if count > 0:
                print(f"Clearing {count} existing records in '{collection_name}' Chroma collection...")
                import chromadb
                client = chromadb.PersistentClient(path=persist_dir)
                client.delete_collection(name=collection_name)
                collection = get_chroma_collection(persist_dir, collection_name=collection_name)
        except Exception as e:
            print(f"Could not reset Chroma collection: {e}")

        print("Generating vector embeddings and saving to ChromaDB...")
        ids = [c["id"] for c in all_chunks]
        documents = [c["text"] for c in all_chunks]
        metadatas = [
            {
                "article_id": c["article_id"],
                "title": c["title"],
                "integration_id": c["integration_id"],
                "url": c["url"],
                "chunk_index": c["chunk_index"],
            }
            for c in all_chunks
        ]

        # Add to Chroma in batches to prevent API payload limit errors
        batch_size = 100
        for i in range(0, len(all_chunks), batch_size):
            end = min(i + batch_size, len(all_chunks))
            try:
                collection.add(
                    ids=ids[i:end],
                    documents=documents[i:end],
                    metadatas=metadatas[i:end]
                )
                if i % 500 == 0 or end == len(all_chunks):
                    print(f"Indexed vector batch {end}/{len(all_chunks)}...")
            except Exception as ex:
                print(f"Failed to index vector batch {i}:{end}: {ex}")
                print("Continuing with remaining batches...")

    print(f"\n✅ Indexing completed successfully!")
    print(f"- {processed_count} Markdown guides indexed.")
    print(f"- {len(all_chunks)} total chunks populated.")
    print(f"- BM25 Lexical Index: 'storage/site_lexical_index/'")
    if not skip_vector:
        print(f"- Chroma DB Collection: 'site_md_kb'")
    else:
        print(f"- Vector DB indexing was skipped (--skip-vector).")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Index Markdown guides into search databases.")
    parser.add_argument("--skip-vector", action="store_true", help="Skip ChromaDB vector indexing (run lexical indexing only)")
    args = parser.parse_args()
    index_all_md_guides(skip_vector=args.skip_vector)

