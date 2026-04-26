# FreightOS — Automated Freight Bill Processing System

A production-grade freight bill processing system that automatically validates carrier invoices against contracts and delivery records, makes confidence-scored approval decisions, and pauses for human review when confidence is low.

Built with **FastAPI**, **PostgreSQL**, **NetworkX**, **LangGraph**, and **Gemini AI**.

---

## Demo

![Dashboard](https://img.shields.io/badge/UI-FreightOS%20Dashboard-1D9E75?style=flat-square)
![API](https://img.shields.io/badge/API-FastAPI-009688?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker)
![LangGraph](https://img.shields.io/badge/Agent-LangGraph-FF6B35?style=flat-square)

---

## What It Does

Logistics companies receive hundreds of freight bills (carrier invoices) every month. Manually checking each one against contracts is slow and error-prone. FreightOS automates the entire verification pipeline:

1. **Ingests** a freight bill via API
2. **Traverses** a relationship graph to find matching contracts, shipments, and bills of lading
3. **Validates** all charges deterministically — rate, weight, fuel surcharge, duplicates
4. **Scores** confidence and auto-approves or auto-disputes high-confidence decisions
5. **Pauses** for human review when confidence is low
6. **Resumes** after a reviewer submits their decision

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                   FastAPI (port 8000)                │
│  POST /freight-bills  GET /freight-bills/{id}        │
│  GET  /review-queue   POST /review/{id}              │
└───────────────────┬─────────────────────────────────┘
                    │
        ┌───────────▼───────────┐
        │    LangGraph Agent    │
        │                       │
        │  check_duplicate      │
        │  resolve_carrier      │
        │  traverse_graph       │
        │  validate_charges     │
        │  score_and_decide     │
        │  generate_explanation │
        │  finalize             │
        └──┬──────────┬─────────┘
           │          │
    ┌──────▼──┐  ┌────▼──────┐
    │NetworkX │  │PostgreSQL │
    │  Graph  │  │    DB     │
    └──────────┘  └───────────┘
           │
    ┌──────▼──────────────────┐
    │  Gemini AI (LLM)        │
    │  - Carrier name fuzzy   │
    │    matching             │
    │  - Audit explanations   │
    └─────────────────────────┘
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI | Async, fast, auto Swagger docs |
| Database | PostgreSQL | Relational data, ACID, audit trail |
| Graph | NetworkX (in-memory) | Zero-infra graph traversal for contract → shipment → BOL relationships |
| Agent | LangGraph | Stateful pipeline with human-in-the-loop pause/resume |
| LLM | Google Gemini 1.5 Flash | Fuzzy carrier name matching + human-readable explanations |
| Containerisation | Docker Compose | One-command setup |
| Dashboard | Vanilla HTML/JS | Served directly from FastAPI, no separate frontend server |

---

## Project Structure

```
freight-bill-processor/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env                          # your API keys (not committed)
├── seed_data_logistics.json      # 5 carriers, 8 contracts, 7 shipments, 10 bills
├── app/
│   ├── main.py                   # FastAPI app entry point + static file serving
│   ├── schemas.py                # Pydantic request/response models
│   ├── api/
│   │   └── routes.py             # All 4 API endpoints
│   ├── agent/
│   │   ├── graph.py              # LangGraph state machine (7 nodes)
│   │   ├── rules.py              # Deterministic validation rules (all arithmetic)
│   │   └── llm.py                # Gemini integration (name normalisation + explanations)
│   ├── db/
│   │   ├── models.py             # SQLAlchemy models
│   │   ├── session.py            # DB engine + session factory
│   │   └── graph.py              # NetworkX graph builder + traversal helpers
│   └── static/
│       └── freight_bill_dashboard.html   # Full dashboard UI
└── tests/
    └── test_agent.py             # Deterministic rules unit tests
```

---

## Schema Design

### PostgreSQL Tables

**`freight_bills`** — every bill with its status, confidence score, matched entities, LLM explanation, and flags.

**`audit_log`** — every check the agent ran on every bill (step name, pass/fail, evidence). Full traceability for every decision.

**`review_queue`** — bills the agent paused on. Stores reason and agent state for resume.

### Graph Model (NetworkX)

```
Carrier ──HAS_CONTRACT──► Contract ──COVERS_LANE──► Lane
   │                          │
   └──HAS_SHIPMENT──► Shipment──LINKED_TO_SHIPMENT──┘
                          │
                     HAS_BOL
                          │
                         BOL
```

The agent traverses this graph to answer: *"Given carrier X, lane Y, and bill date Z — which contracts are active, and which shipment and BOL does this bill map to?"*

NetworkX was chosen over Neo4j for zero operational overhead at this dataset scale. With production volume (millions of nodes), Neo4j would be the right upgrade.

---

## Confidence Scoring

Each validation check has a weight. A failed check deducts its weight from 1.0:

| Check | Weight | Triggers when |
|---|---|---|
| Carrier known | 0.20 | Carrier name has no match in system |
| Not duplicate | 0.20 | Same bill number already processed |
| Contract active | 0.20 | No active contract on bill date for this lane |
| Rate within tolerance | 0.15 | Billed rate deviates >5% from contracted rate |
| Weight matches BOL | 0.15 | Billed weight exceeds BOL confirmed weight |
| Fuel surcharge correct | 0.05 | Surcharge doesn't match contract % (incl. mid-term revisions) |
| No contract overlap | 0.05 | Multiple contracts cover same lane/date |

**Score ≥ 0.75** → auto-approve or auto-dispute (based on which checks failed)
**Score < 0.75** → pause for human review

---

## Human-in-the-Loop

When the agent scores below the threshold:
1. Bill is saved to `review_queue` with reason and confidence
2. Status is set to `flagged`
3. Dashboard shows it in the Review Queue tab
4. Reviewer clicks Approve or Dispute, adds optional notes
5. `POST /review/{id}` re-runs the full agent pipeline with reviewer decision injected
6. Agent finalises and updates the bill status

---

## The 10 Test Scenarios

The seed data includes deliberately ambiguous cases:

| Bill | Scenario | Expected Decision |
|---|---|---|
| FB-2025-101 | Clean match — all checks pass | Auto-approved (100%) |
| FB-2025-102 | 3 overlapping contracts, no shipment ref | Flagged (ambiguous) |
| FB-2025-103 | Partial delivery — second truck | Approved |
| FB-2025-104 | Over-billing — claims 1500kg, BOL confirms 1200kg | Disputed |
| FB-2025-105 | Rate drift — 8.75% above contracted rate | Disputed |
| FB-2025-106 | Expired contract used | Disputed |
| FB-2025-107 | FTL contract billed per-kg (valid alternate) | Approved |
| FB-2025-108 | Mid-term fuel surcharge revision applied correctly | Approved |
| FB-2025-109 | Duplicate of FB-2025-101 | Rejected (duplicate) |
| FB-2025-110 | Unknown carrier — no record in system | Flagged (human review) |

---

## LLM vs Deterministic Rules

**LLM (Gemini) is used for:**
- Fuzzy carrier name matching (e.g. "Safexpress" vs "Safexpress Logistics")
- Generating human-readable audit explanations

**Deterministic Python rules handle everything else:**
- Rate deviation calculation
- Weight vs BOL comparison
- Cumulative weight across multiple bills
- Fuel surcharge validation (including mid-term revisions)
- Date range validation
- Duplicate detection

> Rule: Never use an LLM for arithmetic in a financial system.

---

## How to Run Locally

### Prerequisites
- Docker Desktop installed and running
- A free Gemini API key from [aistudio.google.com](https://aistudio.google.com/app/apikey)

### Steps

```bash
# 1. Clone the repo
git clone https://github.com/YOUR_USERNAME/freight-bill-processor.git
cd freight-bill-processor

# 2. Add your Gemini API key
# Open .env and replace the placeholder:
# GEMINI_API_KEY=your_actual_key_here

# 3. Start everything
docker-compose up --build

# 4. Open the dashboard
# http://localhost:8000
```

That's it. The dashboard loads automatically.

### API Docs (Swagger UI)
```
http://localhost:8000/docs
```

### Run Tests
```bash
docker-compose exec api pytest tests/ -v
```

---

## API Reference

### `POST /freight-bills`
Ingest a freight bill. Triggers the agent asynchronously. Returns immediately with `status: processing`.

```json
{
  "id": "FB-2025-101",
  "carrier_id": "CAR001",
  "carrier_name": "Safexpress Logistics",
  "bill_number": "SFX/2025/00234",
  "bill_date": "2025-02-15",
  "shipment_reference": "SHP-2025-002",
  "lane": "DEL-BLR",
  "billed_weight_kg": 850,
  "rate_per_kg": 15.00,
  "base_charge": 12750.00,
  "fuel_surcharge": 1020.00,
  "gst_amount": 2479.00,
  "total_amount": 16249.00
}
```

### `GET /freight-bills/{id}`
Get the current state, decision, confidence score, and full evidence chain for a bill.

### `GET /review-queue`
List all bills currently waiting for human review.

### `POST /review/{id}`
Submit a reviewer decision to resume the agent.

```json
{
  "decision": "approve",
  "notes": "Verified with carrier — rate increase was pre-agreed verbally."
}
```

---

## Environment Variables

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | `postgresql://freight:freight@postgres:5432/freight` |
| `GEMINI_API_KEY` | Google Gemini API key | — |
| `CONFIDENCE_THRESHOLD` | Score below which bills go to human review | `0.75` |

---

## Trade-offs Made

**NetworkX over Neo4j** — NetworkX requires zero additional infrastructure. At production scale with millions of nodes, Neo4j's persistent graph and Cypher query language would be worth the overhead.

**In-memory graph** — The graph is rebuilt on every startup from the seed JSON. In production this would be persisted in the database and updated incrementally.

**Re-run agent on review** — Instead of true LangGraph checkpoint/resume (which requires Redis or a persistent checkpointer), the agent re-runs the full pipeline with the reviewer decision injected. This is simpler and more reliable but slightly less efficient.

**Background tasks** — Agent runs in FastAPI's `BackgroundTasks`. In production, a proper task queue (Celery + Redis or AWS SQS) would give better durability, retries, and monitoring.

---

## What I'd Do With More Time

- Add Redis + LangGraph's `RedisCheckpointer` for true stateful interrupt/resume
- Replace NetworkX with Neo4j for persistent, queryable graph at scale
- Add Celery for reliable async task processing
- Add webhook notifications when bills enter the review queue
- Expand test coverage — especially integration tests hitting the full agent pipeline
- Add a metrics endpoint showing agent performance (approval rate, avg confidence, processing time)
- Deploy to GCP Cloud Run + Cloud SQL

---
