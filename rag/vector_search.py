import os
from pymongo import MongoClient
from dotenv import load_dotenv
from typing import List, Dict
from utils.logger import get_logger

load_dotenv()

logger = get_logger("VectorSearch")


class VectorSearchEngine:

    def __init__(self):
        mongo_uri = os.getenv("MONGO_URI")

        self.client = MongoClient(mongo_uri)

        # ✅ FIXED DATABASE
        self.db = self.client["agri_rag"]
        self.collection = self.db["knowledge_base"]

        self.index_name = "vector_index"

    def search(self, embedding: List[float], top_k: int = 10) -> List[Dict]:

        if not embedding:
            return []

        pipeline = [
            {
                "$vectorSearch": {
                    "index": self.index_name,
                    "path": "embedding",
                    "queryVector": embedding,
                    "numCandidates": 200,
                    "limit": top_k
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "crop": 1,
                    "category": 1,
                    "layer": 1,
                    "disease_or_issue": 1,
                    "content": 1,
                    "score": {"$meta": "vectorSearchScore"}
                }
            }
        ]

        try:
            results = list(self.collection.aggregate(pipeline))

            logger.debug("\n=== VECTOR SEARCH RESULTS ===")
            logger.debug(str(results))
            logger.debug("============================\n")

            return results

        except Exception as e:
            logger.error(f"VectorSearch Error: {e}")
            return []