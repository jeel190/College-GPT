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
        self.model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

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
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3.6-flash",
            "gemini-3.7-flash",
            "gemini-flash-latest"
        ]
        unique_models = list(dict.fromkeys(m for m in models_to_try if m))

        last_error = None
        for m in unique_models:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={self.gemini_key}"
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
                "generationConfig": {
                    "temperature": 0.1,  # Deterministic, factual accuracy
                    "maxOutputTokens": 800
                }
            }

            try:
                resp = requests.post(url, json=payload, timeout=7)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates and "content" in candidates[0]:
                        parts = candidates[0]["content"].get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                else:
                    err_text = resp.text[:200]
                    last_error = f"HTTP {resp.status_code}: {err_text}"
                    if resp.status_code in (400, 403):
                        raise Exception(last_error)
            except Exception as e:
                last_error = str(e)
                if "400" in last_error or "403" in last_error or "API_KEY_INVALID" in last_error:
                    raise

        raise Exception(f"Google AI Studio request failed across models: {last_error}")

    def _targeted_offline_extract(self, question: str, chunks: List[Dict[str, Any]]) -> str:
        """
        Intelligently extracts ONLY the specifically requested data (e.g. Tuesday timetable,
        attendance rule, or specific module) across all chunks without showing filenames.
        """
        if not chunks:
            return (
                "**No matching information found.**\n\n"
                "I couldn't locate relevant sections in your currently indexed college documents for this inquiry."
            )

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

        # 2. Specific topic matching: search lines across ALL retrieved chunks
        stop_words = {"what", "is", "the", "are", "of", "in", "for", "a", "an", "and", "or", "to", "how", "do", "does", "can", "tell", "me", "give", "show", "plan", "work"}
        q_raw_words = [w for w in re.findall(r"\w+", q_lower) if w not in stop_words]

        # Expand with typo map
        q_words = set(q_raw_words)
        for w in q_raw_words:
            if w in COMMON_TYPO_MAP:
                q_words.add(COMMON_TYPO_MAP[w])

        matched_lines = []
        for chunk in chunks:
            text = chunk.get("text", "")
            lines = [l.strip() for l in text.split("\n") if l.strip()]
            for i, line in enumerate(lines):
                line_lower = line.lower()
                # Check for significant keyword match
                match_count = sum(1 for qw in q_words if qw in line_lower)
                if match_count > 0:
                    matched_lines = lines[i : min(i + 5, len(lines))]
                    break
            if matched_lines:
                break

        if matched_lines:
            header = matched_lines[0]
            subtopics = matched_lines[1:]
            bullets = "\n".join(f"* {sub}" for sub in subtopics) if subtopics else ""
            return f"### **{header}**\n\n{bullets}\n"

        # Fallback to concise snippet of first chunk without file titles
        first_text = chunks[0].get("text", "")[:280].strip() + "..."
        return f"{first_text}\n"
