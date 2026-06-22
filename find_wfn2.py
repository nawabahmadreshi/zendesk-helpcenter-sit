import json
with open('storage/lexical_index/corpus.jsonl', 'r') as f:
    for line in f:
        doc = json.loads(line)
        title = doc.get("metadata", {}).get("title", "")
        if "ADP" in title:
            print(f"TITLE: {title}")
