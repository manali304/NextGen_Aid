
"""
Fraud Guard Agent — Groq API
Detects false alarms, test calls, and repeat-abuse patterns.

NEVER suppresses a real emergency — only flags clear false alarms.
"""

import os
import json
import re
import asyncio
import functools
from datetime import datetime, timezone, timedelta

from groq import Groq


SYSTEM_PROMPT = """
You are a false-alarm detection AI for an eldercare emergency system.

Your ONLY job is to flag OBVIOUS non-genuine emergency reports.
You must NEVER suppress a real emergency. When in doubt, always pass the alert through.

Respond ONLY with a valid JSON object — no markdown, no explanation, no extra text:

{
  "is_suspicious": true or false,
  "reason": "Brief reason if suspicious, otherwise null",
  "confidence": 0.0 to 1.0,
  "recommendation": "pass" or "hold_for_review" or "escalate_to_human"
}

Only flag as suspicious when VERY confident:

- Explicit test messages:
  "testing 123", "this is a test", "ignore this"

- Clearly automated spam or bot messages

- Person explicitly states it is not a real emergency

- Nonsense or random characters with no emergency content

When uncertain, always return:

{
  "is_suspicious": false,
  "reason": null,
  "confidence": 0.0,
  "recommendation": "pass"
}
"""


class FraudGuardAgent:
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
        elder_id: str | None,
        all_cases: dict
    ) -> dict:

        # Detect excessive calls from same elder in last 5 minutes
        if elder_id:
            cutoff = datetime.now(timezone.utc) - timedelta(minutes=5)

            recent = sum(
                1
                for c in all_cases.values()
                if c.get("event", {}).get("elder_id") == elder_id
                and datetime.fromisoformat(c["created_at"]) > cutoff
            )

            if recent >= 5:
                return {
                    "is_suspicious": True,
                    "reason": f"{recent} calls from same elder in 5 minutes — possible device malfunction",
                    "confidence": 0.9,
                    "recommendation": "hold_for_review"
                }

        loop = asyncio.get_running_loop()

        return await loop.run_in_executor(
            None,
            functools.partial(self._call_groq, raw_text)
        )

    def _call_groq(self, raw_text: str) -> dict:
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                temperature=0.1,
                max_tokens=256,
                messages=[
                    {
                        "role": "system",
                        "content": SYSTEM_PROMPT
                    },
                    {
                        "role": "user",
                        "content": f"Message to evaluate:\n{raw_text}"
                    }
                ]
            )

            raw = response.choices[0].message.content.strip()

            # Remove accidental markdown fences
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
            # Never block emergencies if AI fails
            return {
                "is_suspicious": False,
                "reason": None,
                "confidence": 0.0,
                "recommendation": "pass",
                "error": str(e)
            }

