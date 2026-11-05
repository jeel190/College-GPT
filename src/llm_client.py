"""
LLM Client for College GPT.
Exclusively powered by Google AI Studio (Gemini API) with an intelligent, targeted Offline Fallback.
Clean responses without file citations or provider badges.
"""

import os
import re
from typing import List, Dict, Any, Tuple
import requests
from src.prompt import COLLEGE_SYSTEM_PROMPT, QA_USER_PROMPT

COMMON_TYPO_MAP = {
    "jango": "django",
    "pyton": "python",
    "phyton": "python",
    "pyhton": "python",
    "postgre": "postgresql",
    "postgress": "postgresql",
    "postgres": "postgresql",
    "reactjs": "react",
    "sem": "semester",
    "semister": "semester",
    "sylabus": "syllabus",
    "syllbus": "syllabus",
    "timetbl": "timetable",
    "atten": "attendance",
    "subjets": "subjects"
}


class CollegeLLMClient:
    def __init__(self):
        self.load_env()

    def load_env(self):
        """Loads the Google AI Studio API Key from environment or .env files."""
        if not os.getenv("GEMINI_API_KEY"):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            parent_dir = os.path.dirname(base_dir)
            for env_path in [os.path.join(base_dir, ".env"), os.path.join(parent_dir, ".env")]:
                if os.path.exists(env_path):
                    try:
                        with open(env_path, "r", encoding="utf-8", errors="ignore") as f:
                            for line in f:
                                line = line.strip()
                                if line.startswith("GEMINI_API_KEY="):
                                    v = line.split("=", 1)[1].strip()
                                    if v:
                                        os.environ["GEMINI_API_KEY"] = v
                                elif line.startswith("GEMINI_MODEL="):
                                    v = line.split("=", 1)[1].strip()
                                    if v:
                                        os.environ["GEMINI_MODEL"] = v
                    except Exception:
                        pass

        self.gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        self.model = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview").strip()

    def get_active_provider(self) -> str:
        """Returns current status of Google AI Studio provider."""
        self.load_env()
        return "google_studio" if self.gemini_key else "offline"

    def generate_response(
        self,
        question: str,
        retrieved_chunks: List[Dict[str, Any]],
        custom_provider: str = None
    ) -> Tuple[str, str]:
        """
        Synthesizes an answer using the retrieved chunks and Google AI Studio Gemini API.
        Returns: (answer_markdown, provider_name)
        """
        self.load_env()

        # Build context string without exposing raw filenames to the user
        context_parts = []
        for i, chunk in enumerate(retrieved_chunks, 1):
            text = chunk.get("text", "")
            context_parts.append(f"--- Document Reference {i} ---\n{text}\n")

        context_str = "\n".join(context_parts)
        system_content = COLLEGE_SYSTEM_PROMPT.format(context=context_str)
        user_content = QA_USER_PROMPT.format(question=question)

        # 1. Primary: Google AI Studio
        if self.gemini_key:
            try:
                answer = self._call_google_ai_studio(system_content, user_content)
                return answer, "Google AI Studio"
            except Exception as e:
                err_msg = str(e)
                self._last_err = err_msg
                print(f"[College GPT] Google AI Studio error: {err_msg}")
                if "API_KEY_INVALID" in err_msg or "400" in err_msg or "403" in err_msg:
                    return (
                        f"⚠️ **Google AI Studio Key Error**: Your `GEMINI_API_KEY` appears invalid or unauthorized.\n\n"
                        f"Please check your key at [Google AI Studio](https://aistudio.google.com/app/apikey) and verify `.env`.\n\n"
                        f"---\n"
                        + self._targeted_offline_extract(question, retrieved_chunks)
                    ), "Google AI Studio (Key Error)"

        # 2. Targeted Offline Extractor Fallback
        return self._targeted_offline_extract(question, retrieved_chunks), "Offline Extractor"

    def _call_google_ai_studio(self, system_content: str, user_content: str) -> str:
        """Call to Google AI Studio Generative Language REST API using requests with multi-model fallback."""
        models_to_try = [
            self.model,
            "gemini-3-flash-preview",
            "gemini-3.1-flash-lite-preview",
            "gemini-flash-latest"
        ]
        # Try at most 2 distinct models to ensure ultra-fast response without blocking
        unique_models = list(dict.fromkeys(m for m in models_to_try if m))[:2]

        last_error = None
        for m in unique_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_key}"
            gen_cfg = {
                "temperature": 0.1,  # Balanced fast & accurate inference
                "maxOutputTokens": 2500,  # Comprehensive answers without truncation
                "topK": 20,
                "topP": 0.9
            }
            if "gemini-3" in m or "gemini-2.5" in m:
                gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

            payload = {
                "systemInstruction": {
                    "parts": [{"text": system_content}]
                },
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": user_content}]
                    }
                ],
                "generationConfig": gen_cfg
            }

            try:
                resp = requests.post(url, json=payload, timeout=25)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                elif resp.status_code == 429:
                    # Free tier quota exceeded on key; fail fast to offline extractor without looping
                    raise Exception("HTTP 429: Quota exceeded on Google AI Studio.")
                elif resp.status_code in (400, 403):
                    raise Exception(f"HTTP {resp.status_code}: {resp.text[:200]}")
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:150]}"
            except Exception as e:
                last_error = str(e)
                if "400" in last_error or "403" in last_error or "429" in last_error or "API_KEY_INVALID" in last_error:
                    raise

        raise Exception(f"Google AI Studio request failed across models: {last_error}")

    def _targeted_offline_extract(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        """
        Intelligently extracts ONLY the specifically requested data (e.g. Tuesday timetable,
        attendance rule, or specific module) across all chunks without showing filenames.
        """
        if not chunks:
            return "I do not have information regarding the question asked in the college documents."

        q_lower = question.lower()
        days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        queried_day = next((d for d in days if d in q_lower), None)

        # 1. Day of timetable requested
        if queried_day:
            for chunk in chunks:
                text = chunk.get("text", "")
                if queried_day in text.lower():
                    lines = text.split("\n")
                    day_lines = []
                    capturing = False
                    for line in lines:
                        if queried_day in line.lower():
                            capturing = True
                            day_lines.append(line.strip())
                            continue
                        if capturing:
                            if any(d in line.lower() for d in days if d != queried_day):
                                break
                            if line.strip():
                                day_lines.append(line.strip())

                    if day_lines:
                        clean_content = " | ".join(day_lines)
                        return (
                            f"### 📅 **{queried_day.capitalize()} Schedule**\n\n"
                            f"> **{clean_content}**\n\n"
                            f"*Note: This is a sample planning timetable. Verify official period timings with your department.*"
                        )

        # 2. Document overview / summary in offline mode
        if any(w in q_lower for w in ["what is pdf about", "what is the pdf about", "what is this pdf about", "what is pdf", "summarize", "overview", "what does this document cover"]):
            highlights = []
            for chunk in chunks:
                lines = [l.strip() for l in chunk.get("text", "").split("\n") if len(l.strip()) > 15 and not l.strip().startswith("---")]
                if lines:
                    for line in lines[:2]:
                        if not any(line in h for h in highlights):
                            highlights.append(line)
            if highlights:
                bullets = "\n".join(f"* {h}" for h in highlights[:6])
                return f"### **Document Overview**\n\nThe college documents outline the following key academic subjects and details:\n\n{bullets}\n"

        # 3. Specific topic matching: search lines across ALL retrieved chunks
        stop_words = {
            "what", "is", "the", "are", "of", "in", "for", "a", "an", "and", "or",
            "to", "how", "do", "does", "can", "tell", "me", "give", "show", "plan",
            "work", "explain", "about", "who", "which", "when", "where", "why",
            "would", "should", "could", "any", "some", "my", "your", "our", "their",
            "this", "that", "these", "those", "i", "you", "he", "she", "it", "we", "they"
        }
        q_raw_words = [w for w in re.findall(r"[a-z0-9]+", q_lower) if w not in stop_words and len(w) > 2]

        # Expand with typo map
        q_words = set(q_raw_words)
        for w in q_raw_words:
            if w in COMMON_TYPO_MAP:
                q_words.add(COMMON_TYPO_MAP[w])

        if not q_words:
            return "I do not have information regarding the question asked in the college documents."

        best_match_count = 0
        best_matched_lines = []
        for chunk in chunks:
            text = chunk.get("text", "")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for i, line in enumerate(lines):
                line_lower = line.lower()
                # Strict whole word match using word boundaries
                match_count = sum(1 for qw in q_words if re.search(rf"\b{re.escape(qw)}\b", line_lower))
                if match_count > best_match_count:
                    best_match_count = match_count
                    best_matched_lines = lines[i : min(i + 5, len(lines))]
                    if best_match_count >= len(q_words):
                        break
            if best_match_count >= len(q_words):
                break

        if best_matched_lines and best_match_count > 0:
            header = best_matched_lines[0]
            subtopics = best_matched_lines[1:]
            bullets = "\n".join(f"* {sub}" for sub in subtopics) if subtopics else ""
            return f"### **{header}**\n\n{bullets}\n"

        # Fallback when no relevant topics match in offline mode
        return "I do not have information regarding the question asked in the college documents."
