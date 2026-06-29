"""
ElderCare Emergency Response — FastAPI Backend
UiPath AgentHack 2026 · Track 1: UiPath Maestro Case
Updated: Correct Maestro taasBaseUrl + Groq + Twilio 429 fix
"""

from __future__ import annotations
import os, uuid, asyncio, json, logging
from datetime import datetime, timezone
from typing import Optional

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
load_dotenv()

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import httpx

from agents.emergency_detector import EmergencyDetectorAgent
from agents.severity_scorer    import SeverityAgent
from agents.fraud_guard        import FraudGuardAgent
from agents.hospital_finder    import HospitalFinderAgent
from agents.notifier           import NotifierAgent
from process_routes            import router as process_router
from exception_handler import (
    handle_family_not_responding,
    handle_no_caregiver_available,
    handle_sla_breach_approval,
    handle_ai_agent_failure,
    handle_duplicate_emergency,
    handle_hospital_unavailable,
    handle_location_not_found,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ── Startup key checks ─────────────────────────────────────────────────────────
def _mask(v: str) -> str:
    return v[:8] + "..." + v[-4:] if len(v) > 12 else "***"

groq_key   = os.getenv("GROQ_API_KEY", "") or os.getenv("GROK_API_KEY", "")
twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
uipath_tok = os.getenv("UIPATH_ACCESS_TOKEN", "")

log.info(f"GROQ:   {'✅ ' + _mask(groq_key)  if groq_key   else '❌ NOT SET'}")
log.info(f"Twilio: {'✅ ' + _mask(twilio_sid) if twilio_sid else '❌ NOT SET (mock)'}")
log.info(f"UiPath: {'✅ set' if uipath_tok else '⚠️  NOT SET (mock Maestro)'}")

# ── Discovered Maestro metadata (from HTML) ───────────────────────────────────
# These are extracted from the HTML response of staging.uipath.com
MAESTRO_TAAS_URL = "https://taas.shared-stg-svc-ne-01.stg.kubefabric.uipath.systems"
MAESTRO_TENANT_ID = "3b34a582-b9f4-4b76-980d-2768b2e9cd1d"
MAESTRO_ACCOUNT_ID = "07bb327c-38bf-4bde-9e6d-bc8fe4cf59b6"

app = FastAPI(title="ElderCare Emergency API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(process_router, prefix="/process", tags=["UiPath Processes"])

# ── In-memory case store ───────────────────────────────────────────────────────
cases: dict[str, dict] = {}

# ── WebSocket manager ──────────────────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, data: dict):
        payload = json.dumps(data)
        dead = []
        for ws in self.active:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.active.remove(ws)

ws_manager = ConnectionManager()

# ── Models ─────────────────────────────────────────────────────────────────────
class EmergencyEvent(BaseModel):
    source:    str           = Field(..., examples=["voice"])
    raw_text:  str           = Field(..., examples=["Help me I fell down!"])
    location:  Optional[str] = None
    elder_id:  Optional[str] = None
    lat:       Optional[float] = None
    lon:       Optional[float] = None
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

class ApprovalRequest(BaseModel):
    case_id:     str
    approved_by: str
    action:      str
    notes:       Optional[str] = None


# ══════════════════════════════════════════════════════════════════════════════
# PIPELINE
# ══════════════════════════════════════════════════════════════════════════════
async def run_emergency_pipeline(case_id: str, event: EmergencyEvent):

    def update(stage: str, data: dict = {}):
        _update_case(case_id, stage, data)

    # Location fallback
    if not event.location and not (event.lat and event.lon):
        loc_ex = await handle_location_not_found(case_id, event.elder_id or "")
        event.location = loc_ex.get("last_known_location") or "Location unknown"
        update("location_resolved", {"exception": loc_ex})

    # Step 1: Emergency detection
    update("detecting")
    detector = EmergencyDetectorAgent()
    try:
        detection = await detector.run(event.raw_text, event.source)
    except Exception as e:
        ex = await handle_ai_agent_failure(case_id, "EmergencyDetector", str(e))
        detection = ex["safe_default"]
        update("ai_fallback", {"exception": ex})

    update("detected", {"detection": detection})
    if not detection.get("is_emergency", True):
        update("dismissed", {"reason": "AI: not an emergency"})
        return

    # Step 2: Severity
    update("scoring_severity")
    scorer = SeverityAgent()
    try:
        severity = await scorer.run(event.raw_text, detection)
    except Exception as e:
        ex = await handle_ai_agent_failure(case_id, "SeverityScorer", str(e))
        severity = ex["safe_default"]
        update("ai_fallback", {"exception": ex})
    update("severity_scored", {"severity": severity})

    # Step 3: Fraud
    update("fraud_check")
    guard = FraudGuardAgent()
    try:
        fraud = await guard.run(event.raw_text, event.elder_id, cases)
    except Exception as e:
        ex = await handle_ai_agent_failure(case_id, "FraudGuard", str(e))
        fraud = ex["safe_default"]
        update("ai_fallback", {"exception": ex})
    update("fraud_checked", {"fraud": fraud})

    # Duplicate check
    if event.elder_id:
        recent = sum(
            1 for c in cases.values()
            if c.get("event", {}).get("elder_id") == event.elder_id
            and c["id"] != case_id
        )
        if recent >= 5:
            dup_ex = await handle_duplicate_emergency(case_id, event.elder_id, recent)
            update("held_duplicate", {"exception": dup_ex})
            return

    if fraud.get("is_suspicious", False):
        update("held_for_review", {"reason": fraud.get("reason", "Fraud flag")})
        return

    # Step 4: Create Maestro case
    update("creating_maestro_case")
    maestro_case = await create_maestro_case(case_id, event, detection, severity)
    update("maestro_case_created", {"maestro": maestro_case})

    # Step 5: Parallel actions
    update("parallel_actions")
    finder = HospitalFinderAgent()
    notif  = NotifierAgent()

    hospital_task  = asyncio.create_task(finder.run(event.lat, event.lon, event.location))
    caregiver_task = asyncio.create_task(_match_caregiver(event))
    notify_task    = asyncio.create_task(notif.notify_family(case_id, event, severity))

    hospital, caregiver_result, notify_result = await asyncio.gather(
        hospital_task, caregiver_task, notify_task,
        return_exceptions=True
    )

    # Hospital fallback
    if isinstance(hospital, Exception) or not (isinstance(hospital, dict) and hospital.get("nearest")):
        hospital = {
            "nearest": {"name": "Sawai Man Singh Hospital", "eta_min": 10, "distance_km": 2.1},
            "source": "fallback",
        }

    # Caregiver fallback
    if isinstance(caregiver_result, Exception) or not caregiver_result.get("assigned", False):
        cg_ex = await handle_no_caregiver_available(case_id, severity)
        update("caregiver_exception", {"exception": cg_ex})
        caregiver_result = {"assigned": False, "caregiver_name": "None available", "action": cg_ex["action"]}

    # Notification — handle 429 rate limit
    if isinstance(notify_result, Exception):
        notify_result = {"notified": 0, "error": str(notify_result)}
    elif notify_result.get("notified", 0) == 0:
        contacts     = notify_result.get("contacts", [])
        rate_limited = any(
            "429" in str(c.get("error", "")) or "Too Many" in str(c.get("error", ""))
            for c in contacts
        )
        if rate_limited:
            log.warning("[Pipeline] Twilio 429 — waiting 3s then retry")
            await asyncio.sleep(3)
            notify_result = await notif.notify_family(case_id, event, severity)
            update("notification_retried", {"notify": notify_result})
        else:
            family_ex = await handle_family_not_responding(case_id, event, severity)
            update("family_not_responding", {"exception": family_ex})

    update("awaiting_human_approval", {
        "hospital":        hospital,
        "caregiver":       caregiver_result,
        "notify":          notify_result,
        "action_required": "Approve ambulance dispatch",
    })

    # SLA watchdog — 15 min to match Maestro minimum
    asyncio.create_task(_sla_watchdog(case_id, sla_minutes=15))
    log.info(f"[Pipeline] Case {case_id} awaiting human approval")


async def _match_caregiver(event: EmergencyEvent) -> dict:
    api_base = os.getenv("SELF_API_URL", "http://localhost:8000")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(f"{api_base}/process/match-caregiver", json={
                "location": event.location or "",
                "lat":      event.lat or 0.0,
                "lon":      event.lon or 0.0,
                "severity_score": 4,
                "emergency_type": "fall",
                "case_id":  "internal",
            })
            return r.json()
    except Exception as e:
        return {"assigned": False, "error": str(e)}


async def _sla_watchdog(case_id: str, sla_minutes: int = 15):
    await asyncio.sleep(sla_minutes * 60)
    if case_id in cases and cases[case_id].get("stage") == "awaiting_human_approval":
        log.warning(f"[SLA Watchdog] Case {case_id} breached {sla_minutes}min SLA")
        sla_ex = await handle_sla_breach_approval(case_id, cases[case_id])
        _update_case(case_id, "sla_breach_escalated", {"exception": sla_ex})


def _update_case(case_id: str, stage: str, data: dict = {}):
    if case_id not in cases:
        return
    cases[case_id]["stage"] = stage
    cases[case_id]["history"].append({
        "stage": stage,
        "ts":    datetime.now(timezone.utc).isoformat(),
        **data,
    })
    asyncio.create_task(ws_manager.broadcast({
        "type":    "case_update",
        "case_id": case_id,
        "stage":   stage,
        "data":    data,
        "case":    cases[case_id],
    }))


# ══════════════════════════════════════════════════════════════════════════════
# MAESTRO CASE CREATION
# Uses taasBaseUrl discovered from HTML metadata
# ══════════════════════════════════════════════════════════════════════════════
async def create_maestro_case(case_id, event, detection, severity):
    """
    Triggers Maestro case via webhook URL.
    This is the correct way — NOT via /api/v1/cases POST.
    """
    webhook_url = os.getenv("MAESTRO_WEBHOOK_URL", "").strip()
    orch_token  = os.getenv("UIPATH_ACCESS_TOKEN", "").strip()

    if not webhook_url:
        log.warning("MAESTRO_WEBHOOK_URL not set — mock case")
        return {"id": f"EC-{case_id[:6].upper()}", "status": "mock_created"}

    # Payload matches the trigger field mappings you set in Maestro
    payload = {
        "case_id":        case_id,
        "elder_id":       event.elder_id or "",
        "raw_text":       event.raw_text,
        "source":         event.source,
        "location":       event.location or "",
        "lat":            str(event.lat or 0.0),
        "lon":            str(event.lon or 0.0),
        "is_emergency":   str(detection.get("is_emergency", True)),
        "emergency_type": detection.get("emergency_type", "unknown"),
        "summary":        detection.get("summary", ""),
        "confidence":     str(detection.get("confidence", 0.8)),
        "severity": str(severity.get("score", 4)),
        "severity_label": severity.get("label", "high"),
    }

    headers = {"Content-Type": "application/json"}
    if orch_token:
        headers["Authorization"] = f"Bearer {orch_token}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.post(webhook_url, json=payload, headers=headers)
            log.info(f"Maestro webhook status: {resp.status_code}")

            if resp.status_code in [200, 201, 202]:
                log.info("✅ Maestro case triggered via webhook")
                try:
                    return resp.json()
                except Exception:
                    return {"id": f"EC-TRIGGERED", "status": "triggered"}
            else:
                log.warning(f"Webhook returned {resp.status_code}: {resp.text[:200]}")
                raise Exception(f"Webhook failed: {resp.status_code}")

    except Exception as e:
        log.warning(f"Maestro webhook failed: {e} — mock case")
        return {"id": f"EC-{case_id[:6].upper()}", "status": "mock_created"}


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/emergency", status_code=202)
async def report_emergency(event: EmergencyEvent, background_tasks: BackgroundTasks):
    case_id = str(uuid.uuid4())
    cases[case_id] = {
        "id":         case_id,
        "stage":      "received",
        "event":      event.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "history":    [],
        "exceptions": [],
    }
    background_tasks.add_task(run_emergency_pipeline, case_id, event)
    return {"case_id": case_id, "status": "processing"}


@app.post("/approve")
async def approve_action(req: ApprovalRequest):
    if req.case_id not in cases:
        raise HTTPException(404, "Case not found")
    case                = cases[req.case_id]
    case["stage"]       = f"approved:{req.action}"
    case["approved_by"] = req.approved_by
    case["history"].append({
        "stage":       f"approved:{req.action}",
        "ts":          datetime.now(timezone.utc).isoformat(),
        "action":      req.action,
        "approved_by": req.approved_by,
        "notes":       req.notes,
    })
    if req.action == "dispatch_ambulance":
        notif = NotifierAgent()
        asyncio.create_task(notif.notify_ambulance_dispatched(req.case_id, case))
        case["stage"] = "ambulance_dispatched"
    await ws_manager.broadcast({
        "type":    "human_approval",
        "case_id": req.case_id,
        "action":  req.action,
        "case":    case,
    })
    return {"status": "approved", "case": case}


@app.get("/cases")
async def list_cases():
    return {"cases": list(cases.values())}


@app.get("/cases/{case_id}")
async def get_case(case_id: str):
    if case_id not in cases:
        raise HTTPException(404, "Case not found")
    return cases[case_id]


@app.get("/cases/{case_id}/exceptions")
async def get_case_exceptions(case_id: str):
    if case_id not in cases:
        raise HTTPException(404, "Case not found")
    history    = cases[case_id].get("history", [])
    exceptions = [h for h in history if "exception" in h]
    return {"case_id": case_id, "exceptions": exceptions, "count": len(exceptions)}


@app.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        await ws.send_text(json.dumps({"type": "init", "cases": list(cases.values())}))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


@app.get("/health")
async def health():
    return {
        "status":       "ok",
        "active_cases": len(cases),
        "groq_set":     bool(os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY")),
        "twilio_set":   bool(os.getenv("TWILIO_ACCOUNT_SID")),
        "uipath_set":   bool(os.getenv("UIPATH_ACCESS_TOKEN")),
        "sla_minutes":  15,
    }






# ------------------------------------------------------------------------------------------------------------------------------------------
# """
# ElderCare Emergency Response — FastAPI Backend
# UiPath AgentHack 2026 · Track 1: UiPath Maestro Case
# Updated: Groq support + Maestro 405 fix + Twilio 429 fix + SLA 15 min
# """

# from __future__ import annotations
# import os, uuid, asyncio, json, logging
# from datetime import datetime, timezone
# from typing import Optional

# from dotenv import load_dotenv
# load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))
# load_dotenv()  # fallback — also try current directory

# from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks
# from fastapi.middleware.cors import CORSMiddleware
# from pydantic import BaseModel, Field
# import httpx

# from agents.emergency_detector import EmergencyDetectorAgent
# from agents.severity_scorer    import SeverityAgent
# from agents.fraud_guard        import FraudGuardAgent
# from agents.hospital_finder    import HospitalFinderAgent
# from agents.notifier           import NotifierAgent
# from process_routes            import router as process_router
# from exception_handler import (
#     handle_family_not_responding,
#     handle_no_caregiver_available,
#     handle_sla_breach_approval,
#     handle_ai_agent_failure,
#     handle_duplicate_emergency,
#     handle_hospital_unavailable,
#     handle_location_not_found,
# )

# logging.basicConfig(level=logging.INFO)
# log = logging.getLogger(__name__)

# # ── Startup checks ─────────────────────────────────────────────────────────────
# def _mask(val: str) -> str:
#     return val[:8] + "..." + val[-4:] if len(val) > 12 else "***"

# groq_key   = os.getenv("GROQ_API_KEY", "") or os.getenv("GROK_API_KEY", "")
# twilio_sid = os.getenv("TWILIO_ACCOUNT_SID", "")
# uipath_tok = os.getenv("UIPATH_ACCESS_TOKEN", "")

# log.info(f"GROQ key:    {'✅ ' + _mask(groq_key) if groq_key else '❌ NOT SET'}")
# log.info(f"Twilio SID:  {'✅ ' + _mask(twilio_sid) if twilio_sid else '❌ NOT SET (mock mode)'}")
# log.info(f"UiPath tok:  {'✅ set' if uipath_tok else '⚠️  NOT SET (mock Maestro)'}")

# app = FastAPI(title="ElderCare Emergency API", version="1.0.0")

# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=["*"],
#     allow_methods=["*"],
#     allow_headers=["*"],
# )

# app.include_router(process_router, prefix="/process", tags=["UiPath Processes"])

# # ── In-memory case store ───────────────────────────────────────────────────────
# cases: dict[str, dict] = {}

# # ── WebSocket connection manager ───────────────────────────────────────────────
# class ConnectionManager:
#     def __init__(self):
#         self.active: list[WebSocket] = []

#     async def connect(self, ws: WebSocket):
#         await ws.accept()
#         self.active.append(ws)

#     def disconnect(self, ws: WebSocket):
#         if ws in self.active:
#             self.active.remove(ws)

#     async def broadcast(self, data: dict):
#         payload = json.dumps(data)
#         dead = []
#         for ws in self.active:
#             try:
#                 await ws.send_text(payload)
#             except Exception:
#                 dead.append(ws)
#         for ws in dead:
#             self.active.remove(ws)

# ws_manager = ConnectionManager()

# # ── Request / Response models ──────────────────────────────────────────────────
# class EmergencyEvent(BaseModel):
#     source:    str           = Field(..., examples=["voice", "whatsapp", "web", "iot"])
#     raw_text:  str           = Field(..., examples=["Help me, I fell down!"])
#     location:  Optional[str] = Field(None, examples=["12 Rose Garden, Jaipur"])
#     elder_id:  Optional[str] = None
#     lat:       Optional[float] = None
#     lon:       Optional[float] = None
#     timestamp: str           = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

# class ApprovalRequest(BaseModel):
#     case_id:     str
#     approved_by: str
#     action:      str
#     notes:       Optional[str] = None


# # ══════════════════════════════════════════════════════════════════════════════
# # CORE PIPELINE
# # ══════════════════════════════════════════════════════════════════════════════
# async def run_emergency_pipeline(case_id: str, event: EmergencyEvent):

#     def update(stage: str, data: dict = {}):
#         _update_case(case_id, stage, data)

#     # ── Handle missing location ────────────────────────────────────────────────
#     if not event.location and not (event.lat and event.lon):
#         log.warning(f"[Pipeline] No location for case {case_id}")
#         location_ex    = await handle_location_not_found(case_id, event.elder_id or "")
#         event.location = location_ex.get("last_known_location") or "Location unknown"
#         update("location_resolved", {"exception": location_ex})

#     # ── STEP 1: Emergency detection ────────────────────────────────────────────
#     update("detecting")
#     detector = EmergencyDetectorAgent()
#     try:
#         detection = await detector.run(event.raw_text, event.source)
#     except Exception as e:
#         ex        = await handle_ai_agent_failure(case_id, "EmergencyDetector", str(e))
#         detection = ex["safe_default"]
#         update("ai_fallback", {"exception": ex})

#     update("detected", {"detection": detection})

#     if not detection.get("is_emergency", True):
#         update("dismissed", {"reason": "AI determined this is not an emergency"})
#         return

#     # ── STEP 2: Severity scoring ───────────────────────────────────────────────
#     update("scoring_severity")
#     scorer = SeverityAgent()
#     try:
#         severity = await scorer.run(event.raw_text, detection)
#     except Exception as e:
#         ex       = await handle_ai_agent_failure(case_id, "SeverityScorer", str(e))
#         severity = ex["safe_default"]
#         update("ai_fallback", {"exception": ex})

#     update("severity_scored", {"severity": severity})

#     # ── STEP 3: Fraud check ────────────────────────────────────────────────────
#     update("fraud_check")
#     guard = FraudGuardAgent()
#     try:
#         fraud = await guard.run(event.raw_text, event.elder_id, cases)
#     except Exception as e:
#         ex    = await handle_ai_agent_failure(case_id, "FraudGuard", str(e))
#         fraud = ex["safe_default"]
#         update("ai_fallback", {"exception": ex})

#     update("fraud_checked", {"fraud": fraud})

#     # ── STEP 3a: Duplicate check ───────────────────────────────────────────────
#     if event.elder_id:
#         recent_count = sum(
#             1 for c in cases.values()
#             if c.get("event", {}).get("elder_id") == event.elder_id
#             and c["id"] != case_id
#         )
#         if recent_count >= 5:
#             dup_ex = await handle_duplicate_emergency(case_id, event.elder_id, recent_count)
#             update("held_duplicate", {"exception": dup_ex})
#             return

#     if fraud.get("is_suspicious", False):
#         update("held_for_review", {"reason": fraud.get("reason", "Flagged by fraud guard")})
#         return

#     # ── STEP 4: Create Maestro case ───────────────────────────────────────────
#     update("creating_maestro_case")
#     maestro_case = await create_maestro_case(case_id, event, detection, severity)
#     update("maestro_case_created", {"maestro": maestro_case})

#     # ── STEP 5: Parallel — hospital + caregiver + family notification ──────────
#     update("parallel_actions")

#     finder = HospitalFinderAgent()
#     notif  = NotifierAgent()

#     hospital_task  = asyncio.create_task(finder.run(event.lat, event.lon, event.location))
#     caregiver_task = asyncio.create_task(_match_caregiver(event))
#     notify_task    = asyncio.create_task(notif.notify_family(case_id, event, severity))

#     hospital, caregiver_result, notify_result = await asyncio.gather(
#         hospital_task, caregiver_task, notify_task,
#         return_exceptions=True
#     )

#     # ── Handle hospital exception ──────────────────────────────────────────────
#     if isinstance(hospital, Exception):
#         log.error(f"[Pipeline] Hospital finder failed: {hospital}")
#         hospital = {
#             "nearest": {"name": "Sawai Man Singh Hospital", "eta_min": 10, "distance_km": 2.1},
#             "source":  "fallback",
#         }
#     elif not hospital.get("nearest"):
#         hosp_ex  = await handle_hospital_unavailable(
#             case_id,
#             "Unknown",
#             event.lat or 26.9124,
#             event.lon or 75.7873,
#         )
#         hospital = hosp_ex.get("backup_hospital", hospital)
#         update("hospital_exception", {"exception": hosp_ex})

#     # ── Handle caregiver exception ─────────────────────────────────────────────
#     if isinstance(caregiver_result, Exception) or not caregiver_result.get("assigned", False):
#         cg_ex = await handle_no_caregiver_available(case_id, severity)
#         update("caregiver_exception", {"exception": cg_ex})
#         caregiver_result = {
#             "assigned":       False,
#             "caregiver_name": "No caregiver available",
#             "action":         cg_ex["action"],
#         }

#     # ── Handle notification exception — check for 429 rate limit ──────────────
#     if isinstance(notify_result, Exception):
#         log.error(f"[Pipeline] Notification failed: {notify_result}")
#         notify_result = {"notified": 0, "error": str(notify_result)}

#     elif notify_result.get("notified", 0) == 0:
#         # Check if failure was due to Twilio rate limit (429)
#         contacts     = notify_result.get("contacts", [])
#         rate_limited = any(
#             "429" in str(c.get("error", "")) or "Too Many" in str(c.get("error", ""))
#             for c in contacts
#         )

#         if rate_limited:
#             # Wait 3 seconds then retry once
#             log.warning("[Pipeline] Twilio 429 rate limit — waiting 3s before retry")
#             await asyncio.sleep(3)
#             retry_result = await notif.notify_family(case_id, event, severity)
#             notify_result = retry_result
#             update("notification_retried", {"notify": retry_result})
#         else:
#             # Genuine failure — try secondary contacts
#             log.warning("[Pipeline] Family not reached — triggering secondary contacts")
#             family_ex = await handle_family_not_responding(case_id, event, severity)
#             update("family_not_responding", {"exception": family_ex})
#             notify_result["exception"] = family_ex

#     update("awaiting_human_approval", {
#         "hospital":        hospital,
#         "caregiver":       caregiver_result,
#         "notify":          notify_result,
#         "action_required": "Approve ambulance dispatch",
#     })

#     # ── STEP 6: SLA watchdog — 15 min to match Maestro minimum ────────────────
#     asyncio.create_task(_sla_watchdog(case_id, sla_minutes=15))

#     log.info(f"[Pipeline] Case {case_id} awaiting human approval")


# # ══════════════════════════════════════════════════════════════════════════════
# # HELPERS
# # ══════════════════════════════════════════════════════════════════════════════
# async def _match_caregiver(event: EmergencyEvent) -> dict:
#     """Internal caregiver match — calls process route."""
#     api_base = os.getenv("SELF_API_URL", "http://localhost:8000")
#     payload  = {
#         "location":       event.location or "",
#         "lat":            event.lat or 0.0,
#         "lon":            event.lon or 0.0,
#         "severity_score": 4,
#         "emergency_type": "fall",
#         "case_id":        "internal",
#     }
#     try:
#         async with httpx.AsyncClient(timeout=10) as c:
#             r = await c.post(f"{api_base}/process/match-caregiver", json=payload)
#             return r.json()
#     except Exception as e:
#         log.error(f"[_match_caregiver] Failed: {e}")
#         return {"assigned": False, "error": str(e)}


# async def _sla_watchdog(case_id: str, sla_minutes: int = 15):
#     """
#     Waits SLA duration. If case still awaiting approval → escalate to senior.
#     Set to 15 min to match Maestro minimum SLA.
#     """
#     await asyncio.sleep(sla_minutes * 60)

#     if case_id not in cases:
#         return

#     case = cases[case_id]
#     if case.get("stage") == "awaiting_human_approval":
#         log.warning(f"[SLA Watchdog] Case {case_id} breached {sla_minutes}min SLA — escalating")
#         sla_ex = await handle_sla_breach_approval(case_id, case)
#         _update_case(case_id, "sla_breach_escalated", {"exception": sla_ex})


# def _update_case(case_id: str, stage: str, data: dict = {}):
#     if case_id not in cases:
#         return
#     cases[case_id]["stage"] = stage
#     cases[case_id]["history"].append({
#         "stage": stage,
#         "ts":    datetime.now(timezone.utc).isoformat(),
#         **data,
#     })
#     asyncio.create_task(ws_manager.broadcast({
#         "type":    "case_update",
#         "case_id": case_id,
#         "stage":   stage,
#         "data":    data,
#         "case":    cases[case_id],
#     }))


# # ══════════════════════════════════════════════════════════════════════════════
# # MAESTRO CASE CREATION — tries multiple endpoints, falls back to mock
# # ══════════════════════════════════════════════════════════════════════════════
# async def create_maestro_case(case_id, event, detection, severity):

#     orch_url   = os.getenv("UIPATH_ORCHESTRATOR_URL", "https://staging.uipath.com").rstrip("/")
#     orch_token = os.getenv("UIPATH_ACCESS_TOKEN", "").strip()
#     org        = os.getenv("UIPATH_ORG", "hackathon26_253").strip()
#     tenant     = os.getenv("UIPATH_TENANT", "DefaultTenant").strip()

#     log.info(f"Organization = {org}")
#     log.info(f"Tenant = {tenant}")

#     # Mock if token not configured
#     if not orch_token:
#         log.warning("UIPATH_ACCESS_TOKEN not set — mock Maestro case")
#         return {
#             "id":     f"MAESTRO-{case_id[:8].upper()}",
#             "status": "mock_created",
#             "note":   "Set UIPATH_ACCESS_TOKEN in .env for real Maestro integration",
#         }

#     headers = {
#         "Authorization":       f"Bearer {orch_token}",
#         "Content-Type":        "application/json",
#         "X-UIPATH-TenantName": tenant,
#         "X-UIPATH-OrganizationUnitId": "",
#     }

#     # Case input data
#     case_data = {
#         "case_id":        case_id,
#         "elder_id":       event.elder_id or "",
#         "raw_text":       event.raw_text,
#         "source":         event.source,
#         "location":       event.location or "",
#         "lat":            str(event.lat or 0.0),
#         "lon":            str(event.lon or 0.0),
#         "is_emergency":   str(detection.get("is_emergency", True)),
#         "emergency_type": detection.get("emergency_type", "unknown"),
#         "summary":        detection.get("summary", ""),
#         "confidence":     str(detection.get("confidence", 0.8)),
#         "severity_score": str(severity.get("score", 4)),
#         "severity_label": severity.get("label", "high"),
#     }

#     # All known Maestro staging endpoints to try
#     endpoints = [
#         {
#             "url":     f"{orch_url}/{org}/{tenant}/maestro_/api/v1/caseinstances",
#             "payload": {
#                 "processKey":      "ElderCareEmergencyResponse",
#                 "reference":       case_id,
#                 "inputArguments":  case_data,
#             }
#         },
#         {
#             "url":     f"{orch_url}/{org}/{tenant}/maestro_/api/v1/cases",
#             "payload": {
#                 "caseDefinitionKey": "ElderCareEmergencyResponse",
#                 "externalKey":       case_id,
#                 "data":              case_data,
#             }
#         },
#         {
#             "url":     f"{orch_url}/{org}/orchestrator_/odata/Jobs/UiPath.Server.Configuration.OData.StartJobs",
#             "payload": {
#                 "startInfo": {
#                     "ReleaseKey":        "",
#                     "JobsCount":         1,
#                     "Strategy":          "All",
#                     "InputArguments":    json.dumps(case_data),
#                 }
#             }
#         },
#     ]

#     async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
#         for ep in endpoints:
#             try:
#                 log.info(f"Calling Maestro URL: {ep['url']}")
#                 resp = await client.post(ep["url"], json=ep["payload"], headers=headers)
#                 log.info(f"Response status: {resp.status_code}")

#                 if resp.status_code in [200, 201, 202]:
#                     log.info(f"✅ Maestro case created via {ep['url']}")
#                     try:
#                         return resp.json()
#                     except Exception:
#                         return {"id": f"MAESTRO-{case_id[:8].upper()}", "status": "created"}

#                 elif resp.status_code == 401:
#                     log.error("401 Unauthorized — check UIPATH_ACCESS_TOKEN scopes")
#                     break   # No point trying other endpoints with bad token

#                 elif resp.status_code == 404:
#                     log.warning(f"404 — endpoint not found, trying next")
#                     continue

#                 elif resp.status_code == 405:
#                     log.warning(f"405 — method not allowed on this endpoint, trying next")
#                     continue

#                 else:
#                     log.warning(f"Maestro returned {resp.status_code} — trying next endpoint")
#                     log.info(f"Response body: {resp.text[:300]}")
#                     continue

#             except Exception as e:
#                 log.warning(f"Endpoint failed: {e} — trying next")
#                 continue

#     # All endpoints failed — return mock (non-blocking)
#     log.warning("All Maestro endpoints failed — using mock case (demo mode)")
#     return {
#         "id":     f"MAESTRO-{case_id[:8].upper()}",
#         "status": "mock_created",
#         "note":   "Maestro API unreachable — case tracked locally in dashboard",
#         "data":   case_data,
#     }


# # ══════════════════════════════════════════════════════════════════════════════
# # API ENDPOINTS
# # ══════════════════════════════════════════════════════════════════════════════

# @app.post("/emergency", status_code=202)
# async def report_emergency(event: EmergencyEvent, background_tasks: BackgroundTasks):
#     """Ingest emergency from any source and start the pipeline."""
#     case_id = str(uuid.uuid4())
#     cases[case_id] = {
#         "id":         case_id,
#         "stage":      "received",
#         "event":      event.model_dump(),
#         "created_at": datetime.now(timezone.utc).isoformat(),
#         "history":    [],
#         "exceptions": [],
#     }
#     background_tasks.add_task(run_emergency_pipeline, case_id, event)
#     return {"case_id": case_id, "status": "processing"}


# @app.post("/approve")
# async def approve_action(req: ApprovalRequest):
#     """Human coordinator approves or declines ambulance dispatch."""
#     if req.case_id not in cases:
#         raise HTTPException(404, "Case not found")

#     case                = cases[req.case_id]
#     case["stage"]       = f"approved:{req.action}"
#     case["approved_by"] = req.approved_by
#     case["history"].append({
#         "stage":       f"approved:{req.action}",
#         "ts":          datetime.now(timezone.utc).isoformat(),
#         "action":      req.action,
#         "approved_by": req.approved_by,
#         "notes":       req.notes,
#     })

#     if req.action == "dispatch_ambulance":
#         notif = NotifierAgent()
#         asyncio.create_task(notif.notify_ambulance_dispatched(req.case_id, case))
#         case["stage"] = "ambulance_dispatched"

#     await ws_manager.broadcast({
#         "type":    "human_approval",
#         "case_id": req.case_id,
#         "action":  req.action,
#         "case":    case,
#     })
#     return {"status": "approved", "case": case}


# @app.get("/cases")
# async def list_cases():
#     return {"cases": list(cases.values())}


# @app.get("/cases/{case_id}")
# async def get_case(case_id: str):
#     if case_id not in cases:
#         raise HTTPException(404, "Case not found")
#     return cases[case_id]


# @app.get("/cases/{case_id}/exceptions")
# async def get_case_exceptions(case_id: str):
#     """All exceptions that fired during a case."""
#     if case_id not in cases:
#         raise HTTPException(404, "Case not found")
#     history    = cases[case_id].get("history", [])
#     exceptions = [h for h in history if "exception" in h]
#     return {"case_id": case_id, "exceptions": exceptions, "count": len(exceptions)}


# @app.websocket("/ws/dashboard")
# async def dashboard_ws(ws: WebSocket):
#     """Live WebSocket — streams all case updates to dashboard."""
#     await ws_manager.connect(ws)
#     try:
#         await ws.send_text(json.dumps({
#             "type":  "init",
#             "cases": list(cases.values()),
#         }))
#         while True:
#             await ws.receive_text()
#     except WebSocketDisconnect:
#         ws_manager.disconnect(ws)


# @app.get("/health")
# async def health():
#     """Health check — shows which services are connected."""
#     groq_set   = bool(os.getenv("GROQ_API_KEY") or os.getenv("GROK_API_KEY"))
#     twilio_set = bool(os.getenv("TWILIO_ACCOUNT_SID"))
#     uipath_set = bool(os.getenv("UIPATH_ACCESS_TOKEN"))
#     return {
#         "status":        "ok",
#         "active_cases":  len(cases),
#         "groq_key_set":  groq_set,
#         "twilio_set":    twilio_set,
#         "uipath_set":    uipath_set,
#         "sla_minutes":   15,
#         "version":       "1.0.0",
#     }
