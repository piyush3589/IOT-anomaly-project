"""
FastAPI — REST layer over the LangGraph agent.

Endpoints:
  GET  /sensors          → list all available sensors (via MCP)
  POST /analyze          → run full agent pipeline for a sensor
  GET  /health           → health check
"""

import asyncio
import sys

if sys.platform == "windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

import os
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import time


from agent.graph import run_analysis

app = FastAPI(
    title="IoT Anomaly Copilot",
    description="AI agent that detects IoT sensor anomalies via MCP and returns structured remediation reports.",
    version="1.0.0",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Request / response models ────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    sensor_id: str
    include_history: bool = False


class AnalyzeResponse(BaseModel):
    duration_ms: int
    result: dict


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "IoT Anomaly Copilot"}


#@app.get("/sensors")
def list_sensors():
    """List all available IoT sensors fetched via MCP."""
    try:
        sensors = run_mcp_tool("list_sensors")
        return {"sensors": sensors, "count": len(sensors)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MCP server unavailable: {e}")


#@app.get("/sensors/{sensor_id}/reading")
def get_sensor_reading(sensor_id: str):
    """Get latest reading for a sensor via MCP."""
    try:
        reading = run_mcp_tool("get_reading", {"sensor_id": sensor_id})
        return reading
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


#@app.get("/sensors/{sensor_id}/history")
def get_sensor_history(sensor_id: str, n: int = 10):
    """Get historical readings for a sensor via MCP."""
    try:
        history = run_mcp_tool("get_history", {"sensor_id": sensor_id, "n": n})
        return {"sensor_id": sensor_id, "readings": history, "count": len(history)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze_sensor(req: AnalyzeRequest):
    """
    Run the full agent pipeline for a sensor:
    MCP fetch → anomaly detection → RAG remediation → structured report
    """
    start = time.time()

    try:
        result = run_analysis(req.sensor_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    duration_ms = int((time.time() - start) * 1000)
    return AnalyzeResponse(duration_ms=duration_ms, result=result)


@app.post("/analyze/batch")
def analyze_batch(sensor_ids: list[str]):
    """Run analysis on multiple sensors sequentially."""
    results = {}
    for sid in sensor_ids:
        try:
            results[sid] = run_analysis(sid)
        except Exception as e:
            results[sid] = {"error": str(e)}
    return results


# ── Dev runner ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
