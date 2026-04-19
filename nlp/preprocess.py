import re
import time
import json
from typing import Dict, List, Optional, Tuple, Any

try:
    from rapidfuzz import process, fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False


class AgriculturalNLPModule:

    def __init__(self):

        # -----------------------------
        # ENTITY LISTS
        # -----------------------------
        self.crops = [
            "sugarcane", "soybean", "barley", "tomato", "potato", "cotton",
            "banana", "garlic", "pepper", "apple", "grape", "orange",
            "mango", "onion", "wheat", "chili", "maize", "rice", "corn"
        ]

        self.diseases = [
            "powdery mildew", "downy mildew", "early blight", "late blight",
            "leaf spot", "brown spot", "black rot", "mildew", "blight",
            "canker", "mosaic", "virus", "blast", "rust", "wilt",
            "scab", "smut", "spot", "gall", "rot"
        ]

        self.weather = [
            "temperature", "humidity", "monsoon", "drought", "winter",
            "summer", "cloudy", "rainy", "sunny", "windy", "frost",
            "humid", "rain", "cold", "hot", "dry"
        ]

        self.locations = [
            "maharashtra", "california", "karnataka", "florida",
            "gujarat", "punjab", "haryana", "kerala", "texas", "ohio", "iowa"
        ]

        # -----------------------------
        # INTENT KEYWORDS
        # -----------------------------
        self.intent_keywords = {
            "disease_diagnosis": [
                "what disease", "diagnose", "identify", "what is wrong",
                "sick", "symptom", "spot", "yellowing", "disease",
                "what is this disease", "what is disease"
            ],
            "disease_treatment": [
                "treat", "treatment", "cure", "medicine",
                "pesticide", "fungicide", "spray", "how to fix",
                "control", "rid of", "remedy", "recover"
            ],
            "disease_severity": [
                "serious", "severe", "bad", "damage",
                "dangerous", "stage", "lethal", "fatal"
            ],
            "prevention": [
                "prevent", "avoid", "protect", "stop"
            ],
            "fertilizer_recommendation": [
                "fertilizer", "npk", "urea", "compost",
                "nutrients", "potash"
            ],
            "weather_effect": [
                "weather", "rain", "temperature", "humidity"
            ],
            "crop_management": [
                "plant", "harvest", "yield", "irrigate", "soil"
            ],
            "general_query": [
                "help", "hello", "hi", "how", "what", "why"
            ]
        }

        self.intent_priority = {
            "disease_diagnosis": 3,
            "disease_treatment": 3,
            "disease_severity": 3,
            "prevention": 3,
            "fertilizer_recommendation": 2,
            "weather_effect": 2,
            "crop_management": 2,
            "general_query": 1,
            "image_only": 0
        }

    # -----------------------------
    # NORMALIZATION
    # -----------------------------
    def normalize_text(self, text: str) -> str:
        if not text:
            return ""
        text = text.lower()
        text = re.sub(r'[^a-z0-9\s]', ' ', text)
        text = re.sub(r'(.)\1{2,}', r'\1', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # -----------------------------
    # NEGATION
    # -----------------------------
    def detect_negation(self, text: str) -> bool:
        pattern = r'\b(not|no|never|without|dont|doesnt|cant|wont)\b'
        return bool(re.search(pattern, text))

    # -----------------------------
    # ENTITY EXTRACTION
    # -----------------------------
    def extract_entities(self, text: str) -> Dict[str, List[str]]:

        entities = {
            "crop": [],
            "disease": [],
            "weather": [],
            "location": []
        }

        def find_entities(target_list, text):
            found = []

            for item in target_list:
                if item in text:
                    found.append(item)

            return list(set(found))

        entities["crop"] = find_entities(self.crops, text)
        entities["disease"] = find_entities(self.diseases, text)
        entities["weather"] = find_entities(self.weather, text)
        entities["location"] = find_entities(self.locations, text)

        return entities

    # -----------------------------
    # 🔥 UPDATED INTENT DETECTION
    # -----------------------------
    def detect_intent(self, text: str, disease_prediction: Optional[str] = None) -> Tuple[str, float]:
        # -----------------------------
        # -----------------------------
# 🔥 GREETING / GENERAL (PRODUCTION)
# -----------------------------
        greeting_keywords = [
    # Basic greetings
    "hi", "hello", "hey", "heyy", "hii", "yo",

    # Time-based greetings
    "good morning", "good afternoon", "good evening", "good night",

    # Farewell
    "bye", "goodbye", "see you", "see ya", "take care", "later",

    # Gratitude
    "thanks", "thank you", "thankyou", "thx", "thanks a lot", "many thanks",

    # Polite starters
    "please", "pls", "kindly",

    # Casual conversational
    "sup", "whats up", "what's up", "how are you", "how r u",

    # Appreciation
    "great", "awesome", "nice", "cool", "good job",

    # Acknowledgements
    "ok", "okay", "kk", "alright", "fine", "got it"
    ]

        clean_text = text.strip().lower()
        tokens = clean_text.split()

# Match greeting keywords (partial allowed)
        if len(tokens) <= 4 and any(clean_text.startswith(greet) for greet in greeting_keywords):
           return "greeting", 1.0
        
        # -----------------------------
# 🔥 OUT-OF-SCOPE / NON-AGRI (PRODUCTION)
# -----------------------------
        out_of_scope_keywords = [

    # Entertainment
    "movie", "movies", "film", "films", "song", "songs", "music", "album",

    # Sports (non-agri)
    "cricket", "football", "ipl", "match", "score", "team", "player",

    # Social media / internet
    "instagram", "facebook", "youtube", "whatsapp", "twitter", "reels",

    # Technology unrelated
    "coding", "programming", "python code", "java", "c++",

    # Politics / news
    "politics", "election", "minister", "government news",

    # Shopping / random
    "buy phone", "price of iphone", "laptop", "mobile",

    # General unrelated
    "joke", "story", "motivation", "quotes", "relationship"
        ]

        clean_text = text.lower().strip()
        tokens = clean_text.split()

# Match keywords
        matched = [kw for kw in out_of_scope_keywords if kw in clean_text]

# 🔥 Decision logic
        if matched:

    # Avoid false positives (like "crop disease treatment")
          agri_words = ["crop", "plant", "disease", "fertilizer", "soil", "pest"]

          if not any(a in clean_text for a in agri_words):

        # Short or clearly unrelated query
            if len(tokens) <= 12:
              return "out_of_scope", 1.0
        if not text or text.strip() == "":
            return "image_only", 1.0
        
        # -----------------------------
# 🔥 WEATHER INTENT SPLIT (NEW)
        # -----------------------------
# 🔥 WEATHER INTENT (PRODUCTION)
# -----------------------------
        clean_text = text.strip().lower()
        tokens = clean_text.split()

        weather_words = ["weather", "temperature", "rain", "humidity"]

        future_words = ["tomorrow", "next", "week", "later", "soon","forecast"]

        rain_patterns = [
    "will it rain",
    "is it going to rain",
    "rain today",
    "rain tomorrow"
        ]

# REALTIME
        if clean_text in ["weather", "weather today"] or (
          "weather" in clean_text and len(tokens) <= 3
        ):
            return "weather_realtime", 1.0

# RAIN QUESTIONS
        if any(p in clean_text for p in rain_patterns):
            return "weather_forecast", 1.0

# FUTURE WEATHER
        if any(w in clean_text for w in weather_words) and any(f in clean_text for f in future_words):
            return "weather_forecast", 0.95

# AGRICULTURE WEATHER
        if any(w in clean_text for w in weather_words):
           crop_entities = self.extract_entities(clean_text).get("crop", [])
           if crop_entities:
            return "weather_agriculture", 0.9
        # -----------------------------
        # STEP 1 — ACTION OVERRIDE
        # -----------------------------
        treatment_triggers = [
            "treat", "treatment", "cure", "spray", "control",
            "remedy", "recover", "what should i do", "how to fix"
        ]

        if any(trigger in text for trigger in treatment_triggers):
            return "disease_treatment", 0.9

        # -----------------------------
        # STEP 2 — IMAGE DEFAULT
        # -----------------------------
        if disease_prediction:
            return "disease_diagnosis", 0.85

        # -----------------------------
        # STEP 3 — NORMAL TEXT INTENT
        # -----------------------------
        scores = {intent: 0 for intent in self.intent_keywords}

        for intent, keywords in self.intent_keywords.items():
            for kw in keywords:
                if kw in text:
                    scores[intent] += 1

        best_intent = max(scores, key=scores.get)

        if scores[best_intent] == 0:
            return "general_query", 0.0

        confidence = min(0.5 + scores[best_intent] * 0.1, 0.95)

        return best_intent, round(confidence, 2)
        

    # -----------------------------
    # QUERY REWRITE
    # -----------------------------
    def rewrite_query(self, text, intent, entities, disease_prediction):

        expansions = []

        if intent == "disease_treatment":
            expansions += ["treatment", "fungicide", "control"]

        if disease_prediction:
            text = f"Detected disease: {disease_prediction}. {text}"

        if expansions:
            text += " | " + " ".join(expansions)

        return text

    # -----------------------------
    # MAIN PIPELINE
    # -----------------------------
    def process_input(self, text: str, disease_prediction: Optional[str] = None):

        norm = self.normalize_text(text)
        entities = self.extract_entities(norm)
        intent, conf = self.detect_intent(norm, disease_prediction)

        return {
            "original_text": text,
            "normalized_text": norm,
            "intent": intent,
            "intent_confidence": conf,
            "entities": entities,
            "ready_for_embedding": self.rewrite_query(norm, intent, entities, disease_prediction)
        }


# -----------------------------
# TEST
# -----------------------------
if __name__ == "__main__":

    nlp = AgriculturalNLPModule()

    tests = [
        ("IMAGE ONLY", "", "Early Blight"),
        ("VAGUE", "this looks bad", "Early Blight"),
        ("DIAGNOSIS", "what disease is this", "Early Blight"),
        ("TREATMENT", "how to treat this", "Early Blight"),
        ("ACTION", "what should i do", "Early Blight")
    ]

    for name, text, disease in tests:
        print("\n", "="*50)
        print(name)
        result = nlp.process_input(text, disease)
        print(json.dumps(result, indent=2))
