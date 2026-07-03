import asyncio
import sys
if sys.platform == "windows":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
import os
from dotenv import load_dotenv
load_dotenv()
from fastapi import FastAPI, HTTPException, BackgroundTasks, Security, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

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
from mcp_server.client import run_mcp_tool





from agent.graph import run_analysis

app = FastAPI(
    title="IoT Anomaly Copilot",
    description="AI agent that detects IoT sensor anomalies via MCP and returns structured remediation reports.",
    version="1.0.0",
    docs_url="/docs",
)


# -- OWASP: Rate limiting setup ----------------------------------------------
# Mitigates API4:2023 Unrestricted Resource Consumption - prevents anyone
# from hammering the expensive, LLM-calling endpoints.
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# -- OWASP: API key authentication setup -------------------------------------
# Mitigates API2:2023 Broken Authentication - requires a valid key on
# sensitive endpoints instead of leaving them fully open.
API_KEY = os.getenv("API_KEY", "dev-key-change-in-production")
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(key: str = Security(api_key_header)):
    if key != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Pass it via the X-API-Key header.",
        )
    return key


# -- OWASP: Tightened CORS ----------------------------------------------------
# The original allow_origins=["*"] / allow_methods=["*"] / allow_headers=["*"]
# is a Security Misconfiguration - it lets ANY website make requests to this
# API on behalf of a visiting user. Restrict to known origins/methods/headers.
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,       # was "*" - now an explicit list
    allow_methods=["GET", "POST"],       # was "*" - this API only needs these
    allow_headers=["Content-Type", "X-API-Key"],  # was "*" - explicit allowlist
)


# -- Request / response models ------------------------------------------------

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
    force_normal: bool = False





class AnalyzeResponse(BaseModel):
    duration_ms: int
    result: dict


# -- Endpoints -----------------------------------------------------------------


# /health stays OPEN - no auth, no rate limit. Monitoring tools and load
# balancers need to be able to ping this freely.
@app.get("/health")
def health():
    return {"status": "ok", "service": "IoT Anomaly Copilot"}


@app.get("/sensors")
def list_sensors():
    """List all available IoT sensors fetched via MCP."""
    try:
        sensors = run_mcp_tool("list_sensors")
        return {"sensors": sensors, "count": len(sensors)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"MCP server unavailable: {e}")


@app.get("/sensors/{sensor_id}/reading")
def get_sensor_reading(sensor_id: str):
    """Get latest reading for a sensor via MCP."""
    try:
        reading = run_mcp_tool("get_reading", {"sensor_id": sensor_id})
        return reading
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@app.get("/sensors/{sensor_id}/history")
def get_sensor_history(sensor_id: str, n: int = 10):
    """Get historical readings for a sensor via MCP."""
    try:
        history = run_mcp_tool("get_history", {"sensor_id": sensor_id, "n": n})
        return {"sensor_id": sensor_id, "readings": history, "count": len(history)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


# /analyze is the expensive endpoint (calls MCP + LLM + RAG) - protected with
# both auth AND rate limiting (OWASP API2 + API4).
@app.post("/analyze", response_model=AnalyzeResponse)
@limiter.limit("10/minute")
def analyze_sensor(
    req: AnalyzeRequest,
    request: Request,                            # required by slowapi
    api_key: str = Security(verify_api_key),      # OWASP: require auth
):
    """
    Run the full agent pipeline for a sensor:
    MCP fetch -> anomaly detection -> RAG remediation -> structured report
    """
    start = time.time()
    try:
        result = run_analysis(req.sensor_id, force_normal=req.force_normal)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    duration_ms = int((time.time() - start) * 1000)
    return AnalyzeResponse(duration_ms=duration_ms, result=result)


# /analyze/batch is the MOST expensive endpoint (multiple LLM calls in one
# request) - gets a tighter rate limit than the single-sensor endpoint.
@app.post("/analyze/batch")
@limiter.limit("5/minute")
def analyze_batch(
    sensor_ids: list[str],
    request: Request,                             # required by slowapi
    api_key: str = Security(verify_api_key),       # OWASP: require auth
):
    """Run analysis on multiple sensors sequentially."""
    results = {}
    for sid in sensor_ids:
        try:
            results[sid] = run_analysis(sid)
        except Exception as e:
            results[sid] = {"error": str(e)}
    return results


# -- Dev runner -----------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=True)
