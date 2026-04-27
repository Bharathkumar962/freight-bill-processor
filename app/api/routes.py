from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from datetime import datetime
from app.db.session import get_db
from app.db.models import FreightBill, ReviewQueue
from app.schemas import FreightBillIn, FreightBillOut, ReviewQueueItem, ReviewDecisionIn
from app.agent.graph import agent_graph, AgentState

router = APIRouter()


def run_agent(bill_payload: dict, bill_id: str, reviewer_decision: str = None, reviewer_notes: str = None):
    initial_state: AgentState = {
        "bill": bill_payload,
        "bill_id": bill_id,
        "carrier": None,
        "matched_contracts": [],
        "chosen_contract": None,
        "shipment": None,
        "bols": [],
        "checks": [],
        "flags": [],
        "confidence": 0.0,
        "status": "processing",
        "decision_reason": "",
        "reviewer_decision": reviewer_decision,
        "reviewer_notes": reviewer_notes,
        "previously_billed_kg": 0.0,
    }
    for _ in agent_graph.stream(initial_state):
        pass


@router.post("/freight-bills", response_model=FreightBillOut, status_code=202)
def ingest_freight_bill(
    payload: FreightBillIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    existing = db.query(FreightBill).filter(FreightBill.id == payload.id).first()
    if existing and existing.status not in ("pending", "processing"):
        raise HTTPException(400, f"Bill {payload.id} already processed: {existing.status}")
    if not existing:
        bill_row = FreightBill(
            id=payload.id, carrier_id=payload.carrier_id, carrier_name=payload.carrier_name,
            bill_number=payload.bill_number, bill_date=payload.bill_date,
            shipment_reference=payload.shipment_reference, lane=payload.lane,
            billed_weight_kg=payload.billed_weight_kg, rate_per_kg=payload.rate_per_kg,
            base_charge=payload.base_charge, fuel_surcharge=payload.fuel_surcharge,
            gst_amount=payload.gst_amount, total_amount=payload.total_amount,
            raw_payload=payload.model_dump(), status="processing",
        )
        db.add(bill_row)
        db.commit()
        db.refresh(bill_row)
    else:
        bill_row = existing
    background_tasks.add_task(run_agent, payload.model_dump(), payload.id)
    return bill_row


@router.get("/freight-bills/{bill_id}", response_model=FreightBillOut)
def get_freight_bill(bill_id: str, db: Session = Depends(get_db)):
    bill = db.query(FreightBill).filter(FreightBill.id == bill_id).first()
    if not bill:
        raise HTTPException(404, f"Bill {bill_id} not found")
    return bill


@router.get("/review-queue")
def get_review_queue(db: Session = Depends(get_db)):
    items = db.query(ReviewQueue).filter(ReviewQueue.reviewer_decision == None).all()
    return [
        {
            "bill_id": item.bill_id,
            "reason": item.reason,
            "confidence": item.agent_state.get("confidence"),
            "created_at": item.created_at,
        }
        for item in items
    ]


@router.post("/review/{bill_id}")
def submit_review(
    bill_id: str,
    decision: ReviewDecisionIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    if decision.decision not in ("approve", "dispute", "modify"):
        raise HTTPException(400, "decision must be approve | dispute | modify")
    review = db.query(ReviewQueue).filter(ReviewQueue.bill_id == bill_id).first()
    if not review:
        raise HTTPException(404, f"No pending review for bill {bill_id}")
    review.reviewer_decision = decision.decision
    review.reviewer_notes = decision.notes
    review.submitted_at = datetime.utcnow()
    db.commit()
    bill = db.query(FreightBill).filter(FreightBill.id == bill_id).first()
    bill.status = "processing"
    db.commit()
    background_tasks.add_task(run_agent, bill.raw_payload, bill_id,
                               decision.decision, decision.notes)
    return {"message": f"Review submitted for {bill_id}. Agent resuming.", "decision": decision.decision}
