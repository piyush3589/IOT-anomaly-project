"""
LangGraph Agent — three-node pipeline:

  fetch_sensor_data  →  detect_anomaly  →  rag_remediate  →  generate_report

Each node is a pure function that receives AgentState and returns updated state.
LangGraph handles the wiring, retries, and observability hooks.
"""

import os
import json
import uuid
from datetime import datetime
from typing import Literal

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END

from agent.models import (
    AgentState, AnomalyDetection, ActionReport,
    RemediationStep, SeverityLevel,
)
from agent.retriever import retriever
from mcp_server.client import run_mcp_tool

# ── LLM setup ───────────────────────────────────────────────────────────────

llm = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.1,
    api_key=os.getenv("GROQ_API_KEY"),
)


# ── Node 1: Fetch sensor data via MCP ───────────────────────────────────────

def fetch_sensor_data(state: AgentState) -> AgentState:
    """Fetch sensor data — direct simulation bypassing MCP."""
    print(f"[Node 1] Fetching data for sensor: {state.sensor_id}")

    import random
    from datetime import datetime, timedelta

    SENSORS = {
        "temp_001":      {"name": "Boiler Temperature",      "unit": "°C",    "normal_range": [60, 85],   "location": "Plant A - Zone 2"},
        "pressure_001":  {"name": "Pipeline Pressure",       "unit": "bar",   "normal_range": [4.0, 6.5], "location": "Plant A - Zone 1"},
        "flow_001":      {"name": "Coolant Flow Rate",       "unit": "L/min", "normal_range": [45, 75],   "location": "Plant B - Zone 3"},
        "vibration_001": {"name": "Pump Vibration",          "unit": "mm/s",  "normal_range": [0.5, 4.0], "location": "Plant B - Zone 1"},
        "humidity_001":  {"name": "Control Room Humidity",   "unit": "%RH",   "normal_range": [40, 60],   "location": "Control Room"},
    }

    sensor = SENSORS.get(state.sensor_id)
    if not sensor:
        return AgentState(**{**state.model_dump(), "error": f"Unknown sensor: {state.sensor_id}"})

    low, high = sensor["normal_range"]
    value = round(random.uniform(high * 1.1, high * 1.3), 2)

    reading = {
        "sensor_id": state.sensor_id,
        "name": sensor["name"],
        "value": value,
        "unit": sensor["unit"],
        "normal_range": sensor["normal_range"],
        "location": sensor["location"],
        "timestamp": datetime.utcnow().isoformat(),
        "status": "CRITICAL_HIGH",
    }

    now = datetime.utcnow()
    history = []
    for i in range(10):
        ts = now - timedelta(minutes=(10 - i) * 5)
        v = round(random.uniform(low, high * 1.3), 2)
        history.append({**reading, "value": v, "timestamp": ts.isoformat()})

    print(f"[DEBUG] Reading: {reading}")
    print(f"[DEBUG] History count: {len(history)}")

    return AgentState(**{**state.model_dump(), "raw_reading": reading, "history": history})


# ── Node 2: Detect anomaly with LLM ─────────────────────────────────────────

def detect_anomaly(state: AgentState) -> AgentState:
    """LLM analyses the reading + history and produces an AnomalyDetection."""
    print(f"[Node 2] Detecting anomaly for sensor: {state.sensor_id}")

    reading = state.raw_reading
    history_values = [r["value"] for r in (state.history or [])]

    prompt = f"""You are an IoT anomaly detection expert.

CURRENT READING:
{json.dumps(reading, indent=2)}

HISTORICAL VALUES (oldest → newest): {history_values}

Analyse whether this reading is anomalous. Respond ONLY with a JSON object matching this schema exactly:
{{
  "sensor_id": "{state.sensor_id}",
  "is_anomalous": true/false,
  "severity": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "current_value": <number>,
  "unit": "<string>",
  "normal_min": <number>,
  "normal_max": <number>,
  "deviation_pct": <number>,
  "trend": "RISING" | "FALLING" | "STABLE",
  "summary": "<one sentence plain English>"
}}

Rules:
- severity CRITICAL if value exceeds normal by >25% or status is CRITICAL_HIGH/CRITICAL_LOW
- severity HIGH if 15-25% deviation
- severity MEDIUM if 5-15% deviation  
- severity LOW if <5% deviation or within range
- trend based on last 5 historical values direction
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    # strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    print(f"[DEBUG] Raw LLM response: {raw}")
    data = json.loads(raw.strip())

    # Fallback: fill None numeric fields from raw_reading
    if reading:
        normal_range = reading.get("normal_range", [None, None])
        if data.get("current_value") is None:          # ← this line changed
            data["current_value"] = reading.get("value")
        if not data.get("unit"):
            data["unit"] = reading.get("unit", "")
        if data.get("normal_min") is None and isinstance(normal_range, list):
            data["normal_min"] = normal_range[0]
        if data.get("normal_max") is None and isinstance(normal_range, list):
            data["normal_max"] = normal_range[1]
        if data.get("deviation_pct") is None:
            val  = data.get("current_value") or 0
            high = data.get("normal_max") or 0
            low  = data.get("normal_min") or 0
            if high and val > high:
                data["deviation_pct"] = round((val - high) / high * 100, 2)
            elif low and val < low:
                data["deviation_pct"] = round((low - val) / low * 100, 2)
            else:
                data["deviation_pct"] = 0.0

    anomaly = AnomalyDetection(**data)
    return AgentState(**{**state.model_dump(), "anomaly": anomaly}) 


# ── Node 3: RAG over remediation knowledge base ──────────────────────────────

def rag_remediate(state: AgentState) -> AgentState:
    """Semantic search over remediation KB using anomaly context."""
    print(f"[Node 3] RAG retrieval for: {state.anomaly.summary}")

    query = (
        f"{state.anomaly.summary} "
        f"sensor {state.sensor_id} "
        f"value {state.anomaly.current_value} {state.anomaly.unit} "
        f"severity {state.anomaly.severity}"
    )

    context, source_id, confidence = retriever.retrieve(query)

    # Attach source info to context
    enriched = f"[Source: {source_id} | Confidence: {confidence}]\n\n{context}"
    return AgentState(**{**state.model_dump(), "rag_context": enriched})


# ── Node 4: Generate final structured report ─────────────────────────────────

def generate_report(state: AgentState) -> AgentState:
    """LLM synthesises everything into a final ActionReport."""
    print(f"[Node 4] Generating action report")

    reading = state.raw_reading
    anomaly = state.anomaly

    prompt = f"""You are an industrial IoT incident response system.

