# IoT Anomaly Copilot

An AI agent that monitors IoT sensors, detects anomalies using an LLM, retrieves remediation playbooks via RAG, and returns structured incident reports — all through a single API call.

**Live Demo:** https://pi3900-iot.hf.space/docs  
**API:** https://iot-project-6ogr.onrender.com  
**Stack:** LangGraph · MCP · ChromaDB · Groq LLaMA 3.3-70b · FastAPI · Pydantic v2 · Docker

---

## What It Does

Send a sensor ID. The agent does the rest:

1. **Fetches live sensor data** via Model Context Protocol (MCP) tools
2. **Detects anomaly** — Groq LLaMA 3.3-70b analyses the reading + 10-point history, classifies severity (LOW / MEDIUM / HIGH / CRITICAL)
3. **Retrieves remediation playbook** — semantic search over ChromaDB knowledge base
4. **Evaluates its own confidence** — if confidence < 0.5, the agent reformulates the query and retries RAG (up to 2 attempts)
5. **Returns structured report** — root cause, step-by-step fix, responsible teams, escalation flag

---

## Agent Architecture

```
POST /analyze  {"sensor_id": "temp_001"}
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                    LangGraph Agent                      │
│                                                         │
│  fetch_sensor_data    (MCP tool calls)                  │
│         ↓                                               │
│  detect_anomaly       (Groq LLaMA 3.3-70b)              │
│         ↓                                               │
│         ├── no anomaly → END                            │
│         ↓                                               │
│  rag_remediate        (ChromaDB semantic search)        │
│         ↓                                               │
│  generate_report      (Pydantic structured output)      │
│         ↓                                               │
│         ├── confidence ≥ 0.5 → END                      │
│         └── confidence < 0.5 → rag_remediate (retry)   │
│                    ↑___________________________|        │
│              (max 2 retries, refined query)             │
└─────────────────────────────────────────────────────────┘
```

---

## Agentic Behavior — Confidence Evaluation Loop

Most RAG pipelines retrieve once and answer regardless of quality. This agent evaluates its own output before finalizing.

After generating a report, the agent checks its confidence score:

- **Confidence ≥ 0.5** → report is finalized and returned
- **Confidence < 0.5** → agent decides to retry, reformulates the retrieval query using anomaly severity, deviation percentage, and trend — then retrieves again
- **Max 2 retries** — prevents infinite loops while allowing meaningful self-correction

The retry decision is made at runtime based on observed output quality — not hardcoded by the developer. This is what distinguishes an agentic system from a linear pipeline.

**Sample log output:**
```
[Node 3] RAG retrieval for: Boiler temperature critically high
[Node 4] Generating action report (attempt 1)
[Agent] Low confidence (0.38) — retrying RAG (attempt 1)
[Node 3] RAG RETRY 1 — refining query
[Node 4] Generating action report (attempt 2)
[Agent] Confidence acceptable (0.71) — finalizing report
```

---

## Security — OWASP API Security Top 10

Three OWASP controls are implemented and verified across all endpoints:

| Control | Implementation | OWASP Reference |
|---|---|---|
| API Key Authentication | `X-API-Key` header required on `/analyze` and `/analyze/batch` | API2:2023 Broken Authentication |
| Rate Limiting | 10 req/min on `/analyze`, 5 req/min on `/analyze/batch` via slowapi | API4:2023 Unrestricted Resource Consumption |
| CORS Lockdown | Restricted origins, methods (GET/POST only), explicit header allowlist | API8:2023 Security Misconfiguration |

Unauthenticated requests to protected endpoints return `401 Unauthorized`. Requests exceeding rate limits return `429 Too Many Requests`.

---

## Sample Output

