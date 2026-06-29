"""
Notifier Agent — Updated
Sends WhatsApp (Twilio) with automatic SMS fallback on delivery failure.
"""
import os, logging, asyncio
import httpx

log = logging.getLogger(__name__)


class NotifierAgent:
    def __init__(self):
        self.twilio_sid   = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
        self.twilio_token = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
        self.from_whatsapp = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886")
        self.from_sms      = self.from_whatsapp.replace("whatsapp:", "")

    # ── Public methods ─────────────────────────────────────────────────────────

    async def notify_family(self, case_id: str, event, severity: dict) -> dict:
        contacts = await self._get_family_contacts(event.elder_id)

        if severity.get("label") == "dismissed":
            msg = (
                f"ℹ️ *ELDERCARE UPDATE*\n\n"
                f"The alert for {event.elder_id or 'your family member'} "
                f"has been reviewed.\n\n"
                f"✅ No emergency detected — case has been closed.\n"
                f"📋 Case ID: #{case_id[:8]}\n\n"
                f"If this seems incorrect, call 112.\n\n"
            )
        else:
            emoji = {5: "🚨", 4: "⚠️", 3: "🔔", 2: "ℹ️", 1: "💙"}.get(severity.get("score", 3), "🔔")

            msg = (
                f"{emoji} *ELDERCARE ALERT* {emoji}\n\n"
                f"Your loved one needs help!\n"
                f"📍 Location: {event.location or 'Being located...'}\n"
                f"🔴 Severity: {severity.get('label', 'unknown').upper()} "
                f"(Score: {severity.get('score', '?')}/5)\n"
                f"📋 Case ID: #{case_id[:8]}\n\n"
                f"https://eldercare-demo.app/track/{case_id}"
            )

        results = []
        for contact in contacts:
            results.append(await self._send_with_sms_fallback(contact, msg, case_id))

        return {
            "notified": sum(1 for r in results if r.get("status") != "failed"),
            "contacts": results,
            "case_id": case_id,
        }

    async def notify_ambulance_dispatched(self, case_id: str, case: dict) -> dict:
        """Notify everyone that ambulance is approved and en route."""
        contacts = await self._get_family_contacts(
            case.get("event", {}).get("elder_id")
        )
        msg = (
            f"✅ *UPDATE — Ambulance Dispatched*\n\n"
            f"An ambulance has been approved and is en route.\n"
            f"Case: #{case_id[:8]}\n"
            f"Approved by: {case.get('approved_by', 'Medical coordinator')}\n\n"
            f"Track live: https://eldercare-demo.app/track/{case_id}"
        )
        results = []
        for contact in contacts:
            result = await self._send_with_sms_fallback(contact, msg, case_id)
            results.append(result)

        return {"notified": len(results), "contacts": results}

    async def notify_secondary_contacts(self, case_id: str, elder_id: str, message: str) -> dict:
        """
        Exception handler: notify secondary contacts when primary family
        is not responding.
        """
        contacts = await self._get_secondary_contacts(elder_id)
        results  = []
        for contact in contacts:
            result = await self._send_with_sms_fallback(contact, message, case_id)
            results.append(result)
        return {"notified": len(results), "contacts": results}

    async def notify_senior_coordinator(self, case_id: str, message: str) -> dict:
        """
        Exception handler: escalate to senior coordinator on SLA breach.
        """
        contacts = await self._get_senior_coordinator_contacts()
        results  = []
        for contact in contacts:
            result = await self._send_with_sms_fallback(contact, message, case_id)
            results.append(result)
        return {"notified": len(results), "contacts": results}

    # ── Core send with automatic SMS fallback ──────────────────────────────────

    async def _send_with_sms_fallback(self, to_number: str, message: str, case_id: str) -> dict:
        """
        Try WhatsApp first. If it fails or Twilio not configured → fall back to SMS.
        Exception 8: WhatsApp Delivery Failure → SMS Fallback
        """
        # Try WhatsApp
        whatsapp_result = await self._send_whatsapp(to_number, message)

        if whatsapp_result.get("status") in ["queued", "sent", "delivered", "mock_sent"]:
            return {**whatsapp_result, "channel": "whatsapp"}

        # WhatsApp failed → try SMS fallback
        log.warning(f"[Notifier] WhatsApp failed for {to_number} — trying SMS fallback")
        sms_result = await self._send_sms(to_number, message)

        if sms_result.get("status") in ["queued", "sent", "delivered", "mock_sent"]:
            return {**sms_result, "channel": "sms_fallback"}

        # Both failed
        log.error(f"[Notifier] Both WhatsApp and SMS failed for {to_number}")
        return {
            "to":            to_number,
            "status":        "failed",
            "channel":       "all_failed",
            "whatsapp_error": whatsapp_result.get("error"),
            "sms_error":      sms_result.get("error"),
        }

    async def _send_whatsapp(self, to_number: str, message: str) -> dict:
        """Send WhatsApp message via Twilio."""
        if not self.twilio_sid:
            log.info(f"[MOCK WhatsApp] → {to_number}: {message[:80]}...")
            return {"to": to_number, "status": "mock_sent", "sid": "MOCK-WA"}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    url,
                    data={
                        "From": self.from_whatsapp,
                        "To":   f"whatsapp:{to_number}" if not to_number.startswith("whatsapp:") else to_number,
                        "Body": message,
                    },
                    auth=(self.twilio_sid, self.twilio_token),
                )
                data = r.json()
                return {
                    "to":     to_number,
                    "status": data.get("status", "unknown"),
                    "sid":    data.get("sid", ""),
                    "error":  data.get("message") if data.get("status") == "failed" else None,
                }
        except Exception as e:
            return {"to": to_number, "status": "error", "error": str(e)}

    async def _send_sms(self, to_number: str, message: str) -> dict:
        """
        SMS fallback via Twilio SMS API.
        Exception 8: WhatsApp Delivery Failure → SMS Fallback
        """
        # Shorten message for SMS (160 char limit)
        sms_text = message[:157] + "..." if len(message) > 160 else message

        if not self.twilio_sid:
            log.info(f"[MOCK SMS] → {to_number}: {sms_text[:60]}...")
            return {"to": to_number, "status": "mock_sent", "sid": "MOCK-SMS"}

        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.twilio_sid}/Messages.json"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    url,
                    data={
                        "From": self.from_sms,
                        "To":   to_number,
                        "Body": sms_text,
                    },
                    auth=(self.twilio_sid, self.twilio_token),
                )
                data = r.json()
                return {
                    "to":     to_number,
                    "status": data.get("status", "unknown"),
                    "sid":    data.get("sid", ""),
                    "error":  data.get("message") if data.get("status") == "failed" else None,
                }
        except Exception as e:
            return {"to": to_number, "status": "error", "error": str(e)}

    # ── Contact lists (replace with DB calls in production) ───────────────────

    async def _get_family_contacts(self, elder_id: str | None) -> list[str]:
        """Primary family contacts — replace with DB lookup."""
        return ["+917075143471"]
        #return ["+917075143471", "+919110775194"]

    async def _get_secondary_contacts(self, elder_id: str | None) -> list[str]:
        """
        Secondary contacts — called when primary family not responding.
        Exception 1: Family Not Responding
        """
        return ["+917075143471"]
        #return ["+917075143471", "+919110775194"]

    async def _get_senior_coordinator_contacts(self) -> list[str]:
        """
        Senior coordinator contacts — called on SLA breach.
        Exception 3: SLA Breach
        """
        return ["+917075143471"]