ANOMALY DETECTED:
{anomaly.model_dump_json(indent=2)}

SENSOR LOCATION: {reading.get('location', 'Unknown')}
SENSOR NAME: {reading.get('name', state.sensor_id)}

REMEDIATION KNOWLEDGE BASE CONTEXT:
{state.rag_context}

Generate a JSON action report matching this schema EXACTLY (no extra fields):
{{
  "report_id": "{str(uuid.uuid4())}",
  "generated_at": "{datetime.utcnow().isoformat()}",
  "sensor_id": "{state.sensor_id}",
  "sensor_name": "<from reading>",
  "location": "<from reading>",
  "anomaly": <copy the anomaly JSON exactly>,
  "root_cause": "<most likely root cause from KB, 1-2 sentences>",
  "remediation_steps": [
    {{"step_number": 1, "action": "...", "responsible_team": "...", "estimated_time": "..."}}
  ],
  "knowledge_source": "<source id from context>",
  "confidence": <0.0–1.0 float from context>,
  "escalate_immediately": <true if severity is CRITICAL>,
  "affected_systems": ["<system1>", "<system2>"],
  "estimated_downtime_hours": <number or null>,
  "agent_reasoning": "<2-3 sentences explaining how you reached this conclusion>"
}}

Include 3–5 remediation steps. Be specific and actionable.
"""

    response = llm.invoke([HumanMessage(content=prompt)])
    raw = response.content.strip()

    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    data = json.loads(raw.strip())

    # re-attach the validated anomaly object
    data["anomaly"] = anomaly.model_dump()

    report = ActionReport(**data)
    return AgentState(**{**state.model_dump(), "report": report})


# ── Conditional edge: skip remediation if no anomaly ─────────────────────────

def should_remediate(state: AgentState) -> Literal["rag_remediate", "skip"]:
    if state.error:
        return "skip"
    if state.anomaly and not state.anomaly.is_anomalous:
        return "skip"
    return "rag_remediate"


# ── Build the graph ──────────────────────────────────────────────────────────

def build_graph():
    graph = StateGraph(AgentState)

    graph.add_node("fetch_sensor_data", fetch_sensor_data)
    graph.add_node("detect_anomaly", detect_anomaly)
    graph.add_node("rag_remediate", rag_remediate)
    graph.add_node("generate_report", generate_report)

    graph.set_entry_point("fetch_sensor_data")
    graph.add_edge("fetch_sensor_data", "detect_anomaly")
    graph.add_conditional_edges(
        "detect_anomaly",
        should_remediate,
        {"rag_remediate": "rag_remediate", "skip": END},
    )
    graph.add_edge("rag_remediate", "generate_report")
    graph.add_edge("generate_report", END)

    return graph.compile()


# Singleton compiled graph
agent = build_graph()


def run_analysis(sensor_id: str) -> dict:
    """Entry point called by FastAPI."""
    initial_state = AgentState(sensor_id=sensor_id)
    final_state = agent.invoke(initial_state)

    if final_state.get("error"):
        return {"error": final_state["error"]}
    if final_state.get("report"):
        return final_state["report"].model_dump()
    if final_state.get("anomaly") and not final_state["anomaly"]["is_anomalous"]:
        return {
            "sensor_id": sensor_id,
            "status": "NORMAL",
            "message": "No anomaly detected.",
            "reading": final_state.get("raw_reading"),
        }
    return {"error": "Agent completed without producing a report."}
