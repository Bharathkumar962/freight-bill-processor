from datetime import date

RATE_TOLERANCE = 0.05
WEIGHT_TOLERANCE_KG = 0.0

def check_duplicate(bill_number, carrier_name, existing_bill_numbers):
    is_dup = bill_number in existing_bill_numbers
    return (not is_dup, {"bill_number": bill_number, "is_duplicate": is_dup})

def check_carrier_known(carrier_id):
    return (carrier_id is not None, {"carrier_id": carrier_id})

def check_rate(billed_rate, contracted_rate):
    if contracted_rate == 0:
        return (False, {"error": "contracted rate is zero"})
    deviation = (billed_rate - contracted_rate) / contracted_rate
    passed = abs(deviation) <= RATE_TOLERANCE
    return (passed, {"billed_rate": billed_rate, "contracted_rate": contracted_rate,
                     "deviation_pct": round(deviation * 100, 2), "tolerance_pct": RATE_TOLERANCE * 100})

def check_weight(billed_kg, bol_kg):
    overcharge_kg = billed_kg - bol_kg
    passed = overcharge_kg <= WEIGHT_TOLERANCE_KG
    return (passed, {"billed_kg": billed_kg, "bol_kg": bol_kg, "overcharge_kg": overcharge_kg})

def check_cumulative_weight(billed_kg, shipment_total_kg, previously_billed_kg):
    total_billed = previously_billed_kg + billed_kg
    passed = total_billed <= shipment_total_kg
    return (passed, {"this_bill_kg": billed_kg, "previously_billed_kg": previously_billed_kg,
                     "total_billed_kg": total_billed, "shipment_weight_kg": shipment_total_kg,
                     "overcharge_kg": max(0, total_billed - shipment_total_kg)})

def check_fuel_surcharge(billed_surcharge, base_charge, rate, bill_date):
    bill_dt = date.fromisoformat(bill_date)
    fsc_pct = rate.get("fuel_surcharge_percent", 0)
    if "revised_on" in rate:
        revised_dt = date.fromisoformat(rate["revised_on"])
        if bill_dt >= revised_dt:
            fsc_pct = rate.get("revised_fuel_surcharge_percent", fsc_pct)
    expected = round(base_charge * fsc_pct / 100, 2)
    deviation = abs(billed_surcharge - expected)
    return (deviation <= 1.0, {"billed_surcharge": billed_surcharge, "expected_surcharge": expected,
                                "fsc_pct_used": fsc_pct, "deviation": deviation})

def check_ftl_billing(billed_kg, billed_base, rate):
    ftl_rate = rate.get("rate_per_unit", 0)
    alt_rate = rate.get("alternate_rate_per_kg", 0)
    if abs(billed_base - ftl_rate) <= 1.0:
        return (True, {"mode": "FTL_flat", "ftl_rate": ftl_rate, "billed_base": billed_base})
    expected_alt = round(billed_kg * alt_rate, 2)
    if abs(billed_base - expected_alt) <= 1.0:
        return (True, {"mode": "per_kg_alternate", "alt_rate": alt_rate,
                       "billed_kg": billed_kg, "expected": expected_alt, "billed_base": billed_base})
    return (False, {"mode": "unknown", "billed_base": billed_base,
                    "expected_ftl": ftl_rate, "expected_alt_kg": round(billed_kg * alt_rate, 2)})

def compute_confidence(checks):
    weights = {"carrier_known": 0.20, "duplicate": 0.20, "contract_active": 0.20,
               "rate": 0.15, "weight": 0.15, "fuel_surcharge": 0.05, "contract_overlap": 0.05}
    score = 1.0
    flags = []
    for name, passed, detail in checks:
        if not passed:
            score -= weights.get(name, 0.05)
            flags.append(f"{name}: FAILED - {detail}")
    return max(0.0, round(score, 3)), flags
