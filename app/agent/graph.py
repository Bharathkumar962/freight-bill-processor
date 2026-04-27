import os
from typing import TypedDict
from langgraph.graph import StateGraph, END
from app.db import graph as kg
from app.agent import rules
from app.agent.llm import normalise_carrier_name, generate_explanation
 
 
class AgentState(TypedDict):
    bill: dict
    bill_id: str
    carrier: dict | None
    matched_contracts: list
    chosen_contract: dict | None
    shipment: dict | None
    bols: list
    checks: list
    flags: list
    confidence: float
    status: str
    decision_reason: str
    reviewer_decision: str | None
    reviewer_notes: str | None
    previously_billed_kg: float
 
 
def node_check_duplicate(state: AgentState) -> AgentState:
    from app.db.session import SessionLocal
    from app.db.models import FreightBill
    bill = state["bill"]
    db = SessionLocal()
    try:
        existing = db.query(FreightBill).filter(
            FreightBill.bill_number == bill["bill_number"],
            FreightBill.carrier_name == bill["carrier_name"],
            FreightBill.id != bill["id"],
        ).first()
    finally:
        db.close()
    passed = existing is None
    checks = list(state.get("checks", [])) + [("duplicate", passed, {
        "bill_number": bill["bill_number"],
        "existing_id": existing.id if existing else None,
    })]
    if not passed:
        return {**state, "checks": checks, "status": "duplicate",
                "decision_reason": f"Duplicate of {existing.id}"}
    return {**state, "checks": checks}
 
 
def node_resolve_carrier(state: AgentState) -> AgentState:
    bill = state["bill"]
    carrier = None
    if bill.get("carrier_id"):
        carrier = kg.get_carrier(bill["carrier_id"])
    if carrier is None:
        carrier = kg.find_carrier_by_name(bill["carrier_name"])
    if carrier is None:
        all_names = [d["name"] for _, d in kg.G.nodes(data=True) if d.get("type") == "carrier"]
        normalised = normalise_carrier_name(bill["carrier_name"], all_names)
        if normalised:
            carrier = kg.find_carrier_by_name(normalised)
    passed = carrier is not None
    checks = list(state.get("checks", [])) + [("carrier_known", passed, {
        "billed_name": bill["carrier_name"],
        "resolved_id": carrier["id"] if carrier else None,
    })]
    return {**state, "carrier": carrier, "checks": checks}
 
 
def node_traverse_graph(state: AgentState) -> AgentState:
    bill = state["bill"]
    carrier = state.get("carrier")
    if not carrier:
        return {**state, "matched_contracts": [], "shipment": None, "bols": []}
    matched = kg.get_active_contracts_for_lane(carrier["id"], bill["lane"], bill["bill_date"])
    shipment = None
    if bill.get("shipment_reference"):
        shipment = kg.get_shipment(bill["shipment_reference"])
    bols = kg.get_bols_for_shipment(shipment["id"]) if shipment else []
    chosen = None
    if matched:
        if shipment and shipment.get("contract_id"):
            for m in matched:
                if m["contract"]["id"] == shipment["contract_id"]:
                    chosen = m
                    break
        if chosen is None:
            chosen = matched[0]
    overlap_flag = len(matched) > 1
    checks = list(state.get("checks", [])) + [
        ("contract_overlap", not overlap_flag, {"contract_count": len(matched)}),
        ("contract_active", chosen is not None, {
            "chosen_contract": chosen["contract"]["id"] if chosen else None,
        }),
    ]
    return {**state, "matched_contracts": matched, "chosen_contract": chosen,
            "shipment": shipment, "bols": bols, "checks": checks}
 
 
def node_validate_charges(state: AgentState) -> AgentState:
    from app.db.session import SessionLocal
    from app.db.models import FreightBill as FBModel
    bill = state["bill"]
    chosen = state.get("chosen_contract")
    bols = state.get("bols", [])
    shipment = state.get("shipment")
    checks = list(state.get("checks", []))
    if not chosen:
        return {**state, "checks": checks}
    rate = chosen["rate"]
    if "rate_per_kg" in rate:
        passed, detail = rules.check_rate(bill["rate_per_kg"], rate["rate_per_kg"])
        checks.append(("rate", passed, detail))
    passed, detail = rules.check_fuel_surcharge(
        bill["fuel_surcharge"], bill["base_charge"], rate, bill["bill_date"])
    checks.append(("fuel_surcharge", passed, detail))
    if bols:
        total_bol_kg = sum(b.get("actual_weight_kg", 0) for b in bols)
        passed, detail = rules.check_weight(bill["billed_weight_kg"], total_bol_kg)
        checks.append(("weight", passed, detail))
    if shipment:
        db = SessionLocal()
        try:
            prev_bills = db.query(FBModel).filter(
                FBModel.shipment_reference == shipment["id"],
                FBModel.id != bill["id"],
                FBModel.status.notin_(["duplicate", "disputed"]),
            ).all()
            prev_kg = sum(b.billed_weight_kg for b in prev_bills)
        finally:
            db.close()
        passed, detail = rules.check_cumulative_weight(
            bill["billed_weight_kg"], shipment["total_weight_kg"], prev_kg)
        checks.append(("cumulative_weight", passed, detail))
    if "rate_per_unit" in rate:
        passed, detail = rules.check_ftl_billing(
            bill["billed_weight_kg"], bill["base_charge"], rate)
        checks.append(("ftl_billing", passed, detail))
    return {**state, "checks": checks}
 
 