```json
{
  "duration_ms": 47381,
  "result": {
    "report_id": "fe05a29f-a4f0-4bff-bb89-b7ff417e8341",
    "sensor_id": "temp_001",
    "sensor_name": "Boiler Temperature",
    "location": "Plant A - Zone 2",
    "anomaly": {
      "is_anomalous": true,
      "severity": "CRITICAL",
      "current_value": 94.59,
      "unit": "°C",
      "normal_min": 60,
      "normal_max": 85,
      "deviation_pct": 11.41,
      "trend": "STABLE",
      "summary": "Boiler temperature critically high, exceeding normal range by 11.41%."
    },
    "root_cause": "Coolant flow rate drop — likely blocked heat exchanger or control valve CV-201 failure.",
    "remediation_steps": [
      {"step_number": 1, "action": "Reduce boiler load by 20%", "responsible_team": "control room operator", "estimated_time": "5 min"},
      {"step_number": 2, "action": "Check coolant flow sensor flow_001 for correlated drop", "responsible_team": "maintenance team", "estimated_time": "10 min"},
      {"step_number": 3, "action": "Inspect CV-201 control valve manually", "responsible_team": "maintenance team", "estimated_time": "30 min"},
      {"step_number": 4, "action": "Flush heat exchanger if flow confirmed low", "responsible_team": "mechanical team", "estimated_time": "1 hr"},
      {"step_number": 5, "action": "Review thermal logs for last 24h", "responsible_team": "engineering team", "estimated_time": "2 hr"}
    ],
    "knowledge_source": "kb_temp_high_001",
    "confidence": 0.74,
    "escalate_immediately": true,
    "affected_systems": ["Boiler unit B-01", "downstream process line PL-3"],
    "estimated_downtime_hours": 2,
    "agent_reasoning": "Boiler at 94.59°C is 11.41% above normal max of 85°C. RAG retrieved coolant flow playbook with 74% confidence. Recommended immediate load reduction and valve inspection."
  }
}
```

---

## Stack

| Component | Library |
|---|---|
| Agent orchestration | LangGraph 0.2 |
| LLM | Groq — LLaMA 3.3-70b-versatile |
| MCP server | mcp official Python SDK |
| Vector store | ChromaDB + sentence-transformers |
| API | FastAPI + Uvicorn |
| Structured outputs | Pydantic v2 |
| Rate limiting | slowapi |
| Observability | LangSmith (optional) |

---

## Sensors Monitored

| Sensor ID | Name | Unit | Normal Range |
|---|---|---|---|
| temp_001 | Boiler Temperature | °C | 60–85 |
| pressure_001 | Pipeline Pressure | bar | 4.0–6.5 |
| flow_001 | Coolant Flow Rate | L/min | 45–75 |
| vibration_001 | Pump Vibration | mm/s | 0.5–4.0 |
| humidity_001 | Control Room Humidity | %RH | 40–60 |

---

## API Endpoints

| Method | Endpoint | Auth Required | Description |
|---|---|---|---|
| GET | /health | No | Health check |
| GET | /sensors | No | List all sensors |
| GET | /sensors/{id}/reading | No | Latest reading |
| GET | /sensors/{id}/history | No | Last N readings |
| POST | /analyze | Yes | Run full agent pipeline |
| POST | /analyze/batch | Yes | Analyze multiple sensors |

---

## Quickstart

```bash
# 1. Clone
git clone https://github.com/piyush3589/IOT-anomaly-project
cd IOT-anomaly-project

# 2. Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Add your GROQ_API_KEY (free at console.groq.com)
# Set API_KEY to a strong secret for endpoint authentication

# 5. Seed the knowledge base (run once)
python data/seed_knowledge.py

# 6. Start the API
uvicorn api.main:app --reload

# 7. Open Swagger UI
# http://localhost:8000/docs
```

---



---

## Project Structure

```
iot-anomaly-copilot/
├── mcp_server/
│   ├── server.py          # MCP server — exposes sensor tools
│   └── client.py          # MCP client wrapper
├── agent/
│   ├── graph.py           # LangGraph agent with confidence evaluation loop
│   ├── models.py          # Pydantic models (AgentState, ActionReport)
│   └── retriever.py       # ChromaDB RAG retriever
├── api/
│   └── main.py            # FastAPI endpoints with OWASP security controls
├── data/
│   └── seed_knowledge.py  # Seeds 5 remediation playbooks into ChromaDB
├── tests/
│   └── test_all.py        # Unit + integration tests
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml
```

---

## Key Concepts Demonstrated

- **Agentic confidence loop** — agent evaluates its own report quality and retries RAG with a refined query if confidence < 0.5, up to 2 times. The retry decision is made at runtime, not hardcoded.
- **Model Context Protocol (MCP)** — LLM agent calls sensor tools via MCP rather than hardcoded function calls
- **LangGraph stateful graph** — conditional edges, runtime branching, and cycle support
- **RAG pipeline** — ChromaDB semantic search over domain-specific remediation knowledge
- **OWASP API Security** — authentication, rate limiting, and CORS controls verified in production
- **Pydantic v2 structured outputs** — every LLM response is validated and typed
- **FastAPI** — production-ready REST API with auto-generated Swagger docs
