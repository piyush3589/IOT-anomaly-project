"""
Seed script — populates ChromaDB with IoT remediation knowledge.
Run once: python data/seed_knowledge.py

Each document is a remediation playbook for a specific anomaly type.
The RAG node retrieves the most relevant one given the sensor reading.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import chromadb
from chromadb.utils import embedding_functions

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")

REMEDIATION_DOCS = [
    {
        "id": "kb_temp_high_001",
        "content": """
ANOMALY: Boiler Temperature HIGH / CRITICAL_HIGH
SENSOR TYPE: Temperature (°C)
NORMAL RANGE: 60–85°C | CRITICAL THRESHOLD: >95°C

ROOT CAUSE (most likely):
1. Coolant flow rate drop — check flow_001 simultaneously
2. Blocked heat exchanger fins — inspect Plant A Zone 2
3. Control valve failure — valve CV-201 may be stuck closed
4. Ambient temperature spike in Zone 2

REMEDIATION STEPS:
1. [Immediate] Reduce boiler load by 20% — control room operator — 5 min
2. [Immediate] Check coolant flow sensor flow_001 for correlated drop
3. [30 min] Inspect CV-201 control valve manually — maintenance team
4. [1 hr] Flush heat exchanger if flow confirmed low — mechanical team
5. [Post-incident] Review thermal logs for last 24h — engineering team

AFFECTED SYSTEMS: Boiler unit B-01, downstream process line PL-3
ESCALATE IF: Temperature exceeds 98°C for more than 5 minutes
ESTIMATED DOWNTIME: 2–4 hours for heat exchanger flush
""",
        "metadata": {"sensor_type": "temperature", "anomaly_type": "HIGH", "location": "Plant A"},
    },
    {
        "id": "kb_pressure_high_001",
        "content": """
ANOMALY: Pipeline Pressure HIGH / CRITICAL_HIGH
SENSOR TYPE: Pressure (bar)
NORMAL RANGE: 4.0–6.5 bar | CRITICAL THRESHOLD: >8.0 bar

ROOT CAUSE (most likely):
1. Downstream blockage — debris accumulation in pipe section P-104
2. Pressure relief valve PRV-301 failed closed
3. Pump speed controller malfunction — VFD-01 running at 100%
4. Sudden demand reduction with pump still at full load

REMEDIATION STEPS:
1. [Immediate] Open manual bypass valve BV-112 — 2 min — operator on duty
2. [Immediate] Verify PRV-301 is operational — safety team
3. [15 min] Reduce VFD-01 frequency to 40 Hz — control room
4. [1 hr] Inspect pipe section P-104 for blockage — mechanical team
5. [Post-incident] Calibrate pressure transmitter PT-301 — instrumentation team

AFFECTED SYSTEMS: Pipeline P-104, downstream tanks T-01 and T-02
ESCALATE IF: Pressure exceeds 9.0 bar — risk of pipe rupture
ESTIMATED DOWNTIME: 1–2 hours
""",
        "metadata": {"sensor_type": "pressure", "anomaly_type": "HIGH", "location": "Plant A"},
    },
    {
        "id": "kb_flow_low_001",
        "content": """
ANOMALY: Coolant Flow Rate LOW / CRITICAL_LOW
SENSOR TYPE: Flow rate (L/min)
NORMAL RANGE: 45–75 L/min | CRITICAL THRESHOLD: <20 L/min

ROOT CAUSE (most likely):
1. Pump cavitation — check inlet pressure at suction side
2. Filter FT-201 clogged — last replaced 6 months ago
3. Leakage in coolant circuit — check for puddles in Zone 3
4. Pump seal failure — listen for unusual noise at Pump P-03

REMEDIATION STEPS:
1. [Immediate] Switch to standby pump P-03B — operator — 3 min
2. [Immediate] Inspect filter FT-201 — maintenance team — 15 min
3. [30 min] Check all isolation valves in coolant circuit are fully open
4. [1 hr] Inspect pump P-03 mechanical seal — mechanical team
5. [2 hr] Pressure test coolant loop for leaks — mechanical team

