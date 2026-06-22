from app.reranker import ReRanker
from app.lexical_search import LexicalIndex
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "How do I configure ADP WFN integration?"
l_results = lex.search_with_indices("ADP Workforce Now Configuration Guide", top_k=50)

r = ReRanker()
ranked = r.rerank(query, l_results, top_k=10)
for i, x in enumerate(ranked):
    title = x.get('metadata', {}).get('title', '')
    text = x.get("text", "").split('\n')[1] if '\n' in x.get("text", "") else ""
    score = x.get('rerank_score', 0)
    print(f"#{i+1} [{text}] - Score: {score:.3f}")
