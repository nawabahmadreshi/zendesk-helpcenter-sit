from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "ADP Workforce Now Configuration Guide - Connector Configuration"
l_results = lex.search_with_indices(query, top_k=50)

for i, x in enumerate(l_results):
    title = x.get('metadata', {}).get('title', '')
    text = x.get('text', '').replace("\n", " ")[:100]
    print(f"Rank #{i+1} | Score: {x.get('score')} | Title: {title}")
    print("Text preview:", text)
