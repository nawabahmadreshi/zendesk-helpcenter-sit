# Quick Run Guide (zendesk-inline-help-sync)

This is a fast setup guide for developers or admins to get the script running locally from scratch.

## Prerequisites
1. **Python 3.9+** installed on your Mac/PC (`python3 --version`).
2. A **Zendesk Admin Email** and **API Token**.
3. (Optional) A **Slack Webhook URL** if you want notifications.

## Step-by-Step Setup

**1. Open a terminal and navigate to the folder:**
```bash
cd path/to/zendesk-inline-help-sync
```

**2. Create a virtual environment & install the required packages:**
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**3. Set up your secrets:**
You need to duplicate the `.env.example` file and name it `.env`.
```bash
cp .env.example .env
```
Open `.env` in any text editor and paste in your Zendesk keys, category ID, and Slack webhook url.

**4. Run it:**
Once the `.env` file is saved, simply run:
```bash
python sync_category.py
```

## Expected Behavior
- The script checks the Zendesk Category ID you provided.
- It sees if any articles with an `integration_id_X` label were updated.
- If they were updated, it cleans their HTML, injects IDs, and extracts them natively to `storage/processed/articles/`.
- If a Slack Webhook was provided, it sends an alert to your channel!
