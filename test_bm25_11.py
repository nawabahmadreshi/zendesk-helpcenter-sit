from app.lexical_search import LexicalIndex
from app.reranker import rerank_results
from config import Config

lex = LexicalIndex(str(Config().lexical_index_dir))
query = "ADP Workforce Now Connector Configuration"
l_results = lex.search_with_indices(query, top_k=50)

reranked = rerank_results(query, l_results, top_n=10)

for i, r in enumerate(reranked):
    title = r.get("metadata", {}).get("title", "")
    text = r.get("text", "")
    score = r.get("rerank_score", 0)
    print(f"#{i+1} | Score: {score} | Title: {title}")
    print("Preview:", text.replace('\n', ' ')[:100])
