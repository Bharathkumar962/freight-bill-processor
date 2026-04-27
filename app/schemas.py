from pydantic import BaseModel
from typing import Any
from datetime import datetime

class FreightBillIn(BaseModel):
    id: str
    carrier_id: str | None = None
    carrier_name: str
    bill_number: str
    bill_date: str
    shipment_reference: str | None = None
    lane: str
    billed_weight_kg: float
    rate_per_kg: float
    base_charge: float
    fuel_surcharge: float
    gst_amount: float
    total_amount: float
    billing_unit: str | None = None

class FreightBillOut(BaseModel):
    id: str
    carrier_name: str
    bill_number: str
    bill_date: str
    lane: str
    total_amount: float
    status: str
    confidence_score: float | None = None
    matched_contract_id: str | None = None
    matched_shipment_id: str | None = None
    matched_bol_id: str | None = None
    decision_reason: str | None = None
    flags: list[Any] | None = None
    created_at: datetime
    class Config:
        from_attributes = True

class ReviewQueueItem(BaseModel):
    bill_id: str
    reason: str
    confidence: float | None = None
    created_at: datetime
    class Config:
        from_attributes = True

class ReviewDecisionIn(BaseModel):
    decision: str
    notes: str | None = None
