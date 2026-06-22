from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "How do I configure ADP Workforce Now integration?"
l_results = lex.search_with_indices(query, top_k=5000)

for i, x in enumerate(l_results):
    title = x.get('metadata', {}).get('title', '')
    if title == "ADP Workforce Now Configuration Guide":
        text = x.get('text', '')
        if "Connector Configuration" in text:
            print(f"FOUND IT at Rank #{i+1} | Score: {x.get('score')}")
            print(text[:200].replace('\n', ' '))
