"""
MCP Server — exposes IoT sensor data as tools the LLM agent can call.

Run standalone:
    python mcp_server/server.py

The agent calls these tools via MCP protocol:
  - list_sensors()         → all available sensor IDs + metadata
  - get_reading(sensor_id) → latest reading for one sensor
  - get_history(sensor_id, n) → last N readings
"""

import random
import json
from datetime import datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Simulated sensor registry ──────────────────────────────────────────────

SENSORS: dict[str, dict] = {
    "temp_001": {
        "name": "Boiler Temperature",
        "unit": "°C",
        "normal_range": (60, 85),
        "critical_high": 95,
        "location": "Plant A - Zone 2",
    },
    "pressure_001": {
        "name": "Pipeline Pressure",
        "unit": "bar",
        "normal_range": (4.0, 6.5),
        "critical_high": 8.0,
        "location": "Plant A - Zone 1",
    },
    "flow_001": {
        "name": "Coolant Flow Rate",
        "unit": "L/min",
        "normal_range": (45, 75),
        "critical_low": 20,
        "location": "Plant B - Zone 3",
    },
    "vibration_001": {
        "name": "Pump Vibration",
        "unit": "mm/s",
        "normal_range": (0.5, 4.0),
        "critical_high": 7.5,
        "location": "Plant B - Zone 1",
    },
    "humidity_001": {
        "name": "Control Room Humidity",
        "unit": "%RH",
        "normal_range": (40, 60),
        "critical_high": 80,
        "location": "Control Room",
    },
}


def _generate_reading(sensor_id: str, anomalous: bool = False) -> dict:
    """Generate a realistic sensor reading, optionally anomalous."""
    sensor = SENSORS[sensor_id]
    low, high = sensor["normal_range"]

    if anomalous:
        # push value outside normal range
        if "critical_high" in sensor:
            value = round(random.uniform(high * 1.1, sensor["critical_high"] * 1.05), 2)
        else:
            value = round(random.uniform(sensor.get("critical_low", 0), low * 0.8), 2)
    else:
        value = round(random.uniform(low, high), 2)

    return {
        "sensor_id": sensor_id,
        "name": sensor["name"],
        "value": value,
        "unit": sensor["unit"],
        "normal_range": sensor["normal_range"],
        "location": sensor["location"],
        "timestamp": datetime.utcnow().isoformat(),
        "status": _classify(sensor, value),
    }


def _classify(sensor: dict, value: float) -> str:
    low, high = sensor["normal_range"]
    if value < low:
        crit = sensor.get("critical_low", low * 0.7)
        return "CRITICAL_LOW" if value <= crit else "LOW"
    if value > high:
        crit = sensor.get("critical_high", high * 1.2)
        return "CRITICAL_HIGH" if value >= crit else "HIGH"
    return "NORMAL"


def _generate_history(sensor_id: str, n: int = 10) -> list[dict]:
    """Return last N readings with realistic time deltas."""
    readings = []
    now = datetime.utcnow()
    # last reading is anomalous to trigger agent analysis
    for i in range(n):
        ts = now - timedelta(minutes=(n - i) * 5)
        anomalous = i == n - 1  # only latest is anomalous
        reading = _generate_reading(sensor_id, anomalous=anomalous)
        reading["timestamp"] = ts.isoformat()
        readings.append(reading)
    return readings


# ── MCP Server setup ────────────────────────────────────────────────────────

app = Server("iot-sensor-server")


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="list_sensors",
            description="List all available IoT sensors with metadata (ID, name, unit, location, normal range).",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="get_reading",
            description="Get the latest real-time reading for a specific sensor.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sensor_id": {
                        "type": "string",
                        "description": "Sensor ID, e.g. 'temp_001'",
                    }
                },
                "required": ["sensor_id"],
            },
        ),
        types.Tool(
            name="get_history",
            description="Get the last N readings for a sensor to analyse trends.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sensor_id": {"type": "string"},
                    "n": {
                        "type": "integer",
                        "description": "Number of historical readings (default 10, max 50)",
                        "default": 10,
                    },
                },
                "required": ["sensor_id"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    if name == "list_sensors":
        result = {
            sid: {
                "name": s["name"],
                "unit": s["unit"],
                "location": s["location"],
                "normal_range": s["normal_range"],
            }
            for sid, s in SENSORS.items()
        }
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    if name == "get_reading":
        sid = arguments["sensor_id"]
        if sid not in SENSORS:
            return [types.TextContent(type="text", text=f"ERROR: Unknown sensor '{sid}'")]
        reading = _generate_reading(sid, anomalous=True)  # always anomalous for demo
        return [types.TextContent(type="text", text=json.dumps(reading, indent=2))]

    if name == "get_history":
        sid = arguments["sensor_id"]
        n = min(int(arguments.get("n", 10)), 50)
        if sid not in SENSORS:
            return [types.TextContent(type="text", text=f"ERROR: Unknown sensor '{sid}'")]
        history = _generate_history(sid, n)
        return [types.TextContent(type="text", text=json.dumps(history, indent=2))]

    return [types.TextContent(type="text", text=f"ERROR: Unknown tool '{name}'")]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
