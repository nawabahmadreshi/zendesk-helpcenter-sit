from app.lexical_search import LexicalIndex
from config import Config
cfg = Config()
lex = LexicalIndex(str(cfg.lexical_index_dir))

query = "ADP Workforce Now Configuration Guide"
results = lex.search_with_indices(query, top_k=50)
sections = set()
for r in results:
    title = r.get("metadata", {}).get("title", "")
    if title == "ADP Workforce Now Configuration Guide":
        text = r.get("text", "").split('\n')[1] if '\n' in r.get("text", "") else ""
        sections.add(text)
for s in sorted(list(sections)):
    print(s)
