# 🚨 ElderCare Emergency Response
### UiPath AgentHack 2026 — Track 1: UiPath Maestro Case

> *An elderly woman says "Help me." Within seconds, AI agents classify the emergency, score severity, alert family via WhatsApp, find the nearest hospital, and create a UiPath Maestro case awaiting human approval to dispatch an ambulance — all while a live dashboard tracks every step.*

---

## 🏗 Architecture

```
Voice / WhatsApp / Web / IoT
           ↓
     FastAPI Backend
           ↓
   ┌───────────────────────────┐
   │      AI Agent Layer       │
   │  EmergencyDetector (Claude)│
   │  SeverityScorer   (Claude)│
   │  FraudGuard       (Claude)│
   └───────────────────────────┘
           ↓
   UiPath Maestro Case Engine
   (Automation Cloud · BPMN)
           ↓
   ┌──────────────┬────────────┐
   │ HospitalFinder│ FamilyAlert│
   │ (Google Maps) │(Twilio WA) │
   └──────────────┴────────────┘
           ↓
   Human Approval Gate
   (Medical coordinator UI)
           ↓
   🚑 Ambulance Dispatched
           ↓
   Live Dashboard (WebSocket)
```

---

## 🎯 Challenge Track

**Track 1: UiPath Maestro Case**

Our solution orchestrates a real eldercare emergency response across:
- **AI agents** (Claude via Anthropic API) for classification, triage, and fraud detection
- **UiPath Maestro Case** for case lifecycle management with BPMN stages
- **Human-in-the-loop** approval before ambulance dispatch (safety-critical)
- **UiPath Robots** for WhatsApp notifications and external API calls
- **Live dashboard** for coordinators with real-time WebSocket updates

### Bonus: Coding Agents
The AI detection/scoring/fraud agents call Claude directly, and the backend was built with Claude Code — combining agentic coding with low-code UiPath orchestration.

---

## 📁 Project Structure

```
eldercare/
├── backend/
│   ├── main.py                    # FastAPI app — event ingestion, WebSocket, approval
│   ├── agents/
│   │   ├── emergency_detector.py  # Claude agent — emergency classification
│   │   ├── severity_scorer.py     # Claude agent — 1–5 severity triage
│   │   ├── fraud_guard.py         # Claude agent — false-alarm detection
│   │   ├── hospital_finder.py     # Google Maps / mock hospital search
│   │   └── notifier.py            # Twilio WhatsApp + push notifications
│   ├── requirements.txt
│   └── Dockerfile
├── uipath/
│   └── maestro_case_definition.json   # Full BPMN case definition for UiPath
├── dashboard/
│   └── index.html                 # Live coordinator dashboard (WebSocket)
├── docker-compose.yml
└── .env.example
```

---

## 🚀 Quick Start

### 1. Clone and configure
```bash
git clone https://github.com/yourteam/eldercare-agenthack
cd eldercare-agenthack
cp .env.example .env
# Fill in: ANTHROPIC_API_KEY, UIPATH_*, TWILIO_*, GOOGLE_MAPS_API_KEY
```

### 2. Run with Docker Compose
```bash
docker-compose up --build
```

### 3. Open the dashboard
```
http://localhost:3000
```

### 4. Trigger a test emergency
```bash
curl -X POST http://localhost:8000/emergency \
  -H "Content-Type: application/json" \
  -d '{
    "source": "voice",
    "raw_text": "Help me, I fell down and I cannot get up!",
    "location": "12 Rose Garden Colony, Jaipur",
    "elder_id": "Elder-Priya",
    "lat": 26.9124,
    "lon": 75.7873
  }'
```
Watch the dashboard update in real time!

### 5. Approve ambulance dispatch
```bash
curl -X POST http://localhost:8000/approve \
  -H "Content-Type: application/json" \
  -d '{
    "case_id": "<case_id from above>",
    "approved_by": "Dr. Sharma",
    "action": "dispatch_ambulance",
    "notes": "Reviewed — severity 4, dispatch confirmed"
  }'
```

---

## 🤖 AI Agents

| Agent | Model | Role |
|---|---|---|
| EmergencyDetector | claude-sonnet-4 | Classifies intent: fall / medical / fire / intruder |
| SeverityScorer | claude-sonnet-4 | Scores 1–5, recommends response level |
| FraudGuard | claude-sonnet-4 | Filters false alarms, duplicate calls |
| HospitalFinder | Google Maps API | Finds nearest ER with ETA |
| Notifier | Twilio / WhatsApp | Alerts family and caregiver |

All agents run in **parallel where safe** (hospital search + notification run concurrently after triage).

---

## 📋 UiPath Maestro Case Stages

```
intake → triage → critical_response → dispatched → resolved
                ↘ standard_response → monitoring → resolved
intake → review → triage (if genuine) | dismissed (if false alarm)
```

Human tasks:
- **Approve ambulance dispatch** — `role:MedicalCoordinator`, 2-min SLA, escalates to senior
- **Caregiver check-in** — assigned to matched caregiver, 30-min SLA
- **Review suspicious alert** — `role:Supervisor`, 10-min SLA

---

## 🔗 UiPath Automation Cloud Setup

1. Go to [cloud.uipath.com](https://cloud.uipath.com)
2. Navigate to **Maestro → Case Definitions**
3. Import `uipath/maestro_case_definition.json`
4. Deploy processes:
   - `ElderCare.EmergencyDetector` — calls FastAPI `/emergency` endpoint
   - `ElderCare.WhatsAppNotifier` — Twilio robot
   - `ElderCare.HospitalFinder` — Google Maps robot
   - `ElderCare.CaregiverMatcher` — matching database lookup
5. Set environment variables in Orchestrator → Connections

---

## 🌍 Real-world Impact

- **2.1 billion** people will be 60+ by 2050 (WHO)
- Falls are the leading cause of fatal injury in adults over 65
- Average emergency response time without automation: **8–12 minutes**
- With ElderCare: **<30 seconds** from signal to notification, <2 min to human approval

---

## 👥 Team

Built with ❤️ for UiPath AgentHack 2026

---

## 📜 License

MIT
