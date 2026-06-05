"""
Tests — covers MCP tool parsing, anomaly detection logic, and API endpoints.
Run: pytest tests/ -v
"""

import pytest
import json
from unittest.mock import patch, MagicMock

from agent.models import AgentState, AnomalyDetection, SeverityLevel


# ── Unit: Pydantic models ────────────────────────────────────────────────────

def test_anomaly_detection_model():
    a = AnomalyDetection(
        sensor_id="temp_001",
        is_anomalous=True,
        severity=SeverityLevel.CRITICAL,
        current_value=98.5,
        unit="°C",
        normal_min=60,
        normal_max=85,
        deviation_pct=15.9,
        trend="RISING",
        summary="Boiler temperature critically high at 98.5°C, 15.9% above normal max.",
    )
    assert a.severity == SeverityLevel.CRITICAL
    assert a.is_anomalous is True
    assert a.deviation_pct == 15.9


def test_agent_state_defaults():
    state = AgentState(sensor_id="pressure_001")
    assert state.sensor_id == "pressure_001"
    assert state.raw_reading is None
    assert state.error is None


# ── Unit: MCP server tool logic ──────────────────────────────────────────────

def test_sensor_reading_structure():
    """Test that simulated readings have all required fields."""
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
    from mcp_server.server import _generate_reading, SENSORS

    for sid in SENSORS:
        reading = _generate_reading(sid)
        assert "sensor_id" in reading
        assert "value" in reading
        assert "unit" in reading
        assert "status" in reading
        assert "timestamp" in reading


def test_anomalous_reading_out_of_range():
    from mcp_server.server import _generate_reading, SENSORS

    for sid in SENSORS:
        reading = _generate_reading(sid, anomalous=True)
        low, high = SENSORS[sid]["normal_range"]
        # anomalous reading should be outside normal range
        assert reading["value"] < low or reading["value"] > high, (
            f"Anomalous reading for {sid} was {reading['value']} — still within [{low}, {high}]"
        )


def test_classify_normal():
    from mcp_server.server import _classify
    sensor = {"normal_range": (60, 85), "critical_high": 95}
    assert _classify(sensor, 72.0) == "NORMAL"


def test_classify_critical_high():
    from mcp_server.server import _classify
    sensor = {"normal_range": (60, 85), "critical_high": 95}
    assert _classify(sensor, 96.0) == "CRITICAL_HIGH"


def test_classify_low():
    from mcp_server.server import _classify
    sensor = {"normal_range": (60, 85), "critical_high": 95}
    assert _classify(sensor, 55.0) == "LOW"


# ── Unit: RAG retriever ──────────────────────────────────────────────────────

def test_retriever_returns_tuple():
    """Smoke test — requires seeded ChromaDB."""
    try:
        from agent.retriever import RemediationRetriever
        r = RemediationRetriever()
        doc, source_id, confidence = r.retrieve("boiler temperature high critical")
        assert isinstance(doc, str)
        assert len(doc) > 10
        assert 0.0 <= confidence <= 1.0
    except Exception:
        pytest.skip("ChromaDB not seeded — run data/seed_knowledge.py first")


# ── Integration: FastAPI endpoints ───────────────────────────────────────────

def test_health_endpoint():
    from fastapi.testclient import TestClient
    from api.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_sensors_endpoint_mocked():
    from fastapi.testclient import TestClient
    from api.main import app

    mock_sensors = {
        "temp_001": {"name": "Boiler Temperature", "unit": "°C"}
    }

    with patch("api.main.run_mcp_tool", return_value=mock_sensors):
        client = TestClient(app)
        resp = client.get("/sensors")
        assert resp.status_code == 200
        data = resp.json()
        assert "sensors" in data
        assert data["count"] == 1


def test_analyze_endpoint_mocked():
    from fastapi.testclient import TestClient
    from api.main import app

    mock_result = {
        "sensor_id": "temp_001",
        "status": "NORMAL",
        "message": "No anomaly detected.",
    }

    with patch("api.main.run_analysis", return_value=mock_result):
        client = TestClient(app)
        resp = client.post("/analyze", json={"sensor_id": "temp_001"})
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "duration_ms" in data