def node_score_and_decide(state: AgentState) -> AgentState:
    checks = state.get("checks", [])
    if state.get("status") == "duplicate":
        return {**state, "confidence": 0.0, "flags": ["duplicate bill"]}
    score, flags = rules.compute_confidence(checks)
    threshold = float(os.getenv("CONFIDENCE_THRESHOLD", "0.75"))
    if state.get("reviewer_decision"):
        mapping = {"approve": "approved", "dispute": "disputed", "modify": "flagged"}
        status = mapping.get(state["reviewer_decision"], "flagged")
    elif score >= threshold:
        failed = [c for c in checks if not c[1]]
        status = "disputed" if failed else "approved"
    else:
        status = "flagged"
    return {**state, "confidence": score, "flags": flags, "status": status}
 
 
def node_generate_explanation(state: AgentState) -> AgentState:
    explanation = generate_explanation(
        bill_id=state["bill_id"], status=state["status"],
        confidence=state["confidence"], flags=state["flags"],
        checks=state["checks"], chosen_contract=state.get("chosen_contract"),
    )
    return {**state, "decision_reason": explanation}
 
 
def node_finalize(state: AgentState) -> AgentState:
    from app.db.session import SessionLocal
    from app.db.models import FreightBill as FBModel, AuditLog, ReviewQueue
    db = SessionLocal()
    try:
        bill_row = db.query(FBModel).filter(FBModel.id == state["bill_id"]).first()
        if bill_row:
            bill_row.status = state["status"]
            bill_row.confidence_score = state.get("confidence")
            bill_row.decision_reason = state.get("decision_reason", "")
            bill_row.flags = state.get("flags", [])
            if state.get("chosen_contract"):
                bill_row.matched_contract_id = state["chosen_contract"]["contract"]["id"]
            if state.get("shipment"):
                bill_row.matched_shipment_id = state["shipment"]["id"]
            if state.get("bols"):
                bill_row.matched_bol_id = state["bols"][0]["id"]
            for name, passed, detail in state.get("checks", []):
                db.add(AuditLog(bill_id=state["bill_id"], step=name,
                                result="pass" if passed else "fail", detail=detail))
            if state["status"] == "flagged":
                existing_rq = db.query(ReviewQueue).filter(
                    ReviewQueue.bill_id == state["bill_id"]).first()
                if not existing_rq:
                    flags = state.get("flags", [])
                    db.add(ReviewQueue(
                        bill_id=state["bill_id"],
                        reason="; ".join(flags) if flags else "Low confidence",
                        agent_state={"confidence": state.get("confidence", 0)},
                    ))
            db.commit()
    finally:
        db.close()
    return state
 
 
def route_after_scoring(state: AgentState) -> str:
    if state.get("status") in ("duplicate", "flagged"):
        return "finalize"
    return "generate_explanation"
 
 
def route_after_carrier(state: AgentState) -> str:
    if not state.get("carrier"):
        return "score_and_decide"
    return "traverse_graph"
 
 
def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("check_duplicate",      node_check_duplicate)
    builder.add_node("resolve_carrier",      node_resolve_carrier)
    builder.add_node("traverse_graph",       node_traverse_graph)
    builder.add_node("validate_charges",     node_validate_charges)
    builder.add_node("score_and_decide",     node_score_and_decide)
    builder.add_node("generate_explanation", node_generate_explanation)
    builder.add_node("finalize",             node_finalize)
    builder.set_entry_point("check_duplicate")
    builder.add_edge("check_duplicate", "resolve_carrier")
    builder.add_conditional_edges("resolve_carrier", route_after_carrier, {
        "traverse_graph":   "traverse_graph",
        "score_and_decide": "score_and_decide",
    })
    builder.add_edge("traverse_graph",       "validate_charges")
    builder.add_edge("validate_charges",     "score_and_decide")
    builder.add_conditional_edges("score_and_decide", route_after_scoring, {
        "generate_explanation": "generate_explanation",
        "finalize":             "finalize",
    })
    builder.add_edge("generate_explanation", "finalize")
    builder.add_edge("finalize",             END)
    return builder.compile()
 
 
agent_graph = build_graph()