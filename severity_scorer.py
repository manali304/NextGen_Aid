
"""
Severity Scorer Agent — Groq API

Scores emergency severity 1–5 with clinical reasoning.

1 = Minor wellness check
3 = Moderate — caregiver dispatch
5 = Critical — immediate ambulance
"""

import os
import json
import re
import asyncio
import functools

from groq import Groq


SYSTEM_PROMPT = """
You are a clinical triage AI for an eldercare emergency response system.

Given an emergency report, score the severity and recommend the response level.

Respond ONLY with a valid JSON object — no markdown, no explanation, no extra text:

{
  "score": 1 to 5,
  "label": "critical" or "high" or "moderate" or "low" or "minimal",
  "reasoning": "Brief clinical reasoning, max 2 sentences",
  "recommended_response": "ambulance" or "caregiver" or "family_check" or "monitor",
  "time_sensitive": true or false,
  "estimated_response_minutes": number between 5 and 30
}

Scoring guide:

5 = Unconscious, cardiac event, stroke, severe bleeding
    → dispatch ambulance immediately

4 = Fall with suspected fracture, chest pain, confusion
    → urgent caregiver + ambulance standby

3 = Fall without injury, distress call
    → caregiver dispatch

2 = Disorientation, minor pain
    → family notification + check-in

1 = Preventive alert, wellness check needed
"""


class SeverityAgent:
    def __init__(self):
        self.client = Groq(
            api_key=os.getenv("GROQ_API_KEY")
        )

        self.model = os.getenv(
            "GROQ_MODEL",
            "llama-3.3-70b-versatile"
        )

    async def run(
        self,
        raw_text: str,
        detection: dict
    ) -> dict:

        user_msg = (
            f"Raw message: {raw_text}\n"
            f"Emergency type: {detection.get('emergency_type', 'unknown')}\n"
            f"Initial confidence: {detection.get('confidence', 0.8)}\n"
            f"Summary: {detection.get('summary', '')}"
        )

        loop = asyncio.get_running_loop()

        return await loop.run_in_executor(
            None,
            functools.partial(self._call_groq, user_msg)
        )

    def _call_groq(self, user_msg: str) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                max_tokens=512,
                temperature=0.1,
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

            # Safe default:
            # Prefer over-escalation rather than under-escalation
            return {
                "score": 4,
                "label": "high",
                "reasoning": "Groq unavailable — defaulting to high severity for safety.",
                "recommended_response": "caregiver",
                "time_sensitive": True,
                "estimated_response_minutes": 10,
                "error": str(e)
            }

