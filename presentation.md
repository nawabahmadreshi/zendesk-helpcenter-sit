# Zendesk Inline Help Sync: Project Presentation

## 🎯 The Objective
To create a local agent workspace that fetches Guide articles from Zendesk, selectively cleans and formats them for inline help, and exports them directly to a reliable, flat-file structure mapping to `integration_id`s.

## 🏗️ Architecture Restructure
The project was migrated from a complex package approach to an easy-to-use, flat-file service runner layout:

- **`config.py`**: A centralized environment configuration node that handles fetching `.env` variables and builds the Zendesk client connection.
- **`sync_category.py`**: The main execution engine. Run this manually or repeatedly to pull, process, and dump the targeted Help Center category.
- **`process_article.py`**: The HTML cleaning brain. It strips out inline styles, removes Zendesk clutter (`.article-votes`, `nav` tags), and mathematically ensures deterministic heading anchors. This guarantees a safe HTML footprint for external embedding.
- **`rebuild_outputs.py`**: The core data pipeline. It evaluates the Zendesk articles against our criteria and orchestrates the creation of the `headings.json` and `.xlsx` artifacts tracking broken internal links.

## 💾 The Storage Layer
The output artifacts were given heavily defined roles within the `/storage/` tree:
```text
storage/
├── processed/
│   ├── articles/           ← The 100% clean, exportable HTML files
│   ├── headings.json       ← Heading tag telemetry data
│   └── headings.xlsx       ← Spreadsheets capturing headings & broken links
├── raw/                    ← Reserved for API response staging
├── metadata/               
├── published/              
└── logs/                   
```

## 🔍 The Extractor Filter & Output Format
We implemented a strict publishing protocol.

1. **Filtering:** The script loops through all articles inside the selected Zendesk category. However, **it ignores everything** except the articles explicitly tagged with `integration_id_X` within Zendesk.
2. **Naming Convention:** Instead of merging everything into one giant block, the articles maintain total autonomy. They are exported natively under `<integration_label>_<zendesk_id>.html`. 

## ✅ Success Run
In a live test against category `19082031599383` (84 available articles), only `Integration test doc` possessed the integration_id label. The engine successfully extracted, scrubbed, and processed `integration_id_6c6a442f-3797-456e-29e6-a23da164c87f_38892370166679.html` and placed it safely inside `/processed/articles/`. 
