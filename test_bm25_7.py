import re
from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "How do I configure ADP Workforce Now integration?"
l_results = lex.search_with_indices(query, top_k=1500)

query_tokens = set(re.findall(r'\w+', query.lower()))
query_tokens.add('configuration') 

for r in l_results:
    title = r.get('metadata', {}).get('title', '').lower()
    title_tokens = set(re.findall(r'\w+', title))
    overlap = len(query_tokens.intersection(title_tokens))
    if overlap >= 3:
        r['score'] *= (1.0 + (overlap * 0.5))

l_results = sorted(l_results, key=lambda x: x.get('score', 0), reverse=True)

for i, x in enumerate(l_results[:10]):
    print(f"#{i+1} | Score: {x.get('score')} | Title: {x.get('metadata', {}).get('title', '')}")
