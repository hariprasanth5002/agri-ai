from typing import Dict, List, Any


class ContextBuilder:

    def build(
        self,
        nlp: Dict,
        rag: List[Dict],
        vision: Dict = None,
        location: Dict = None,
        weather: Dict = None
    ) -> Dict[str, Any]:

        query = nlp.get("original_text", "").lower()
        intent = nlp.get("intent")
        intent_confidence = nlp.get("intent_confidence")

        entities = nlp.get("entities", {})

        crop = entities.get("crop", [])
        disease = entities.get("disease", [])

        # -----------------------------
        # 🔥 FILTER RELEVANT KNOWLEDGE
        # -----------------------------
        # -----------------------------
# 🔥 DISEASE-AWARE FILTERING
# -----------------------------
        disease_list = nlp.get("entities", {}).get("disease", [])

        exact = []
        partial = []

        for item in rag:
            content = item.get("content", "").lower()

            # ✅ exact disease match
            if any(d in content for d in disease_list):
                exact.append(item)

            # ✅ fallback for generic match (any entity)
            elif any(d in content for d in entities.get("crop", []) + entities.get("weather", [])):
                partial.append(item)

# -----------------------------
# FINAL SELECTION
# -----------------------------
        filtered = exact if exact else partial[:3]

        # fallback if still empty
        if not filtered:
            filtered = rag[:3]

        # -----------------------------
        # 🔥 LIMIT + SHORTEN CONTENT
        # -----------------------------
        knowledge = []

        for item in filtered[:3]:
            knowledge.append({
                "content": item.get("content", "")[:800],  # 🔥 reduce size
                "score": round(item.get("score", 0), 3)
            })

        return {
            "query": query,
            "intent": {
                "type": intent,
                "confidence": intent_confidence
            },
            "entities": {
                "crop": crop,
                "disease": disease,
                "location": location
            },
            "environment": {
                "weather": weather
            },
            "knowledge": knowledge,
            "vision": vision
        }