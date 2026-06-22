import json
found = False
with open('storage/lexical_index/corpus.jsonl', 'r') as f:
    for line in f:
        doc = json.loads(line)
        title = doc.get("metadata", {}).get("title", "")
        text = doc.get("text", "")
        if "ADP Workforce Now Configuration Guide" == title and "Connector Configuration" in text:
            print("FOUND IT!")
            print(text.replace("\n", " ")[:200])
            found = True

if not found:
    print("Not found in corpus.jsonl!")
