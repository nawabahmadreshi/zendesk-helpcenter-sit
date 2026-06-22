#!/usr/bin/env python3
"""
CLI tool to ingest local source documents (HTML/Text) into the AI knowledge base.
Supports manual version and integration ID tagging to handle archiving.
"""
import argparse
import os
import shutil
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Ensure we can import app modules
import sys
sys.path.append(os.getcwd())

load_dotenv()

from config import Config
from app.processor import render_clean_article_html
from app.embedding import embed_single_article
from bs4 import BeautifulSoup

def ingest_file(file_path: str, version: str, integration_id: str, title: str = None):
    cfg = Config()
    src = Path(file_path)
    if not src.exists():
        print(f"Error: File {file_path} not found.")
        return

    # 1. Prepare Archive Storage
    archive_dir = cfg.processed_dir / "articles" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # 2. Process Content
    content = src.read_text(encoding="utf-8")
    if src.suffix.lower() == ".html":
        soup = BeautifulSoup(content, "html.parser")
    else:
        # Wrap plain text in simple HTML structure
        soup = BeautifulSoup(f"<div>{content.replace(chr(10), '<br>')}</div>", "html.parser")

    # Use filename as title if none provided
    if not title:
        title = src.stem.replace("_", " ").title()

    # Generate a unique slug/ID for local files to avoid collision with Zendesk
    local_id = f"local_{uuid.uuid4().hex[:8]}"
    
    # Render with version metadata
    article_mock = {
        "id": local_id,
        "title": title,
        "slug": src.stem
    }
    
    clean_html = render_clean_article_html(article_mock, soup, product_version=version)
    
    # 3. Save to Archive
    # Filename format: {version}_{integration_id}_{local_id}.html
    target_filename = f"{version}_{integration_id}_{local_id}.html"
    target_path = archive_dir / target_filename
    target_path.write_text(clean_html, encoding="utf-8")
    
    print(f"Processed: {src.name} -> {target_path}")

    # 4. Index in Vector DB
    # We use a special collection for archives or just the general one?
    # For now, index into general KB but with version metadata.
    result = embed_single_article(target_path, str(cfg.vectordb_dir), cfg.GEMINI_API_KEY)
    
    print(f"Indexing Complete: {result.get('chunks_stored', 0)} chunks stored.")
    print(f"Local URL: http://localhost:8000/archive/{target_filename}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest local documents into AI knowledge base.")
    parser.add_argument("--file", required=True, help="Path to the source file (HTML/Text)")
    parser.add_argument("--version", required=True, help="Product version tag (e.g., v11)")
    parser.add_argument("--integration_id", default="global", help="Integration ID (default: global)")
    parser.add_argument("--title", help="Optional title for the document")

    args = parser.parse_args()
    ingest_file(args.file, args.version, args.integration_id, args.title)
