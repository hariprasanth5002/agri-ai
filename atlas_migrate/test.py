from pymongo import MongoClient
from models.embedding_model import EmbeddingModel

# -----------------------------
# CONNECT ATLAS
# -----------------------------
client = MongoClient("mongodb+srv://hariprasanth5002_db_user:KPXnS87tMndfCYBI@cluster0.ouvfnhs.mongodb.net/?appName=Cluster0")
collection = client["agri_rag"]["knowledge_base"]

embedding_model = EmbeddingModel()


# -----------------------------
# TEST QUERIES (ALL LAYERS)
# -----------------------------
TEST_QUERIES = [
    # Layer 1 (disease)
    ("Disease Detection", "Tomato leaves have white powdery patches"),

    # Layer 2 (advisory)
    ("Fertilizer", "Rice leaves turning yellow what fertilizer to apply"),
    ("Pest", "Whiteflies in cotton how to control"),
    ("Weather", "Heavy rain coming should I apply fertilizer"),
    ("Spray Timing", "Can I spray pesticide during fog"),

    # Layer 3 (decision)
    ("Crop Recommendation", "Best crop to grow in low rainfall area next 6 months"),
]


# -----------------------------
# RUN TEST
# -----------------------------
def run_test(name, query):
    print("\n" + "=" * 80)
    print(f"🧪 Test: {name}")
    print(f"Query: {query}")

    query_vector = embedding_model.generate_embedding(query)

    results = list(collection.aggregate([
        {
            "$vectorSearch": {
                "index": "vector_index",
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": 200,
                "limit": 5
            }
        },
        {
            "$project": {
                "crop": 1,
                "category": 1,
                "layer": 1,
                "disease_or_issue": 1,
                "score": {"$meta": "vectorSearchScore"}
            }
        }
    ]))

    if not results:
        print("❌ NO RESULTS")
        return False

    print("\nTop Results:\n")

    for r in results:
        print(f"Score: {round(r.get('score', 0), 4)}")
        print(f"Layer: {r.get('layer')}")
        print(f"Category: {r.get('category')}")
        print(f"Crop: {r.get('crop')}")
        print(f"Disease: {r.get('disease_or_issue')}")
        print("-" * 40)

    return True


# -----------------------------
# EXECUTION
# -----------------------------
print("\n🚀 RUNNING ATLAS VECTOR STRESS TEST\n")

success = 0

for name, query in TEST_QUERIES:
    if run_test(name, query):
        success += 1

print("\n" + "=" * 80)
print(f"✅ Passed: {success} / {len(TEST_QUERIES)} tests")
print("DONE\n")