# 🚨 ElderCare Emergency Response

### UiPath AgentHack 2026 — Track 1: UiPath Maestro Case

> *An elderly person says "Help me." Within seconds, AI agents classify the emergency, assess its severity, notify caregivers, locate the nearest hospital, and create a UiPath Maestro case awaiting human approval before emergency services are dispatched.*

---

# 📖 Project Description

ElderCare Emergency Response is an AI-powered case management solution built on the UiPath Platform to automate the end-to-end handling of elder emergency incidents.

The solution receives emergency requests from multiple channels such as voice, WhatsApp, web applications, or IoT devices. AI agents analyze the incident, determine the severity, and recommend the appropriate response. UiPath Maestro then orchestrates the complete case lifecycle while keeping human operators in control of critical decisions such as ambulance dispatch.

By combining AI-driven decision making with UiPath Maestro's case orchestration capabilities, the solution significantly reduces emergency response time, improves coordination between caregivers and emergency responders, and provides complete visibility into every case.

---

# 🎯 Problem Statement

Emergency response for elderly individuals often involves multiple manual steps, delayed communication, and fragmented coordination between caregivers, hospitals, and emergency responders.

This project addresses these challenges by:

* Automatically analyzing emergency reports using AI
* Prioritizing emergencies based on severity
* Creating and managing cases with UiPath Maestro
* Routing human approval tasks through Action Center
* Notifying caregivers automatically
* Maintaining a complete audit trail throughout the case lifecycle

---

# 🏗 Solution Architecture

```text
Voice / WhatsApp / Web / IoT
           ↓
    API Workflow / Webhook
           ↓
     AI Agent Builder
           ↓
  Emergency Classification
  Severity Assessment
           ↓
   UiPath Maestro Case
   Management Engine
           ↓
 ┌──────────────┬──────────────┐
 │Hospital Search│Notifications│
 └──────────────┴──────────────┘
           ↓
 Human Approval
 (Action Center)
           ↓
 Emergency Response
           ↓
 Case Resolution
```

---

# 🛠 UiPath Components Used

This solution utilizes the following UiPath capabilities:

* ✅ UiPath Maestro
* ✅ UiPath Agent Builder
* ✅ Low-Code AI Agent
* ✅ API Workflows
* ✅ Action Center
* ✅ Action Apps
* ✅ Studio Web
* ✅ Integration Service
* ✅ UiPath Orchestrator
* ✅ HTTP Request Activities
* ✅ JSON Processing
* ✅ External LLM Integration

---

# 🤖 Agent Type

**Primary Agent Type:** Low-Code Agent

The solution combines:

* Low-Code AI Agent built using UiPath Agent Builder
* UiPath Maestro for end-to-end case orchestration
* API Workflows for external integrations
* Human-in-the-loop approvals through Action Center

No UiPath Coded Agents are used in this implementation.

---

# ⚙️ Solution Workflow

1. An emergency request is received from Voice, WhatsApp, Web, or IoT.
2. The request triggers a UiPath API Workflow through a webhook.
3. The AI Agent analyzes the emergency description.
4. The agent classifies the emergency and determines its severity.
5. UiPath Maestro automatically creates a new case.
6. Hospital search and caregiver notifications execute in parallel.
7. A Human Approval task is generated in Action Center.
8. A medical coordinator reviews the AI recommendation.
9. Once approved, emergency services are dispatched.
10. The case progresses through Maestro until successful resolution.

---

# 🤖 AI Capabilities

The AI Agent performs:

* Emergency intent classification
* Severity assessment
* Recommended response generation
* Structured incident extraction
* AI-assisted decision support for operators

---

# 📋 UiPath Maestro Case Stages

```text
Intake
   ↓
AI Analysis
   ↓
Case Creation
   ↓
Human Review
   ↓
Approved?
 ├── Yes → Emergency Response → Monitoring → Resolved
 └── No  → Closed / Escalated
```

---

# 🚀 Setup Instructions

## Prerequisites

* UiPath Automation Cloud Account
* UiPath Maestro enabled
* Agent Builder enabled
* Action Center enabled
* Integration Service enabled
* Data Service enabled
* Studio Web
* External LLM API Key

---

## Step 1 – Clone the Repository

```bash
git clone https://github.com/<your-username>/eldercare-emergency-response.git
cd eldercare-emergency-response
```

---

## Step 2 – Import the Solution

Import the solution into your UiPath Automation Cloud tenant.

---

## Step 3 – Configure Data Service

Create the required Data Service entities.

Example entities:

* Emergency Data
* Case Information
* Elder Information (optional)

---

## Step 4 – Configure Agent Builder

1. Import the AI Agent.
2. Configure the LLM connection.
3. Add the required API credentials.
4. Publish the agent.

---

## Step 5 – Configure Maestro

1. Import the Maestro Case Definition.
2. Create the Case Type.
3. Configure Case Activities.
4. Publish the process.

---

## Step 6 – Configure Action Center

1. Publish the Action App.
2. Connect it with the Maestro Case.
3. Verify approval tasks.

---

## Step 7 – Configure API Workflow

1. Import the API Workflow.
2. Configure:

   * Webhook endpoint
   * Agent connection
   * Orchestrator connection
3. Publish the workflow.

---

## Step 8 – Configure Integration Service

Create an HTTP Webhook trigger that invokes the API Workflow whenever a new emergency request is received.

---

## Step 9 – Test the Solution

Send an HTTP POST request.

Example:

```bash
curl -X POST http://localhost:8000/emergency \
-H "Content-Type: application/json" \
-d '{
"source":"voice",
"raw_text":"Help me! I fell down and cannot get up.",
"location":"12 Rose Garden Colony, Jaipur",
"elder_id":"ELD001"
}'
```

Expected execution flow:

* Emergency received
* AI analyzes incident
* Maestro creates case
* Human approval task generated
* Operator approves
* Emergency response initiated
* Case completed

---

# 📂 Project Structure

```text
eldercare/
│
├── API Workflows/
├── Maestro/
├── Agent Builder/
├── Action Apps/
├── Action Center/
├── Data Service/
├── Documentation/
└── README.md
```

---

# 🌟 Key Features

* AI-powered emergency classification
* Automated severity assessment
* UiPath Maestro case orchestration
* Human-in-the-loop approvals
* Action Center integration
* API Workflow automation
* Webhook-triggered processing
* Automated notifications
* End-to-end case lifecycle management
* Complete audit trail

---

# 🎯 Business Impact

* Faster emergency response for elderly individuals
* Reduced manual intervention
* Improved coordination between caregivers and responders
* Human oversight for safety-critical decisions
* Scalable case management architecture
* Better visibility into emergency operations

---

# 🛠 Technology Stack

* UiPath Maestro
* UiPath Agent Builder
* UiPath Studio Web
* UiPath API Workflows
* UiPath Action Center
* UiPath Action Apps
* UiPath Integration Service
* UiPath Orchestrator
* HTTP Webhooks
* External LLM

---

# 👥 Team

Built for **UiPath AgentHack 2026** to demonstrate how AI agents and UiPath Maestro can transform emergency response and case management for elder care.

---

# 📜 License

MIT License
