#!/usr/bin/env python3
import os
import re
import pathlib
from bs4 import BeautifulSoup
from openpyxl import Workbook

ROOT = pathlib.Path(__file__).resolve().parents[1]
SITE_DIR = ROOT / "site"

def get_doc_title(md_file: pathlib.Path, folder_name: str) -> str:
    """Read the first H1 heading from the markdown file to get the document title."""
    if md_file.exists():
        try:
            content = md_file.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    if title:
                        return title
        except Exception:
            pass
    # Fallback to slug-based title
    return folder_name.replace("-", " ")

def migrate_md_file(md_file: pathlib.Path, title: str):
    """Prepend the title to all subheadings in the markdown file."""
    if not md_file.exists():
        return
    
    content = md_file.read_text(encoding="utf-8")
    lines = content.splitlines()
    new_lines = []
    first_heading_seen = False
    
    for line in lines:
        match = re.match(r'^(#+)\s+(.*)', line)
        if match:
            hashes = match.group(1)
            heading_text = match.group(2).strip()
            
            if not first_heading_seen:
                # The first heading is the main document title, leave it alone
                first_heading_seen = True
                new_lines.append(line)
            else:
                # Subheading: prepend title if not already present
                if not heading_text.lower().startswith(title.lower()):
                    new_lines.append(f"{hashes} {title} - {heading_text}")
                else:
                    new_lines.append(line)
        else:
            new_lines.append(line)
            
    md_file.write_text("\n".join(new_lines), encoding="utf-8")

def migrate_html_file(html_file: pathlib.Path, title: str) -> list:
    """Prepend the title to headings in HTML, write it back, and return a list of headings for Excel."""
    if not html_file.exists():
        return []
    
    content = html_file.read_text(encoding="utf-8")
    soup = BeautifulSoup(content, "html.parser")
    
    headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
    
    first_h1_seen = False
    excel_headings = []
    
    for h in headings:
        # The main title H1 is the first heading in body
        if h.name == 'h1' and not first_h1_seen:
            first_h1_seen = True
            continue
            
        h_text = h.get_text(strip=True)
        if h_text:
            # Prepend title if not already present
            if not h_text.lower().startswith(title.lower()):
                h_text_new = f"{title} - {h_text}"
                h.clear()
                h.append(h_text_new)
            else:
                h_text_new = h_text
                
            excel_headings.append({
                "level": h.name.upper(),
                "text": h_text_new,
                "id": h.get("id", "")
            })
            
    html_file.write_text(str(soup), encoding="utf-8")
    return excel_headings

def write_headings_excel(headings: list, out_xlsx: pathlib.Path):
    """Write headings metadata to excel sheet."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Headings"
    ws.append(["Heading", "Level", "ID", "URL"])

    # Attempt to load SITE_BASE from .env or config
    SITE_BASE = os.environ.get("SITE_BASE", "").rstrip("/")
    slug = out_xlsx.parent.name
    page_url = f"{SITE_BASE}/{slug}/" if SITE_BASE else ""

    for h in headings:
        hid = h["id"]
        url = f"{page_url}#{hid}" if page_url else f"#{hid}"
        ws.append([h["text"], h["level"], hid, url])

    wb.save(out_xlsx)

def main():
    if not SITE_DIR.exists():
        print(f"Error: {SITE_DIR} directory does not exist.")
        return

    print("Locating all guides under site/...")
    folders = [f for f in SITE_DIR.iterdir() if f.is_dir() and not f.name.startswith(".")]
    print(f"Found {len(folders)} guide directories to migrate.")

    count = 0
    for folder in folders:
        slug = folder.name
        md_file = folder / f"{slug}.md"
        html_file = folder / "index.html"
        xlsx_file = folder / "headings.xlsx"
        
        # Determine title
        title = get_doc_title(md_file, slug)
        
        # Migrate MD
        migrate_md_file(md_file, title)
        
        # Migrate HTML
        excel_headings = migrate_html_file(html_file, title)
        
        # Re-generate XLSX if it exists or if we found headings
        if xlsx_file.exists() or excel_headings:
            write_headings_excel(excel_headings, xlsx_file)
            
        count += 1
        if count % 100 == 0:
            print(f"Migrated {count}/{len(folders)} guides...")

    print(f"\n✅ Headings migration completed for {count} guides.")

if __name__ == "__main__":
    main()
