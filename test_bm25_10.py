import re
from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "ADP Workforce Now Connector Configuration"
l_results = lex.search_with_indices(query, top_k=50)

for i, x in enumerate(l_results[:10]):
    print(f"#{i+1} | Score: {x.get('score')} | Title: {x.get('metadata', {}).get('title', '')}")
