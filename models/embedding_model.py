import os
os.environ["TRANSFORMERS_NO_TF"] = "1"
os.environ["TRANSFORMERS_NO_FLAX"] = "1"
from sentence_transformers import SentenceTransformer
from typing import List
import threading


class EmbeddingModel:
    """
    Lightweight embedding model wrapper for RAG pipeline.
    Uses sentence-transformers for semantic vector generation.
    """

    _lock = threading.Lock()

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        """
        Initialize the embedding model once.
        """
        self.model = SentenceTransformer(model_name)

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for input text.
        """
        if not text:
            return []

        with self._lock:
            vector = self.model.encode(text)

        return vector.tolist()

    def generate_batch_embeddings(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts at once.
        Useful for document indexing.
        """
        if not texts:
            return []

        with self._lock:
            vectors = self.model.encode(texts)

        return [vec.tolist() for vec in vectors]