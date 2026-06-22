import re
from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
original_query = "How do I configure ADP WFN integration?"

acronyms = {
    r'\bwfn\b': 'Workforce Now',
    r'\boim\b': 'Oracle Identity Manager'
}
query = original_query
for pattern, replacement in acronyms.items():
    query = re.sub(pattern, replacement, query, flags=re.IGNORECASE)

l_results = lex.search_with_indices(query, top_k=500)

query_tokens = set(re.findall(r'\w+', query.lower()))
if "configure" in query_tokens: query_tokens.add("configuration")
if "configuration" in query_tokens: query_tokens.add("configure")

for r in l_results:
    title = r.get('metadata', {}).get('title', '').lower()
    title_tokens = set(re.findall(r'\w+', title))
    overlap = len(query_tokens.intersection(title_tokens))
    if overlap >= 3:
        r['score'] *= (1.0 + (overlap * 0.5))

l_results = sorted(l_results, key=lambda x: x.get('score', 0), reverse=True)

found = False
for i, x in enumerate(l_results[:50]):
    title = x.get('metadata', {}).get('title', '')
    if title == "ADP Workforce Now Configuration Guide":
        print(f"#{i+1} | {title} | {x.get('text', '').replace(chr(10), ' ')[:50]}")
        found = True
if not found:
    print("NOT FOUND IN TOP 50")
