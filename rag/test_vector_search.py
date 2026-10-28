from rag.vector_search import VectorSearchEngine
from models.embedding_model import EmbeddingModel
import os

# Initialize
embedder = EmbeddingModel()
search_engine = VectorSearchEngine()

# Test query
query = "help me treat my tomato crop with early blight"

print("\nQUERY:", query)

# Generate embedding
embedding = embedder.generate_embedding(query)

print("\nEmbedding length:", len(embedding))  # should be 384

# Search
results = search_engine.search(embedding)

print("\n=== RAG RESULTS ===")
for r in results:
    print(r)
print("===================\n")
print("MONGO_URI:", os.getenv("MONGO_URI"))