from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "ADP Workforce Now Configuration Guide - Connector Configuration"
l_results = lex.search_with_indices(query, top_k=5000)

found_chunks = []
for i, x in enumerate(l_results):
    title = x.get('metadata', {}).get('title', '')
    if title == "ADP Workforce Now Configuration Guide":
        text = x.get('text', '')
        if "Connector Configuration" in text:
            print(f"FOUND IT at Rank #{i+1} | Score: {x.get('score')}")
            print(text[:200].replace('\n', ' '))
            found_chunks.append(x)

print(f"Total chunks found with 'Connector Configuration': {len(found_chunks)}")
