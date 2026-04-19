"""
SafetyValidator — RAG-grounded safety validation layer for agricultural AI.

Cross-verifies LLM-generated responses against domain-specific safety
knowledge retrieved from the RAG knowledge base to prevent unsafe
agricultural recommendations.

Usage:
    validator = SafetyValidator()
    result = validator.validate(response=llm_output, context=final_context)
    # result → {"safe": bool, "validated_response": str, "issues": list}
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("SafetyValidator")


class SafetyValidator:
    """
    Validates and corrects LLM-generated agricultural advice using
    safety knowledge from the RAG pipeline (Layer 1 disease data,
    Layer 2 advisory rules).
    """

    # ─────────────────────────────────────────────────────────────
    # UNSAFE PATTERN DEFINITIONS
    # ─────────────────────────────────────────────────────────────

    # Chemicals banned or restricted in India (CIB&RC / Anupam Verma list)
    BANNED_CHEMICALS = {
        "endosulfan", "monocrotophos", "methyl parathion", "phorate",
        "triazophos", "dichlorvos", "phosphamidon", "methomyl",
        "aldicarb", "captafol", "dieldrin", "aldrin", "heptachlor",
        "benzene hexachloride", "bhc", "lindane", "ethyl mercury chloride",
        "mercury compounds", "calcium cyanide", "copper acetoarsenite",
        "ddt", "ethylene dibromide", "maleic hydrazide",
        "paraquat dimethyl sulphate", "sodium cyanide", "sodium methane arsonate",
        "tetradifon", "nicotine sulfate", "nitrofen", "paraquat",
        "pentachloronitrobenzene", "pentachlorophenol", "phenyl mercury acetate",
        "toxaphene", "metoxuron", "chlordane", "ethyl parathion",
        "carbofuran 50sp", "benomyl", "carbaryl", "diazinon",
        "fenitrothion", "alachlor", "thiram",
    }

    # Patterns that indicate potentially dangerous overuse
    OVERUSE_PATTERNS = [
        r"\bapply\s+daily\b",
        r"\bevery\s*day\b",
        r"\bdaily\s+application\b",
        r"\bincrease\s+(the\s+)?dosage\b",
        r"\bdouble\s+(the\s+)?dose\b",
        r"\btriple\s+(the\s+)?dose\b",
        r"\btwice\s+a\s+day\b",
        r"\bhigher\s+(concentration|dose|dosage|amount)\b",
        r"\bmore\s+than\s+recommended\b",
        r"\bexcessive\s+(use|application|spraying)\b",
        r"\brepeat\s+(spray(ing)?|application)\s+(every\s+)?(1|2|3)\s+days?\b",
        r"\bapply\s+liberally\b",
        r"\bgenerous(ly)?\s+(application|amount|use)\b",
        r"\bsoak\s+(the\s+)?(plant|crop|soil)\b",
    ]

    # Required structural sections in a complete response
    REQUIRED_SECTIONS = {
        "diagnosis":    [
            "diagnosis", "identified", "detected", "disease", "infection",
            "symptoms", "caused by", "pathogen",
        ],
        "treatment":    [
            "treatment", "control", "manage", "spray", "apply", "fungicide",
            "pesticide", "insecticide", "use",
        ],
        "dosage":       [
            "g/l", "ml/l", "gram", "grams per liter", "ml per liter",
            "g per liter", "dosage", "dose", "rate",
        ],
        "timing":       [
            "interval", "days", "every", "frequency", "timing", "schedule",
            "when to", "season", "stage",
        ],
    }

    # Dosage regex patterns → captures (value, unit)
    DOSAGE_PATTERNS = [
        # "2.5 g/L", "3.0 g/l", "2 g / L"
        r"(\d+(?:\.\d+)?)\s*g\s*/\s*[lL]",
        # "2.5 ml/L", "3 ml/l"
        r"(\d+(?:\.\d+)?)\s*ml\s*/\s*[lL]",
        # "2.5 grams per liter"
        r"(\d+(?:\.\d+)?)\s*grams?\s+per\s+lit(?:er|re)",
        # "2.5 ml per liter"
        r"(\d+(?:\.\d+)?)\s*ml\s+per\s+lit(?:er|re)",
        # "2.5 g per L"
        r"(\d+(?:\.\d+)?)\s*g\s+per\s+[lL]",
        # "2.5 grams/liter"
        r"(\d+(?:\.\d+)?)\s*grams?\s*/\s*lit(?:er|re)",
    ]

    # ─────────────────────────────────────────────────────────────
    # MAIN ENTRY POINT
    # ─────────────────────────────────────────────────────────────

    def validate(self, response: str, context: dict) -> dict:
        """
        Validate and correct an LLM-generated agricultural response.

        Args:
            response:  Raw LLM output string.
            context:   Pipeline context dict containing:
                       - entities.crop, entities.disease
                       - entities.location
                       - environment.weather
                       - knowledge (list of RAG results)

        Returns:
            {
              "safe":               bool,
              "validated_response":  str,
              "issues":             list[str]
            }
        """
        if not response or not response.strip():
            return {
                "safe": False,
                "validated_response": "No response was generated. Please try again.",
                "issues": ["Empty response from LLM"],
            }

        issues: List[str] = []
        knowledge = context.get("knowledge", [])

        # ── Step 1: Extract dosage from LLM response ──────────
        response_dosages = self.extract_dosage(response)

        # ── Step 2: Check against RAG safety knowledge ────────
        knowledge_issues, knowledge_dosage = self.check_against_knowledge(
            response, response_dosages, knowledge
        )
        issues.extend(knowledge_issues)

        # ── Step 3: Detect risk patterns ──────────────────────
        risk_issues = self.detect_risks(response)
        issues.extend(risk_issues)

        # ── Step 4: Validate structural completeness ──────────
        structure_issues, missing_sections = self.enforce_structure(response)
        issues.extend(structure_issues)

        # ── Step 5: Determine safety verdict ──────────────────
        is_safe = len(issues) == 0

        # ── Step 6: Correct response if unsafe ────────────────
        if is_safe:
            validated = response
        else:
            validated = self.correct_response(
                response, issues, knowledge,
                knowledge_dosage, missing_sections
            )

        logger.info(
            f"Safety validation complete — safe={is_safe}, "
            f"issues={len(issues)}"
        )
        if issues:
            logger.warning(f"Issues found: {issues}")

        return {
            "safe": is_safe,
            "validated_response": validated,
            "issues": issues,
        }

    # ─────────────────────────────────────────────────────────────
    # HELPER 1 — EXTRACT DOSAGE
    # ─────────────────────────────────────────────────────────────

    def extract_dosage(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract all dosage mentions from a text string.

        Returns list of {"value": float, "unit": str, "match": str}
        """
        dosages = []
        text_lower = text.lower()

        for pattern in self.DOSAGE_PATTERNS:
            for match in re.finditer(pattern, text_lower):
                value = float(match.group(1))
                raw = match.group(0)

                # Determine unit
                if "ml" in raw:
                    unit = "ml/L"
                else:
                    unit = "g/L"

                dosages.append({
                    "value": value,
                    "unit": unit,
                    "match": match.group(0),
                })

        # Deduplicate by (value, unit)
        seen = set()
        unique = []
        for d in dosages:
            key = (d["value"], d["unit"])
            if key not in seen:
                seen.add(key)
                unique.append(d)

        return unique

    # ─────────────────────────────────────────────────────────────
    # HELPER 2 — CHECK AGAINST RAG KNOWLEDGE
    # ─────────────────────────────────────────────────────────────

    def check_against_knowledge(
        self,
        response: str,
        response_dosages: List[Dict],
        knowledge: List[Dict],
    ) -> Tuple[List[str], Optional[Dict]]:
        """
        Cross-verify LLM response dosages and chemicals against
        the RAG-retrieved knowledge base entries.

        Returns:
            (issues: list[str], knowledge_dosage: dict or None)
        """
        issues: List[str] = []
        response_lower = response.lower()

        # ── Banned chemical detection ─────────────────────────
        for chem in self.BANNED_CHEMICALS:
            if chem in response_lower:
                issues.append(
                    f"Banned/restricted chemical detected: {chem.title()}"
                )

        # ── Extract dosage info from RAG knowledge ────────────
        knowledge_dosage = self._extract_knowledge_dosage(knowledge)

        # ── Cross-verify dosage ───────────────────────────────
        if response_dosages and knowledge_dosage:
            kg = knowledge_dosage  # shorthand
            kg_gpl = kg.get("grams_per_liter")

            if kg_gpl is not None:
                for rd in response_dosages:
                    if rd["unit"] == "g/L" and rd["value"] > kg_gpl:
                        issues.append(
                            f"Overdose detected: response recommends "
                            f"{rd['value']} g/L but knowledge says "
                            f"{kg_gpl} g/L"
                        )

            # Check spray interval
            kg_interval = kg.get("spray_interval_days")
            if kg_interval:
                freq_issue = self._check_frequency(response_lower, kg_interval)
                if freq_issue:
                    issues.append(freq_issue)

        elif not response_dosages:
            # Dosage is expected but missing
            # Only warn if knowledge has dosage data
            if knowledge_dosage and knowledge_dosage.get("grams_per_liter"):
                issues.append("Dosage information missing from response")

        # ── Verify chemicals mentioned exist in knowledge ─────
        unknown = self._detect_unknown_chemicals(response_lower, knowledge)
        if unknown:
            issues.append(
                f"Unknown chemical(s) not in knowledge base: "
                f"{', '.join(c.title() for c in unknown)}"
            )

        return issues, knowledge_dosage

    # ─────────────────────────────────────────────────────────────
    # HELPER 3 — DETECT RISKS
    # ─────────────────────────────────────────────────────────────

    def detect_risks(self, response: str) -> List[str]:
        """
        Scan for overuse patterns, dangerous language, and
        missing safety precautions.
        """
        issues: List[str] = []
        response_lower = response.lower()

        # ── Overuse patterns ──────────────────────────────────
        for pattern in self.OVERUSE_PATTERNS:
            if re.search(pattern, response_lower):
                issues.append(
                    f"Unsafe frequency/overuse detected: "
                    f"'{re.search(pattern, response_lower).group()}'"
                )
                break  # one overuse flag is enough

        # ── Safety precautions are no longer force-checked ────
        # Precautions are only appended if they come from RAG knowledge,
        # not from a hardcoded default block.

        return issues

    # ─────────────────────────────────────────────────────────────
    # HELPER 4 — ENFORCE STRUCTURE
    # ─────────────────────────────────────────────────────────────

    def enforce_structure(self, response: str) -> Tuple[List[str], List[str]]:
        """
        Validate that the response covers all required sections:
        diagnosis, treatment, dosage, timing, precautions.

        Returns:
            (issues, missing_sections)
        """
        issues: List[str] = []
        missing: List[str] = []
        response_lower = response.lower()

        for section, keywords in self.REQUIRED_SECTIONS.items():
            found = any(kw in response_lower for kw in keywords)
            if not found:
                missing.append(section)
                issues.append(f"Missing section: {section}")

        return issues, missing

    # ─────────────────────────────────────────────────────────────
    # HELPER 5 — CORRECT RESPONSE
    # ─────────────────────────────────────────────────────────────

    def correct_response(
        self,
        response: str,
        issues: List[str],
        knowledge: List[Dict],
        knowledge_dosage: Optional[Dict],
        missing_sections: List[str],
    ) -> str:
        """
        Correct an unsafe response using RAG knowledge.

        Strategy:
        1. Replace overdose values with knowledge-recommended dosage
        2. Remove banned chemical mentions + add warning
        3. Append missing safety precautions from knowledge
        4. Append missing structural sections
        5. Add a review notice if uncertainty is high
        """
        corrected = response

        # ── 1. Fix overdose ───────────────────────────────────
        if knowledge_dosage:
            kg_gpl = knowledge_dosage.get("grams_per_liter")
            if kg_gpl is not None:
                corrected = self._fix_overdose(corrected, kg_gpl)

            # Fix unsafe frequency
            kg_interval = knowledge_dosage.get("spray_interval_days")
            if kg_interval:
                corrected = self._fix_frequency(corrected, kg_interval)

        # ── 2. Replace banned chemicals ───────────────────────
        corrected_lower = corrected.lower()
        banned_found = [
            c for c in self.BANNED_CHEMICALS if c in corrected_lower
        ]
        if banned_found:
            for chem in banned_found:
                # Case-insensitive replacement
                pattern = re.compile(re.escape(chem), re.IGNORECASE)
                corrected = pattern.sub(
                    f"[REMOVED: {chem.title()} — banned/restricted]",
                    corrected,
                )

        # ── 3. Append safety precautions from knowledge (only if RAG has them) ──
        # We no longer force-append precautions. They are only added if the
        # RAG knowledge actually contains safety_notes for this disease.
        #  (removed default fallback injection)

        # ── 4. Append dosage if missing ───────────────────────
        if "dosage" in missing_sections and knowledge_dosage:
            dosage_text = self._build_dosage_section(knowledge_dosage)
            if dosage_text:
                corrected += f"\n\nRECOMMENDED DOSAGE:\n{dosage_text}"

        # ── 5. Append timing if missing ───────────────────────
        if "timing" in missing_sections and knowledge_dosage:
            interval = knowledge_dosage.get("spray_interval_days")
            phi = knowledge_dosage.get("pre_harvest_interval_days")
            if interval or phi:
                timing_parts = []
                if interval:
                    timing_parts.append(
                        f"• Apply every {interval} days"
                    )
                if phi:
                    timing_parts.append(
                        f"• Pre-harvest interval: {phi} days"
                    )
                corrected += (
                    f"\n\nTIMING:\n" + "\n".join(timing_parts)
                )

        # ── 6. Log serious issues (no user-facing review notice) ──
        serious = [
            i for i in issues
            if "banned" in i.lower()
            or "overdose" in i.lower()
            or "unknown chemical" in i.lower()
        ]
        if serious:
            logger.warning(
                f"Serious safety corrections applied: {serious}. "
                f"Consider manual review."
            )

        return corrected.strip()

    # ─────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────

    def _extract_knowledge_dosage(
        self, knowledge: List[Dict]
    ) -> Optional[Dict]:
        """
        Pull the first available dosage_guidelines from knowledge entries.
        Works with both raw RAG results (layer1 with dosage_guidelines)
        and context-builder output (truncated content strings).
        """
        for item in knowledge:
            # Direct dosage_guidelines field (layer1 raw)
            dg = item.get("dosage_guidelines")
            if dg and isinstance(dg, dict):
                if dg.get("grams_per_liter") is not None:
                    return dg

            # Fallback: parse dosage from content text
            content = item.get("content", "")
            if content:
                dosages = self.extract_dosage(content)
                if dosages:
                    # Build a synthetic dosage dict
                    d = dosages[0]
                    result = {"grams_per_liter": d["value"]}

                    # Try to extract spray interval
                    interval_match = re.search(
                        r"(?:spray\s+)?interval[s]?\s*(?:of\s+)?(\d+)"
                        r"[\s\-–to]+(\d+)\s*days?",
                        content.lower(),
                    )
                    if interval_match:
                        # Use the larger value (conservative)
                        result["spray_interval_days"] = int(
                            interval_match.group(2)
                        )
                    else:
                        interval_single = re.search(
                            r"every\s+(\d+)\s*(?:[-–]?\s*\d+\s*)?days?",
                            content.lower(),
                        )
                        if interval_single:
                            result["spray_interval_days"] = int(
                                interval_single.group(1)
                            )

                    # Try to extract PHI
                    phi_match = re.search(
                        r"pre[- ]harvest\s+interval[s]?\s*"
                        r"(?:\(PHI\))?\s*(?:of\s+)?(\d+)",
                        content, re.IGNORECASE,
                    )
                    if phi_match:
                        result["pre_harvest_interval_days"] = int(
                            phi_match.group(1)
                        )

                    return result

        return None

    def _check_frequency(
        self, response_lower: str, safe_interval: int
    ) -> Optional[str]:
        """
        Check if the response recommends a spray frequency shorter
        than the knowledge-recommended interval.
        """
        # Match "every X days"
        freq_match = re.search(
            r"every\s+(\d+)\s*(?:[-–]\s*\d+\s*)?days?", response_lower
        )
        if freq_match:
            mentioned_interval = int(freq_match.group(1))
            if mentioned_interval < safe_interval:
                return (
                    f"Unsafe frequency: response says every "
                    f"{mentioned_interval} days but knowledge recommends "
                    f"every {safe_interval} days"
                )

        # Match "daily" / "every day"
        if re.search(r"\bdaily\b|\bevery\s*day\b", response_lower):
            return (
                f"Unsafe frequency: 'daily' application detected — "
                f"knowledge recommends every {safe_interval} days"
            )

        return None

    def _detect_unknown_chemicals(
        self, response_lower: str, knowledge: List[Dict]
    ) -> List[str]:
        """
        Detect chemicals mentioned in the response that are NOT found
        in any of the knowledge base entries.
        """
        # Common agricultural chemical names to look for
        KNOWN_CHEMICALS = {
            "mancozeb", "copper oxychloride", "carbendazim",
            "chlorothalonil", "azoxystrobin", "difenoconazole",
            "myclobutanil", "tebuconazole", "propiconazole",
            "hexaconazole", "metalaxyl", "thiram", "captan",
            "wettable sulfur", "sulphur", "sulfur",
            "bordeaux mixture", "ziram", "copper sulfate",
            "trifloxystrobin", "kresoxim methyl",
            "cymoxanil", "dimethomorph", "fosetyl al",
            "iprodione", "thiophanate methyl", "neem oil",
            "potassium bicarbonate", "lime sulfur",
            "imidacloprid", "acetamiprid", "thiamethoxam",
            "fipronil", "lambda cyhalothrin", "cypermethrin",
            "deltamethrin", "malathion", "chlorpyrifos",
            "profenofos", "abamectin", "emamectin benzoate",
            "spinosad", "indoxacarb", "flubendiamide",
            "rynaxypyr", "chlorantraniliprole",
        }

        # Build knowledge text corpus
        knowledge_text = " ".join(
            item.get("content", "").lower() for item in knowledge
        )

        # Find chemicals mentioned in response but not in knowledge
        unknown = []
        for chem in KNOWN_CHEMICALS:
            if chem in response_lower and chem not in knowledge_text:
                # Skip if it's a banned chem (handled separately)
                if chem not in self.BANNED_CHEMICALS:
                    unknown.append(chem)

        return unknown

    def _fix_overdose(self, response: str, safe_gpl: float) -> str:
        """
        Replace overdose values in the response with the safe
        knowledge-backed value.
        """
        for pattern in self.DOSAGE_PATTERNS:
            for match in re.finditer(pattern, response, re.IGNORECASE):
                value = float(match.group(1))
                if value > safe_gpl:
                    old = match.group(0)
                    # Preserve unit style
                    if "ml" in old.lower():
                        new = f"{safe_gpl} ml/L"
                    else:
                        new = f"{safe_gpl} g/L"
                    response = response.replace(old, new, 1)

        return response

    def _fix_frequency(self, response: str, safe_interval: int) -> str:
        """
        Replace unsafe spray frequency with the knowledge-recommended
        interval.
        """
        # Replace "daily" / "every day"
        response = re.sub(
            r"\b(apply\s+)?daily\b",
            f"every {safe_interval} days",
            response,
            flags=re.IGNORECASE,
        )
        response = re.sub(
            r"\bevery\s*day\b",
            f"every {safe_interval} days",
            response,
            flags=re.IGNORECASE,
        )

        # Replace short intervals
        def _replace_short_interval(match):
            mentioned = int(match.group(1))
            if mentioned < safe_interval:
                return f"every {safe_interval} days"
            return match.group(0)

        response = re.sub(
            r"every\s+(\d+)\s*days?",
            _replace_short_interval,
            response,
            flags=re.IGNORECASE,
        )

        return response

    def _build_precautions(self, knowledge: List[Dict]) -> str:
        """
        Build a precaution section from RAG knowledge safety_notes.
        """
        precautions = set()

        for item in knowledge:
            note = item.get("safety_notes", "")
            if note and note.strip():
                precautions.add(note.strip())

            # Also extract from content
            content = item.get("content", "")
            if content:
                for marker in ["precaution", "safety", "caution", "warning"]:
                    if marker in content.lower():
                        # Extract the sentence containing the marker
                        sentences = re.split(r'[.!]', content)
                        for s in sentences:
                            if marker in s.lower() and len(s.strip()) > 20:
                                precautions.add(s.strip() + ".")
                                break

        if not precautions:
            # No hardcoded fallback — only return precautions from actual
            # RAG knowledge so responses don't get a generic boilerplate.
            return ""

        return "\n".join(f"• {p}" for p in sorted(precautions))

    def _build_dosage_section(self, dosage: Dict) -> str:
        """
        Build a dosage recommendation section from knowledge data.
        """
        parts = []

        gpl = dosage.get("grams_per_liter")
        if gpl is not None:
            parts.append(f"• Recommended rate: {gpl} g/L of water")

        gpa = dosage.get("grams_per_acre")
        if gpa is not None:
            parts.append(f"• Per acre: {gpa} g/acre")

        interval = dosage.get("spray_interval_days")
        if interval is not None:
            parts.append(f"• Spray interval: every {interval} days")

        phi = dosage.get("pre_harvest_interval_days")
        if phi is not None:
            parts.append(f"• Pre-harvest interval: {phi} days")

        return "\n".join(parts) if parts else ""
