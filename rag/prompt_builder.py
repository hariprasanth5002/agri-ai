from typing import Dict, List, Any, Optional


class PromptBuilder:
    """
    Production-grade Prompt Builder

    Responsibilities:
    - Convert structured context → LLM-ready prompt
    - Enforce grounding (no hallucination)
    - Align with RAG layers (disease, advisory, safety)
    - Adapt format based on intent — NO forced structure on every query
    """

    # ------------------------------------------------------------------
    # GREETING
    # ------------------------------------------------------------------
    def build_greeting_prompt(self, query: str) -> str:
        return f"""
You are a friendly agricultural assistant called Agri AI speaking directly to a farmer.

Farmer said: "{query}"

Respond warmly and briefly directly to the farmer in 1-2 sentences.
Guide them to ask agriculture-related questions like crop diseases,
treatment, fertilizers, or weather impact.
Do NOT use bullet points or structured format.
CRITICAL: Speak directly to them. Do not refer to them as "the user".
""".strip()

    # ------------------------------------------------------------------
    # OUT OF SCOPE
    # ------------------------------------------------------------------
    def build_restriction_prompt(self, query: str) -> str:
        return f"""
You are an agricultural AI assistant called Agri AI speaking directly to a farmer.

Farmer asked: "{query}"

This is NOT related to agriculture.
Politely decline their question directly in 1-2 sentences and mention what you can help with.
Do NOT use bullet points or structured format.
CRITICAL: Speak directly to them. Do not refer to them as "the user" or "the farmer" in the third person.
""".strip()

    # ------------------------------------------------------------------
    # WEATHER
    # ------------------------------------------------------------------
    def build_weather_prompt(
        self,
        weather: Dict,
        location: Dict,
        forecast: Dict = None,
        intent: str = None,
        query: str = ""
    ) -> str:

        city = location.get("city", "your area")
        temp = weather.get("temperature")
        humidity = weather.get("humidity")
        condition = weather.get("condition")

        q = query.lower()
        if "tomorrow" in q:
            time_context = "tomorrow"
        elif "after tomorrow" in q:
            time_context = "the day after tomorrow"
        elif "weekend" in q:
            time_context = "the upcoming weekend"
        elif "today" in q or "now" in q:
            time_context = "today"
        else:
            time_context = "the specific day or period the user asked about (or current conditions if unspecified)"

        forecast_text = ""
        if forecast and forecast.get("forecast"):
            next_data = forecast["forecast"][:7] # Give the LLM a full week to answer day-specific queries
            forecast_text = "Next 7 Days Forecast:\n"
            for f in next_data:
                forecast_text += (
                    f"- {f['date']} ({f['day_label']}) → Max: {f['temp_max']}°C, Min: {f['temp_min']}°C, "
                    f"Condition: {f['condition']}, Rain Prob: {round(f['rain_prob']*100)}%\n"
                )

        return f"""
You are an agricultural weather advisor speaking directly to a farmer.

Farmer's query: "{query}"
Location: {city}

Current weather:
- Temperature: {temp}°C
- Humidity: {humidity}%
- Condition: {condition}

{forecast_text}

Analyze the Farmer's query and confidently answer with the exact temperature, condition, and rain probability for the specific day they asked about ('{time_context}'). If unspecified, provide the current weather and today's forecast.
Give a clear, concise weather summary (2-3 sentences) focused ONLY on their requested timeframe.
Then give 1 sentence of practical farming advice based on that weather.

CRITICAL RULES:
- Speak DIRECTLY to the farmer (e.g., "Currently in {city}, it is...").
- Do NOT refer to the farmer in the third person. Do NOT say things like "The user asked for" or "The user hasn't specified".
- Do NOT narrate your thought process. Just give the answer.
- Do NOT use bullet points, headers, or structured format.
- Be natural and conversational.
""".strip()

    # ------------------------------------------------------------------
    # COMPACT KNOWLEDGE HELPER
    # ------------------------------------------------------------------
    def _build_compact_knowledge(self, knowledge_items: List[Dict]) -> str:
        if not knowledge_items:
            return "No relevant knowledge retrieved.\n"
        text = ""
        for item in knowledge_items:
            content = item.get("content", "").strip()
            if content:
                # Do NOT truncate. Agricultural dosages and precise chemical formulations
                # are often located at the end of RAG chunks.
                text += f"- {content}\n\n"
        return text

    # ------------------------------------------------------------------
    # MAIN BUILD — INTENT-AWARE
    # ------------------------------------------------------------------
    def build(self, context: Dict[str, Any]) -> str:

        # ── Safe extraction ───────────────────────────────────────
        query        = context.get("query", "")
        intent_data  = context.get("intent", {})
        intent       = intent_data.get("type", "unknown")
        intent_conf  = intent_data.get("confidence", 0.0)
        entities     = context.get("entities", {})
        crop         = entities.get("crop", [])
        disease      = entities.get("disease", [])
        location     = entities.get("location")
        environment  = context.get("environment", {})
        weather      = environment.get("weather")
        vision       = context.get("vision")

        crop_text     = ", ".join(crop)     if crop     else "Unknown"
        disease_text  = ", ".join(disease)  if disease  else "Unknown"
        location_text = str(location)       if location else "Unknown"
        weather_text  = self._format_weather(weather)
        
        vision_text = "None"
        if vision:
            if vision.get("is_rejected"):
                vision_text = "Status: Image rejected. The uploaded image is either not a plant leaf, or is too unclear for the vision AI to process. Tell the farmer politely that you couldn't analyze the image and ask them to upload a clearer photo of a single leaf."
            else:
                vision_text = f"Confidence: {vision.get('confidence', 0):.2f}. Disease Prediction: {vision.get('disease')}."
                if vision.get("warning"):
                    vision_text += f" Warning from vision model: {vision.get('warning')}"

        knowledge_items = context.get("knowledge", [])
        knowledge_text  = self._build_compact_knowledge(knowledge_items)

        system_prompt  = self._build_system_prompt(intent)
        instructions   = self._build_instructions(intent)
        response_format = self._build_response_format(intent)

        return f"""
{system_prompt}

================ USER QUERY ================
{query}

================ CONTEXT ==================
Crop: {crop_text}
Disease: {disease_text}
Intent: {intent} (confidence: {intent_conf})
Location: {location_text}
Weather: {weather_text}
Vision Analysis: {vision_text}

================ KNOWLEDGE ================
{knowledge_text}

================ INSTRUCTIONS =============
{instructions}

CRITICAL COMMUNICATION RULE:
- Speak DIRECTLY to the farmer. Do NOT refer to the farmer in the third person (like "the user"). 
- Do NOT narrate your thought process (like "since you didn't specify..."). Just give the answer directly.

{response_format}
================ FINAL ANSWER =============
""".strip()

    # ------------------------------------------------------------------
    # SYSTEM PROMPT — varies by intent
    # ------------------------------------------------------------------
    def _build_system_prompt(self, intent: str) -> str:

        if intent in ("disease_diagnosis", "disease_treatment",
                      "disease_severity", "prevention"):
            return """
You are a senior agricultural plant pathologist with 20+ years of field experience in Indian farming.
You specialize in identifying crop diseases and prescribing precise, actionable treatment plans.

CRITICAL RULES:
- Ground EVERY claim in the provided KNOWLEDGE section. Do NOT hallucinate chemical names or dosages.
- If the knowledge contains specific dosages (ml/L, g/L, kg/ha), you MUST quote them exactly.
- If no dosage is found in the knowledge, explicitly say "Dosage: Refer to the product label for your specific formulation."
- Always mention the active ingredient AND its formulation (e.g., Mancozeb 75% WP, Azoxystrobin 23% SC).
- Be practical and farmer-friendly. Assume the reader is an Indian farmer with basic education.
""".strip()

        if intent == "fertilizer_recommendation":
            return """
You are an expert agricultural soil scientist and certified agronomist with deep expertise in Indian soil types.
You provide practical, farmer-friendly fertilizer recommendations grounded in the provided knowledge.

CRITICAL RULES:
- Always specify the fertilizer grade (e.g., NPK 19:19:19, Urea 46-0-0).
- Include exact dosage per acre or per liter of water.
- Mention the application method (foliar spray, soil drench, broadcasting).
- If the knowledge mentions specific brands or formulations, include them.
""".strip()

        if intent in ("crop_management", "weather_effect"):
            return """
You are an experienced agricultural advisor specializing in Indian crop management.
Give practical, weather-aware farming advice grounded in the provided knowledge.
Always consider the current season and local conditions when advising.
""".strip()

        # general_query, unknown, image_only, etc.
        return """
You are Agri AI, a knowledgeable and friendly agricultural assistant.
Answer the farmer's question clearly, practically, and thoroughly.
Use the provided knowledge to give accurate, grounded answers.
If the knowledge contains specific data (chemicals, dosages, timings), include them in your response.
""".strip()

    # ------------------------------------------------------------------
    # INSTRUCTIONS — intent-specific
    # ------------------------------------------------------------------
    def _build_instructions(self, intent: str) -> str:

        if intent == "disease_diagnosis":
            return """
1. Start with a brief 1-2 sentence overview of the disease
2. Identify the most likely disease from the knowledge with its scientific name
3. List the key visible symptoms a farmer should look for
4. Explain the pathogen/cause and the conditions that favor it
5. Suggest immediate next steps the farmer should take
""".strip()

        if intent == "disease_treatment":
            return """
1. Start with a brief 1-sentence confirmation of the disease
2. List the recommended chemical treatments with EXACT active ingredients and formulations from the knowledge
3. For EACH chemical mentioned in the knowledge, extract and provide the EXACT dosage (ml/L, g/L, or kg/ha) — this is MANDATORY
4. Specify the spray schedule (interval in days, number of applications)
5. Mention the Pre-Harvest Interval (PHI) if available in the knowledge
6. Include both chemical AND organic/cultural options if the knowledge provides them
7. End with safety precautions including protective equipment needed

IMPORTANT: Carefully scan ALL provided knowledge chunks for dosage data. Dosages are often in a separate chunk from the general treatment description. Look for patterns like "X ml per liter", "X g/L", "X grams per liter".
""".strip()

        if intent == "disease_severity":
            return """
1. Assess severity level (Low / Medium / High / Critical) based on the knowledge
2. Describe the potential crop damage and yield impact
3. Specify the urgency of action (immediate, within days, preventive)
4. Recommend the first action the farmer should take right now
""".strip()

        if intent == "prevention":
            return """
1. List cultural/preventive measures (spacing, pruning, sanitation)
2. Include resistant varieties if mentioned in the knowledge
3. Recommend preventive chemical sprays with exact dosages from the knowledge
4. Mention monitoring/scouting practices
5. Keep advice practical and actionable for an Indian farmer
""".strip()

        if intent == "fertilizer_recommendation":
            return """
1. Identify the crop growth stage and nutrient requirement
2. Recommend specific fertilizer types with grades (e.g., NPK 19:19:19)
3. Provide EXACT dosage per acre, per plant, or per liter of water
4. Specify application method (foliar spray, soil application, drip fertigation)
5. Mention timing and frequency of application
6. Warn about any over-application risks
""".strip()

        if intent in ("crop_management", "weather_effect"):
            return """
Give practical, actionable advice grounded in the knowledge provided.
Include specific actions the farmer should take, with timing if relevant.
Be conversational but thorough.
""".strip()

        # general_query, unknown
        return """
Answer the question helpfully, clearly, and thoroughly.
Use the provided knowledge to give specific, grounded answers.
Be conversational — no need for a structured format unless it genuinely helps.
""".strip()

    # ------------------------------------------------------------------
    # RESPONSE FORMAT — only enforce structure for clinical intents
    # ------------------------------------------------------------------
    def _build_response_format(self, intent: str) -> str:

        if intent == "disease_diagnosis":
            return """
================ RESPONSE FORMAT ==========
Start with a 1-2 sentence overview paragraph, then use bullet points:
- Diagnosis: (disease name, scientific name, and why you identified it)
- Symptoms: (what the farmer can see — leaf spots, wilting, discoloration, etc.)
- Cause: (pathogen name and favorable conditions like temperature, humidity)
- Recommended Action: (what to do next — consult expert, start treatment, monitor)
"""

        if intent == "disease_treatment":
            return """
================ RESPONSE FORMAT ==========
Start with a 1-2 sentence overview paragraph, then use bullet points:
- Treatment: (list ALL recommended fungicides/pesticides with active ingredient AND formulation. e.g., "Mancozeb 75% WP" or "Azoxystrobin 23% SC")
- Dosage: (MANDATORY — extract EXACT dosages from the knowledge. For example: "Mancozeb 75% WP at 2.5 g/L of water" or "Azoxystrobin 23% SC at 1.0 ml/L". If multiple chemicals, list dosage for EACH one separately.)
- Timing: (spray interval in days, when to start, how many applications, Pre-Harvest Interval if known)
- Precautions: (PPE required, temperature restrictions, phytotoxicity warnings, environmental precautions)

CRITICAL: The Dosage bullet MUST contain specific numbers from the knowledge (ml/L, g/L, kg/ha). Do NOT say "follow label instructions" if the knowledge provides exact numbers.
"""

        if intent == "disease_severity":
            return """
================ RESPONSE FORMAT ==========
Structure your answer as:
- Severity: (Low / Medium / High / Critical — with brief justification)
- Damage risk: (specific crop damage, yield loss percentage if known)
- Action urgency: (Immediate / Within 2-3 days / Preventive schedule)
- First step: (the single most important thing to do right now)
"""

        if intent == "prevention":
            return """
================ RESPONSE FORMAT ==========
List preventive measures using clear bullet points:
- Cultural practices (spacing, sanitation, pruning)
- Resistant varieties (if mentioned in knowledge)
- Preventive sprays with dosage (if available in knowledge)
- Monitoring/scouting tips
"""

        if intent == "fertilizer_recommendation":
            return """
================ RESPONSE FORMAT ==========
Structure your answer as:
- Recommended fertilizer: (type, grade, and brand if known)
- Dosage: (exact amount per acre, per plant, or per liter — MUST include specific numbers)
- Timing: (growth stage, frequency, best time of day)
- Method: (foliar spray / soil drench / broadcasting / drip fertigation)
- Precautions: (over-application risks, mixing compatibility)
"""

        # For ALL other intents: no forced structure
        return """
================ RESPONSE FORMAT ==========
Respond in clear, natural prose. 
Do NOT force a Diagnosis/Treatment/Dosage/Timing/Precautions structure
unless the user specifically asked about disease treatment.
Keep it conversational and helpful.
If the knowledge contains specific data (chemicals, dosages, timings), include them naturally.
"""

    # ------------------------------------------------------------------
    # WEATHER FORMATTER
    # ------------------------------------------------------------------
    def _format_weather(self, weather: Dict) -> str:
        if not weather:
            return "Not available"
        try:
            return (
                f"{weather.get('temperature')}°C, "
                f"{weather.get('humidity')}% humidity, "
                f"{weather.get('condition')}"
            )
        except Exception:
            return "Unavailable"

    # ------------------------------------------------------------------
    # LEGACY SECTION FORMATTER (kept for compatibility)
    # ------------------------------------------------------------------
    def _format_section(self, title: str, items: List[Dict]) -> str:
        if not items:
            return f"{title}:\n- No relevant knowledge retrieved\n"
        text = f"{title}:\n"
        for item in items:
            content = item.get("content", "").strip()
            score   = round(item.get("score", 0), 3)
            if content:
                text += f"- {content} (score: {score})\n"
        return text + "\n"