import time
from app.chroma_store import OllamaEmbeddingFunction
emb = OllamaEmbeddingFunction(base_url="http://localhost:11434")
start = time.time()
res = emb(["This is a test of the embedding speed."])
print(f"Time: {time.time() - start:.3f}s")
