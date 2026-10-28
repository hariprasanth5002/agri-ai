from models.embedding_model import EmbeddingModel
from rag.vector_search import VectorSearchEngine

embedder = EmbeddingModel()
vector_db = VectorSearchEngine()

query = "treat tomato early blight"

embedding = embedder.generate_embedding(query)

results = vector_db.search(embedding=embedding)

print("\n=== RAW RAG RESULTS ===\n")

for r in results:
    print("CATEGORY:", r.get("category"))
    print("LAYER:", r.get("layer"))
    print("CONTENT:", r.get("content")[:200])
    print("-" * 50)