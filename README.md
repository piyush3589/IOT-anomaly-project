# IoT Anomaly Copilot
[![Live Demo](https://img.shields.io/badge/Live-Demo-green)](https://iot-project-6ogr.onrender.com/docs)


An AI agent that monitors IoT sensors, detects anomalies using an LLM, retrieves remediation playbooks via RAG, and returns structured incident reports — all through a single API call.

Built to demonstrate: MCP · LangGraph · Agentic Loops · RAG · ChromaDB · FastAPI · Pydantic · Groq


What it does

You send a sensor ID. The agent does the rest:


Fetches live sensor data via Model Context Protocol (MCP) tools
Detects anomaly — Groq LLaMA 3.3 analyses reading + 10-point history, classifies severity (LOW / MEDIUM / HIGH / CRITICAL)
Retrieves remediation playbook — semantic search over ChromaDB knowledge base
Evaluates its own confidence — if confidence < 0.5, the agent reformulates the query and retries RAG (up to 2 attempts)
Returns structured report — root cause, step-by-step fix, responsible teams, escalation flag


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


Agentic Behavior — Confidence Evaluation Loop

Most RAG pipelines retrieve once and answer regardless of quality. This agent evaluates its own output before finalizing.

After generating a report, the agent checks its confidence score:


Confidence ≥ 0.5 → report is finalized and returned
Confidence < 0.5 → agent decides to retry, reformulates the retrieval query using anomaly severity, deviation percentage, and trend — then retrieves again
Max 2 retries — prevents infinite loops while allowing meaningful self-correction


The retry decision is made at runtime based on observed output quality — not hardcoded by the developer. This is what distinguishes an agentic system from a linear pipeline.

In logs:

[Node 3] RAG retrieval for: Boiler temperature critically high
[Node 4] Generating action report (attempt 1)
[Agent] Low confidence (0.38) — retrying RAG (attempt 1)
[Node 3] RAG RETRY 1 — refining query
[Node 4] Generating action report (attempt 2)
[Agent] Confidence acceptable (0.71) — finalizing report


Sample output

json{
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


Stack

ComponentLibraryAgent orchestrationLangGraph 0.2LLMGroq — LLaMA 3.3-70b-versatileMCP servermcp official Python SDKVector storeChromaDB + sentence-transformersAPIFastAPI + UvicornStructured outputsPydantic v2ObservabilityLangSmith (optional)


Sensors monitored

Sensor IDNameUnitNormal Rangetemp_001Boiler Temperature°C60–85pressure_001Pipeline Pressurebar4.0–6.5flow_001Coolant Flow RateL/min45–75vibration_001Pump Vibrationmm/s0.5–4.0humidity_001Control Room Humidity%RH40–60


API: https://iot-project-6ogr.onrender.com

Swagger UI: https://iot-project-6ogr.onrender.com/docs

Quickstart

bash# 1. Clone and create virtual environment
git clone https://github.com/yourusername/iot-anomaly-copilot
cd iot-anomaly-copilot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Add your GROQ_API_KEY (free at console.groq.com)

# 4. Seed the knowledge base (run once)
python data/seed_knowledge.py

# 5. Start the API
uvicorn api.main:app --reload

# 6. Open Swagger UI
# http://localhost:8000/docs

Test via curl

bash# Run full agent analysis
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"sensor_id": "temp_001"}'

# Try all sensors
for sensor in temp_001 pressure_001 flow_001 vibration_001 humidity_001; do
  echo "Testing $sensor..."
  curl -s -X POST http://localhost:8000/analyze \
    -H "Content-Type: application/json" \
    -d "{\"sensor_id\": \"$sensor\"}" | python -m json.tool
done


Project structure

iot-anomaly-copilot/
├── mcp_server/
│   ├── server.py        # MCP server — exposes sensor tools
│   └── client.py        # MCP client wrapper
├── agent/
│   ├── graph.py         # LangGraph agent with confidence evaluation loop
│   ├── models.py        # Pydantic models (AgentState, ActionReport)
│   └── retriever.py     # ChromaDB RAG retriever
├── api/
│   └── main.py          # FastAPI endpoints
├── data/
│   └── seed_knowledge.py # Seeds 5 remediation playbooks into ChromaDB
├── tests/
│   └── test_all.py      # Unit + integration tests
├── Dockerfile
├── docker-compose.yml
└── .github/workflows/ci.yml


API endpoints

MethodEndpointDescriptionGET/healthHealth checkGET/sensorsList all sensorsGET/sensors/{id}/readingLatest readingGET/sensors/{id}/historyLast N readingsPOST/analyzeRun full agent pipelinePOST/analyze/batchAnalyze multiple sensors


Docker

bashdocker-compose up --build


Key concepts demonstrated


Agentic confidence loop — agent evaluates its own report quality and retries RAG with a refined query if confidence < 0.5, up to 2 times. The retry decision is made at runtime, not hardcoded.
Model Context Protocol (MCP) — LLM agent calls sensor tools via MCP rather than hardcoded function calls
LangGraph stateful graph — conditional edges, runtime branching, and cycle support
RAG pipeline — ChromaDB semantic search over domain-specific remediation knowledge
Pydantic v2 structured outputs — every LLM response is validated and typed
FastAPI — production-ready REST API with auto-generated Swagger docs
