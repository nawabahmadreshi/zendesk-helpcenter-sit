import bm25s
print("tokenize parameters:", bm25s.tokenize.__code__.co_varnames)
print("retrieve parameters:", bm25s.BM25.retrieve.__code__.co_varnames)
