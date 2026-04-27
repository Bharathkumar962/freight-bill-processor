from sqlalchemy import (
    Column, String, Float, Integer, DateTime, JSON, Text, ForeignKey, Enum
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func
import enum

Base = declarative_base()


class BillStatus(str, enum.Enum):
    pending    = "pending"
    processing = "processing"
    approved   = "approved"
    disputed   = "disputed"
    flagged    = "flagged"      # needs human review
    duplicate  = "duplicate"


class ReviewDecision(str, enum.Enum):
    approve  = "approve"
    dispute  = "dispute"
    modify   = "modify"


class FreightBill(Base):
    __tablename__ = "freight_bills"

    id                  = Column(String, primary_key=True)   # e.g. FB-2025-101
    carrier_id          = Column(String, nullable=True)
    carrier_name        = Column(String, nullable=False)
    bill_number         = Column(String, nullable=False)
    bill_date           = Column(String, nullable=False)      # ISO date string
    shipment_reference  = Column(String, nullable=True)
    lane                = Column(String, nullable=False)
    billed_weight_kg    = Column(Float, nullable=False)
    rate_per_kg         = Column(Float, nullable=False)
    base_charge         = Column(Float, nullable=False)
    fuel_surcharge      = Column(Float, nullable=False)
    gst_amount          = Column(Float, nullable=False)
    total_amount        = Column(Float, nullable=False)
    raw_payload         = Column(JSON, nullable=False)        # full original bill

    status              = Column(String, default=BillStatus.pending)
    confidence_score    = Column(Float, nullable=True)
    matched_contract_id = Column(String, nullable=True)
    matched_shipment_id = Column(String, nullable=True)
    matched_bol_id      = Column(String, nullable=True)
    decision_reason     = Column(Text, nullable=True)        # LLM-generated explanation
    flags               = Column(JSON, default=list)         # list of flag strings

    created_at          = Column(DateTime, server_default=func.now())
    updated_at          = Column(DateTime, server_default=func.now(), onupdate=func.now())

    audit_entries       = relationship("AuditLog", back_populates="bill")
    review              = relationship("ReviewQueue", back_populates="bill", uselist=False)


class AuditLog(Base):
    """Every agent decision step is recorded here for full traceability."""
    __tablename__ = "audit_log"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    bill_id     = Column(String, ForeignKey("freight_bills.id"), nullable=False)
    step        = Column(String, nullable=False)   # e.g. "match_contract", "validate_weight"
    result      = Column(String, nullable=False)   # "pass", "fail", "warn"
    detail      = Column(JSON, nullable=True)      # structured evidence
    created_at  = Column(DateTime, server_default=func.now())

    bill        = relationship("FreightBill", back_populates="audit_entries")


class ReviewQueue(Base):
    """Bills paused by the agent awaiting human decision."""
    __tablename__ = "review_queue"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    bill_id         = Column(String, ForeignKey("freight_bills.id"), nullable=False, unique=True)
    reason          = Column(Text, nullable=False)
    agent_state     = Column(JSON, nullable=False)   # serialised LangGraph state for resume
    reviewer_decision = Column(String, nullable=True)
    reviewer_notes  = Column(Text, nullable=True)
    submitted_at    = Column(DateTime, nullable=True)
    created_at      = Column(DateTime, server_default=func.now())

    bill            = relationship("FreightBill", back_populates="review")
