from pymongo import MongoClient

# LOCAL DB
local_client = MongoClient("mongodb://localhost:27017/")
local_db = local_client["agri_rag"]
local_collection = local_db["knowledge_base"]

# ATLAS DB
atlas_client = MongoClient("mongodb+srv://hariprasanth5002_db_user:KPXnS87tMndfCYBI@cluster0.ouvfnhs.mongodb.net/?appName=Cluster0")
atlas_db = atlas_client["agri_rag"]
atlas_collection = atlas_db["knowledge_base"]

# FETCH LOCAL DATA
documents = list(local_collection.find({}, {"_id": 0}))

print(f"📦 Found {len(documents)} documents")

# INSERT INTO ATLAS
if documents:
    atlas_collection.insert_many(documents)
    print("✅ Migration complete")
else:
    print("❌ No data found")