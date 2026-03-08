# Zendesk Inline Help Auto-Sync

This project listens for Zendesk Guide article changes, rebuilds a target Help Center category, and publishes cleaned HTML plus heading indexes for inline help.

## What it does

When an article in the configured Zendesk category is created, updated, published, unpublished, or otherwise changed through a subscribed article event:

- receives the webhook
- verifies the Zendesk webhook signature
- fetches the changed article and checks whether it belongs to the target category
- fetches all articles in that category
- cleans the HTML
- assigns deterministic heading IDs
- rewrites internal anchors
- exports `guide.cleaned.html`, `headings.json`, and `headings.xlsx`

## Project structure

```text
zendesk-inline-help-sync/
├── .env
├── .env.example
├── requirements.txt
├── config.py
├── sync_category.py
├── process_article.py
├── rebuild_outputs.py
├── rebuild_category.py          # legacy entry point
├── app/
│   ├── processor.py             # legacy (kept for reference)
│   ├── webhook_app.py
│   └── zendesk_client.py
└── storage/
    ├── raw/
    ├── processed/
    ├── metadata/
    ├── published/
    └── logs/
```

### Module responsibilities

| Module | Purpose |
|---|---|
| `config.py` | Loads `.env`, exposes a `Config` dataclass with all settings and storage paths |
| `sync_category.py` | CLI entry point — fetches articles and rebuilds outputs |
| `process_article.py` | Per-article HTML cleaning, heading ID assignment, and link rewriting |
| `rebuild_outputs.py` | Category-level aggregation — combines articles and writes HTML / JSON / Excel |
| `app/webhook_app.py` | FastAPI webhook receiver for real-time Zendesk events |
| `app/zendesk_client.py` | Thin wrapper around the Zendesk Help Center API |

### Storage directories

| Directory | Contents |
|---|---|
| `storage/raw/` | Raw Zendesk API responses (future use) |
| `storage/processed/articles/` | Cleaned per-article HTML files |
| `storage/processed/` | Heading indexes (`headings.json`, `headings.xlsx`) |
| `storage/published/` | Final published artifacts (future use) |
| `storage/logs/` | Processing logs (future use) |

## Setup

### 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Install dependencies

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Fill in your Zendesk values in `.env`.

### 4. Run a one-time rebuild

```bash
python sync_category.py
```

### 5. Start the webhook receiver

```bash
uvicorn app.webhook_app:app --host 0.0.0.0 --port 8000 --reload
```

## Zendesk webhook target

Use this endpoint as the webhook destination:

```text
POST /zendesk/webhook
```

Example local URL with ngrok:

```text
https://YOUR-NGROK-SUBDOMAIN.ngrok.app/zendesk/webhook
```

## Output files

The script strictly exports articles that carry the `integration_id_X` label. 

```text
storage/
└── processed/
    ├── articles/
    │   └── integration_id_6c6a442f-3797-456e-29e6-a23da164c87f_38892370166679.html
    ├── headings.json
    └── headings.xlsx
```

## Notes

- **Filtering:** Only articles with an `integration_id_...` label are exported.
- **Naming:** Files are natively shaped around this integration ID (`<integration_id>_<zendesk_id>.html`).
- **Headings:** Heading IDs are deterministic and prefixed with the article slug to reduce collisions.
- **Excel Export:** `headings.xlsx` contains two sheets: `headings` and `broken_anchors`.
- **Consistency:** This script processes the full target category to ensure cross-references and indexes remain perfectly consistent.
