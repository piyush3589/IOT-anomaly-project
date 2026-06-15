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
from typing import Literal, Optional, TypedDict

from dotenv import load_dotenv
load_dotenv()

from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from agent.models import (
    AnomalyDetection, ActionReport,
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


# ── State — TypedDict for LangGraph ─────────────────────────────────────────

class AgentState(TypedDict):
    sensor_id: str
    raw_reading: Optional[dict]
    history: Optional[list]
    anomaly: Optional[AnomalyDetection]
    rag_context: Optional[str]
    report: Optional[ActionReport]
    error: Optional[str]
    retry_count: int
    force_normal: bool


# ── Node 1: Fetch sensor data ────────────────────────────────────────────────

def fetch_sensor_data(state: AgentState) -> AgentState:
    print(f"[Node 1] Fetching data for sensor: {state['sensor_id']}")
    try:
        reading = run_mcp_tool("get_reading", {
            "sensor_id": state["sensor_id"],
            "anomalous": not state.get("force_normal", False)
        })
        history = run_mcp_tool("get_history", {"sensor_id": state["sensor_id"], "n": 10})
        print(f"[DEBUG] Reading: {reading}")
        print(f"[DEBUG] force_normal: {state.get('force_normal')}, anomalous: {not state.get('force_normal', False)}")
        return {**state, "raw_reading": reading, "history": history}
    except Exception as e:
        print(f"[DEBUG] MCP error: {e}")
        return {**state, "error": str(e)}


# ── Node 2: Detect anomaly ───────────────────────────────────────────────────

def detect_anomaly(state: AgentState) -> AgentState:
    print(f"[Node 2] Detecting anomaly for sensor: {state['sensor_id']}")

    reading = state["raw_reading"]
    history_values = [r["value"] for r in (state.get("history") or [])]

    prompt = f"""You are an IoT anomaly detection expert.

CURRENT READING:
{json.dumps(reading, indent=2)}

HISTORICAL VALUES (oldest → newest): {history_values}

Analyse whether this reading is anomalous. Respond ONLY with a JSON object matching this schema exactly:
{{
  "sensor_id": "{state['sensor_id']}",
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

    try:
        response = llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        import re
        try:
            data = json.loads(raw.strip())
        except json.JSONDecodeError:
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                raise ValueError(f"No valid JSON in LLM response: {raw[:200]}")

    except Exception as e:
        print(f"[DEBUG] Error in detect_anomaly: {e}")
        raise

    if reading:
        normal_range = reading.get("normal_range", [None, None])
        if data.get("current_value") is None:
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
    return {**state, "anomaly": anomaly}


# ── Node 3: RAG retrieval ────────────────────────────────────────────────────

def rag_remediate(state: AgentState) -> AgentState:
    retry_count = state.get("retry_count", 0)
    anomaly = state["anomaly"]

    if retry_count > 0:
        print(f"[Node 3] RAG RETRY {retry_count} — refining query")
        query = (
            f"SPECIFIC remediation for {anomaly.severity} severity "
            f"{anomaly.summary} "
            f"deviation {anomaly.deviation_pct}% "
            f"trend {anomaly.trend} "
            f"sensor {state['sensor_id']}"
        )
    else:
        print(f"[Node 3] RAG retrieval for: {anomaly.summary}")
        query = (
            f"{anomaly.summary} "
            f"sensor {state['sensor_id']} "
            f"value {anomaly.current_value} {anomaly.unit} "
            f"severity {anomaly.severity}"
        )

    context, source_id, confidence = retriever.retrieve(query)
    enriched = f"[Source: {source_id} | Confidence: {confidence}]\n\n{context}"
    return {**state, "rag_context": enriched}


# ── Node 4: Generate report ──────────────────────────────────────────────────

def generate_report(state: AgentState) -> AgentState:
    retry_count = state.get("retry_count", 0)
    print(f"[Node 4] Generating action report (attempt {retry_count + 1})")

    reading = state["raw_reading"]
    anomaly = state["anomaly"]

    prompt = f"""You are an industrial IoT incident response system.

ANOMALY DETECTED:
{anomaly.model_dump_json(indent=2)}

SENSOR LOCATION: {reading.get('location', 'Unknown')}
SENSOR NAME: {reading.get('name', state['sensor_id'])}

REMEDIATION KNOWLEDGE BASE CONTEXT:
{state['rag_context']}

Generate a JSON action report matching this schema EXACTLY (no extra fields):
{{
  "report_id": "{str(uuid.uuid4())}",
  "generated_at": "{datetime.utcnow().isoformat()}",
  "sensor_id": "{state['sensor_id']}",
  "sensor_name": "<from reading>",
  "location": "<from reading>",
  "anomaly": <copy the anomaly JSON exactly>,
  "root_cause": "<most likely root cause from KB, 1-2 sentences>",
  "remediation_steps": [
    {{"step_number": 1, "action": "...", "responsible_team": "...", "estimated_time": "..."}}
  ],
  "knowledge_source": "<source id from context>",
  "confidence": <0.0–1.0 float — be honest, low if KB context was weak>,
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
    data["anomaly"] = anomaly.model_dump()

    report = ActionReport(**data)
    return {**state, "report": report, "retry_count": retry_count + 1}


# ── Conditional edge 1: skip if no anomaly ───────────────────────────────────

def should_remediate(state: AgentState) -> Literal["rag_remediate", "skip"]:
    if state.get("error"):
        return "skip"
    anomaly = state.get("anomaly")
    if anomaly and not anomaly.is_anomalous:
        return "skip"
    return "rag_remediate"


# ── Conditional edge 2: retry if low confidence ──────────────────────────────

def should_retry(state: AgentState) -> Literal["rag_remediate", "__end__"]:
    report = state.get("report")
    retry_count = state.get("retry_count", 0)

    if report and report.confidence < 0.5 and retry_count < 2:
        print(f"[Agent] Low confidence ({report.confidence}) — retrying RAG (attempt {retry_count})")
        return "rag_remediate"

    print(f"[Agent] Confidence acceptable ({report.confidence if report else 'N/A'}) — finalizing report")
    return END


# ── Build graph ──────────────────────────────────────────────────────────────

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

    graph.add_conditional_edges(
        "generate_report",
        should_retry,
        {"rag_remediate": "rag_remediate", END: END},
    )

    return graph.compile()


agent = build_graph()


def run_analysis(sensor_id: str, force_normal: bool = False) -> dict:
    initial_state: AgentState = {
        "sensor_id": sensor_id,
        "raw_reading": None,
        "history": None,
        "anomaly": None,
        "rag_context": None,
        "report": None,
        "error": None,
        "retry_count": 0,
        "force_normal": force_normal,
    }
    final_state = agent.invoke(initial_state)

    if final_state.get("error"):
        return {"error": final_state["error"]}
    if final_state.get("report"):
        return final_state["report"].model_dump()
    anomaly = final_state.get("anomaly")
    if anomaly and not anomaly.is_anomalous:
        return {
            "sensor_id": sensor_id,
            "status": "NORMAL",
            "message": "No anomaly detected.",
            "reading": final_state.get("raw_reading"),
        }
    return {"error": "Agent completed without producing a report."}
