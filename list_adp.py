from app.lexical_search import LexicalIndex
from config import Config
cfg = Config()
lex = LexicalIndex(str(cfg.lexical_index_dir))

query = "ADP WFN"
results = lex.search_with_indices(query, top_k=50)
sections = set()
for r in results:
    title = r.get("metadata", {}).get("title", "")
    if "ADP WFN" in title:
        sections.add(r.get("text", "").split('\n')[1] if '\n' in r.get("text", "") else "")

for s in sorted(list(sections)):
    print(s)
