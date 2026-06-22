from app.lexical_search import LexicalIndex
from config import Config
lex = LexicalIndex(str(Config().lexical_index_dir))
lex.load()
for i in range(2):
    print("CHUNK", i)
    item = lex.retriever.corpus[i]
    print(type(item))
    print(item)
    print("---")