AFFECTED SYSTEMS: Boiler cooling loop, heat exchanger HX-01
ESCALATE IF: Flow drops below 15 L/min — thermal runaway risk
ESTIMATED DOWNTIME: 1–3 hours
""",
        "metadata": {"sensor_type": "flow", "anomaly_type": "LOW", "location": "Plant B"},
    },
    {
        "id": "kb_vibration_high_001",
        "content": """
ANOMALY: Pump Vibration HIGH / CRITICAL_HIGH
SENSOR TYPE: Vibration (mm/s RMS)
NORMAL RANGE: 0.5–4.0 mm/s | CRITICAL THRESHOLD: >7.5 mm/s

ROOT CAUSE (most likely):
1. Bearing wear — bearing life typically 18–24 months, check install date
2. Impeller imbalance — foreign object ingestion possible
3. Misalignment between pump and motor shaft — check coupling
4. Cavitation — correlate with flow_001 for simultaneous low flow

REMEDIATION STEPS:
1. [Immediate] Reduce pump speed by 15% via VFD — control room — 2 min
2. [Immediate] Correlate with flow sensor — if both abnormal, stop pump
3. [30 min] Vibration spectrum analysis — condition monitoring team
4. [4 hr] Bearing inspection and lubrication — mechanical team
5. [8 hr] Shaft alignment check with laser tool — mechanical team

AFFECTED SYSTEMS: Pump P-01, motor M-01, connected pipework
ESCALATE IF: Vibration exceeds 10 mm/s — bearing failure imminent
ESTIMATED DOWNTIME: 4–8 hours for bearing replacement
""",
        "metadata": {"sensor_type": "vibration", "anomaly_type": "HIGH", "location": "Plant B"},
    },
    {
        "id": "kb_humidity_high_001",
        "content": """
ANOMALY: Control Room Humidity HIGH / CRITICAL_HIGH
SENSOR TYPE: Relative Humidity (%RH)
NORMAL RANGE: 40–60 %RH | CRITICAL THRESHOLD: >80 %RH

ROOT CAUSE (most likely):
1. HVAC dehumidifier unit failure — DH-CR-01
2. Water ingress — inspect roof and window seals after recent rain
3. Coolant pipe condensation — check insulation on chilled water lines
4. Increased human occupancy without HVAC adjustment

REMEDIATION STEPS:
1. [Immediate] Deploy portable dehumidifier to control room — facilities — 10 min
2. [Immediate] Check HVAC unit DH-CR-01 status on BMS — facilities team
3. [1 hr] Inspect for water ingress at all entry points — facilities team
4. [2 hr] Service HVAC dehumidifier — HVAC contractor
5. [Post-incident] Install secondary humidity sensor for redundancy

AFFECTED SYSTEMS: Control room electronics, HMI panels, PLC cabinets
ESCALATE IF: Humidity exceeds 85%RH — risk of condensation on electronics
ESTIMATED DOWNTIME: N/A (control room must remain operational)
""",
        "metadata": {"sensor_type": "humidity", "anomaly_type": "HIGH", "location": "Control Room"},
    },
]


def seed():
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="paraphrase-MiniLM-L3-v2"
    )

    collection = client.get_or_create_collection(
        name="iot_remediation_kb",
        embedding_function=ef,
        metadata={"description": "IoT anomaly remediation playbooks"},
    )

    # clear + re-seed
    existing = collection.get()
    if existing["ids"]:
        collection.delete(ids=existing["ids"])

    collection.add(
        ids=[d["id"] for d in REMEDIATION_DOCS],
        documents=[d["content"] for d in REMEDIATION_DOCS],
        metadatas=[d["metadata"] for d in REMEDIATION_DOCS],
    )

    print(f"Seeded {len(REMEDIATION_DOCS)} remediation documents into ChromaDB at {CHROMA_PATH}")
    for doc in REMEDIATION_DOCS:
        print(f"  ✓ {doc['id']}")


if __name__ == "__main__":
    seed()
