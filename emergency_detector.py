"""
Emergency Detector Agent — Groq API
Classifies whether an incoming message is a genuine emergency.
"""

import os
import json
import re
import asyncio
import functools
from groq import Groq
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

SYSTEM_PROMPT = """
You are an emergency detection AI for an eldercare safety platform.

Analyze incoming messages and classify them as an emergency or not.

Respond ONLY with a valid JSON object — no markdown, no explanation, no extra text:

{
  "is_emergency": true,
  "confidence": 0.0,
  "emergency_type": "fall",
  "keywords_detected": [],
  "summary": "",
  "needs_immediate_action": true
}

Scoring guide:
- fall: person mentions falling, tripping, can't get up
- medical: chest pain, difficulty breathing, stroke symptoms, bleeding
- fire: smoke, fire, burning smell
- intruder: break-in, suspicious person, threat
- none: test message, normal conversation, clearly not an emergency
"""


class EmergencyDetectorAgent:
    def __init__(self):
        self.client = Groq(
            api_key=os.getenv("GROQ_API_KEY")
        )

        self.model = os.getenv(
            "GROQ_MODEL",
            "llama-3.3-70b-versatile"
        )

    async def run(self, text: str, source: str) -> dict:
        user_msg = f"Source: {source}\nMessage: {text}"

        loop = asyncio.get_running_loop()

        return await loop.run_in_executor(
            None,
            functools.partial(self._call_groq, user_msg)
        )

    def _call_groq(self, user_msg: str) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                max_tokens=512,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": user_msg
                    }
                ]
            )

            raw = response.choices[0].message.content.strip()

            # Remove markdown fences if present
            raw = re.sub(
                r"^```(?:json)?\s*|\s*```$",
                "",
                raw,
                flags=re.MULTILINE
            ).strip()

            return json.loads(raw)

        except Exception as e:
            print("GROQ ERROR:", repr(e))

            return {
                "is_emergency": True,
                "confidence": 0.7,
                "emergency_type": "unknown",
                "keywords_detected": [],
                "summary": "Groq unavailable — treating as emergency (safe default)",
                "needs_immediate_action": True,
                "error": str(e)
            }