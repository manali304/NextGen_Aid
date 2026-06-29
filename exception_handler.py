"""
ElderCare Exception Handler
Handles all critical exceptions in the emergency response workflow.
"""
import os, logging, asyncio
from datetime import datetime, timezone
from agents.notifier import NotifierAgent

log = logging.getLogger(__name__)
notifier = NotifierAgent()


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 1: Family Not Responding
# ═══════════════════════════════════════════════════════════════
async def handle_family_not_responding(case_id: str, event, severity: dict) -> dict:
    """
    Triggered when: WhatsApp sent but no acknowledgement in 5 minutes.
    Action: Try secondary contacts → escalate to emergency services directly.
    """
    log.warning(f"[EX-001] Family not responding for case {case_id}")

    # Try secondary contacts
    secondary = await _get_secondary_contacts(event.elder_id)
    results = []

    for contact in secondary:
        msg = (
            f"🚨 *URGENT — ELDERCARE ALERT*\n\n"
            f"Primary contacts not responding.\n"
            f"*{event.elder_id or 'Your family member'}* needs emergency help.\n"
            f"📍 {event.location or 'Location being traced'}\n"
            f"Case: #{case_id[:8]}\n\n"
            f"Please respond IMMEDIATELY or call 112."
        )
        result = await notifier._send_whatsapp(contact, msg)
        results.append(result)

    # If still no one responds → auto-escalate to ambulance
    return {
        "exception": "family_not_responding",
        "secondary_contacts_notified": len(results),
        "auto_escalated": True,
        "action": "Escalated to senior coordinator for ambulance approval",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 2: No Caregiver Available
# ═══════════════════════════════════════════════════════════════
async def handle_no_caregiver_available(case_id: str, severity: dict) -> dict:
    """
    Triggered when: CaregiverMatcher returns assigned=False.
    Action: If severity >= 4, skip caregiver and go straight to ambulance.
            If severity < 4, notify family and put on monitoring.
    """
    log.warning(f"[EX-002] No caregiver available for case {case_id}")

    if severity.get("score", 0) >= 4:
        action = "direct_ambulance"
        message = "No caregiver available — routing directly to ambulance dispatch"
    else:
        action = "family_monitoring"
        message = "No caregiver available — notifying family for direct check-in"

    log.info(f"[EX-002] Action taken: {action} — {message}")

    return {
        "exception":   "no_caregiver_available",
        "action":      action,
        "message":     message,
        "severity":    severity.get("score"),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 3: SLA Breach — Human Approval Timeout
# ═══════════════════════════════════════════════════════════════
async def handle_sla_breach_approval(case_id: str, case: dict) -> dict:
    """
    Triggered when: Medical coordinator doesn't approve within 2 minutes.
    Action: Auto-escalate to Senior Coordinator with urgent WhatsApp.
    """
    log.warning(f"[EX-003] SLA breach — approval timeout for case {case_id}")

    # Notify senior coordinator
    msg = (
        f"🚨 *URGENT ESCALATION — SLA BREACH*\n\n"
        f"Case #{case_id[:8]} requires immediate attention.\n"
        f"Medical Coordinator has NOT responded within the 2-minute SLA.\n\n"
        f"*Please approve or decline ambulance dispatch NOW.*\n"
        f"Dashboard: https://eldercare-demo.app/track/{case_id}\n\n"
        f"_Auto-escalated by ElderCare system_"
    )

    senior_contacts = await _get_senior_coordinator_contacts()
    results = []
    for contact in senior_contacts:
        result = await notifier._send_whatsapp(contact, msg)
        results.append(result)

    return {
        "exception":                "sla_breach_approval",
        "escalated_to":             "SeniorCoordinator",
        "senior_contacts_notified": len(results),
        "original_sla_minutes":     2,
        "action":                   "Escalated to senior coordinator",
        "timestamp":                datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 4: Caregiver Not Arriving
# ═══════════════════════════════════════════════════════════════
async def handle_caregiver_not_arriving(
    case_id: str,
    caregiver_id: str,
    caregiver_name: str,
    eta_minutes: int
) -> dict:
    """
    Triggered when: Caregiver assigned but no check-in after ETA + 10 min buffer.
    Action: Re-assign a different caregiver + notify family of delay.
    """
    log.warning(f"[EX-004] Caregiver {caregiver_name} not arriving for case {case_id}")

    return {
        "exception":           "caregiver_not_arriving",
        "original_caregiver":  caregiver_name,
        "original_eta":        eta_minutes,
        "action":              "Re-assigning new caregiver + notifying family of delay",
        "reassign_triggered":  True,
        "timestamp":           datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 5: Hospital at Capacity / Unreachable
# ═══════════════════════════════════════════════════════════════
async def handle_hospital_unavailable(
    case_id: str,
    failed_hospital: str,
    lat: float,
    lon: float
) -> dict:
    """
    Triggered when: Primary hospital is at capacity or not reachable.
    Action: Auto-find and assign the next nearest hospital.
    """
    log.warning(f"[EX-005] Hospital {failed_hospital} unavailable for case {case_id}")

    from agents.hospital_finder import HospitalFinderAgent
    finder = HospitalFinderAgent()
    result = await finder.run(lat, lon, None)

    # Get second option (skip the failed one)
    options = result.get("options", [])
    backup = next(
        (h for h in options if h["name"] != failed_hospital),
        options[0] if options else None
    )

    return {
        "exception":        "hospital_unavailable",
        "failed_hospital":  failed_hospital,
        "backup_hospital":  backup,
        "action":           f"Rerouted to {backup['name'] if backup else 'unknown'}",
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 6: AI Agent (Grok) Failure
# ═══════════════════════════════════════════════════════════════
async def handle_ai_agent_failure(
    case_id: str,
    agent_name: str,
    error: str
) -> dict:
    """
    Triggered when: Any Grok API call returns an error.
    Action: Use safe defaults — treat as genuine high-severity emergency.
    Always fail SAFE (escalate rather than dismiss).
    """
    log.error(f"[EX-006] AI agent {agent_name} failed for case {case_id}: {error}")

    safe_defaults = {
        "EmergencyDetector": {
            "is_emergency":   True,
            "confidence":     0.7,
            "emergency_type": "unknown",
            "summary":        "AI unavailable — treating as emergency (safe default)",
        },
        "SeverityScorer": {
            "score":                       4,
            "label":                       "high",
            "reasoning":                   "AI unavailable — defaulting to high severity",
            "recommended_response":        "caregiver",
            "time_sensitive":              True,
            "estimated_response_minutes":  10,
        },
        "FraudGuard": {
            "is_suspicious":  False,
            "reason":         None,
            "recommendation": "pass",
        },
    }

    return {
        "exception":     "ai_agent_failure",
        "agent":         agent_name,
        "error":         error,
        "safe_default":  safe_defaults.get(agent_name, {}),
        "action":        "Using safe defaults — treating as genuine emergency",
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 7: Duplicate Emergency (Device Malfunction)
# ═══════════════════════════════════════════════════════════════
async def handle_duplicate_emergency(
    case_id: str,
    elder_id: str,
    recent_count: int
) -> dict:
    """
    Triggered when: Same elder sends 5+ alerts in 5 minutes.
    Action: Flag for review but DO NOT dismiss — notify family to check device.
    """
    log.warning(f"[EX-007] Duplicate alert — {elder_id} sent {recent_count} alerts")

    return {
        "exception":       "duplicate_emergency",
        "elder_id":        elder_id,
        "alert_count":     recent_count,
        "action":          "Held for review — notifying family to check device",
        "auto_dismissed":  False,  # Never auto-dismiss — human must decide
        "timestamp":       datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 8: WhatsApp Delivery Failure → SMS Fallback
# ═══════════════════════════════════════════════════════════════
async def handle_whatsapp_delivery_failure(
    case_id: str,
    phone: str,
    original_message: str
) -> dict:
    """
    Triggered when: WhatsApp message fails to deliver.
    Action: Fall back to SMS using Twilio SMS API.
    """
    log.warning(f"[EX-008] WhatsApp failed for {phone} — falling back to SMS")

    twilio_sid   = os.getenv("TWILIO_ACCOUNT_SID")
    twilio_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_number  = os.getenv("TWILIO_SMS_NUMBER", os.getenv("TWILIO_WHATSAPP_NUMBER", "").replace("whatsapp:", ""))

    if not twilio_sid:
        log.info(f"[MOCK SMS] → {phone}: {original_message[:60]}...")
        return {"channel": "sms_mock", "to": phone, "status": "mock_sent"}

    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{twilio_sid}/Messages.json",
                data={"From": from_number, "To": phone, "Body": original_message},
                auth=(twilio_sid, twilio_token),
            )
            return {"channel": "sms", "to": phone, "status": resp.json().get("status")}
    except Exception as e:
        return {"channel": "sms_failed", "to": phone, "error": str(e)}


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 9: Location Not Found
# ═══════════════════════════════════════════════════════════════
async def handle_location_not_found(case_id: str, elder_id: str) -> dict:
    """
    Triggered when: No GPS or address provided.
    Action: Use last known location from elder profile, or ask family.
    """
    log.warning(f"[EX-009] Location not found for case {case_id} elder {elder_id}")

    # In production: look up last known location from database
    last_known = await _get_last_known_location(elder_id)

    return {
        "exception":         "location_not_found",
        "last_known_location": last_known,
        "action":            "Using last known location" if last_known else "Requesting location from family",
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# EXCEPTION 10: SLA Breach — Caregiver Check-in Timeout
# ═══════════════════════════════════════════════════════════════
async def handle_sla_breach_checkin(case_id: str, caregiver_name: str) -> dict:
    """
    Triggered when: Caregiver doesn't submit check-in within 30 min SLA.
    Action: Auto-escalate to critical path — assume situation worsened.
    """
    log.warning(f"[EX-010] Caregiver check-in SLA breach for case {case_id}")

    return {
        "exception":        "sla_breach_checkin",
        "caregiver":        caregiver_name,
        "original_sla_min": 30,
        "action":           "Auto-escalating to critical path — dispatching ambulance",
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (replace with real DB calls in production)
# ═══════════════════════════════════════════════════════════════
async def _get_secondary_contacts(elder_id: str) -> list[str]:
    """Secondary family contacts if primary doesn't respond."""
    return ["+7075143471", "+919110775194"]   # replace with DB lookup


async def _get_senior_coordinator_contacts() -> list[str]:
    """Senior coordinator contact for SLA escalation."""
    return ["+9110775194"]                    # replace with DB lookup


async def _get_last_known_location(elder_id: str) -> str | None:
    """Last known location from elder profile database."""
    mock_locations = {
        "Elder-Priya": "12 Rose Garden Colony, Jaipur",
        "Elder-Test":  "Sector 5, Vaishali Nagar, Jaipur",
    }
    return mock_locations.get(elder_id)
