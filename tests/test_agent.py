"""
Tests for the deterministic rules engine and confidence scoring.
Run with: pytest tests/ -v
"""
import pytest
from app.agent.rules import (
    check_duplicate,
    check_rate,
    check_weight,
    check_cumulative_weight,
    check_fuel_surcharge,
    check_ftl_billing,
    compute_confidence,
)


# ── check_rate ─────────────────────────────────────────────────────────────────

def test_rate_exact_match():
    passed, detail = check_rate(15.00, 15.00)
    assert passed is True
    assert detail["deviation_pct"] == 0.0


def test_rate_within_tolerance():
    # 3% above contracted — within 5% tolerance
    passed, _ = check_rate(15.45, 15.00)
    assert passed is True


def test_rate_drift_fb105():
    # FB-2025-105: billed 8.70 vs contracted 8.00 = 8.75% over — should FAIL
    passed, detail = check_rate(8.70, 8.00)
    assert passed is False
    assert detail["deviation_pct"] == pytest.approx(8.75, rel=0.01)


# ── check_weight ───────────────────────────────────────────────────────────────

def test_weight_exact():
    passed, _ = check_weight(850, 850)
    assert passed is True


def test_weight_under_bol():
    # Bill claims less than BOL — allowed (unlikely but valid)
    passed, _ = check_weight(800, 850)
    assert passed is True


def test_weight_over_bol():
    # Bill claims more than BOL — must FAIL
    passed, detail = check_weight(1500, 1200)
    assert passed is False
    assert detail["overcharge_kg"] == 300


# ── check_cumulative_weight ────────────────────────────────────────────────────

def test_cumulative_weight_ok():
    # SHP-2025-001: 2000 kg total; FB-103 billed 800, FB-104 now claims 1200 — total 2000 = ok
    passed, _ = check_cumulative_weight(1200, 2000, 800)
    assert passed is True


def test_cumulative_weight_overbilling_fb104():
    # FB-2025-104: claims 1500 kg when 800 already billed → total 2300 > 2000
    passed, detail = check_cumulative_weight(1500, 2000, 800)
    assert passed is False
    assert detail["overcharge_kg"] == 300


# ── check_fuel_surcharge ───────────────────────────────────────────────────────

def test_fuel_surcharge_original_rate():
    # Before revision date — should use 12%
    rate = {
        "fuel_surcharge_percent": 12,
        "revised_on": "2024-10-01",
        "revised_fuel_surcharge_percent": 18,
    }
    passed, detail = check_fuel_surcharge(2550.0, 21250.0, rate, "2024-09-01")
    assert passed is True
    assert detail["fsc_pct_used"] == 12


def test_fuel_surcharge_revised_rate_fb108():
    # FB-2025-108: bill_date 2024-11-20 > revised_on 2024-10-01 → must use 18%
    rate = {
        "fuel_surcharge_percent": 12,
        "revised_on": "2024-10-01",
        "revised_fuel_surcharge_percent": 18,
    }
    base = 21250.0
    expected_18pct = 3825.0
    passed, detail = check_fuel_surcharge(expected_18pct, base, rate, "2024-11-20")
    assert passed is True
    assert detail["fsc_pct_used"] == 18


def test_fuel_surcharge_wrong_rate():
    # Using original 12% after revision date — should FAIL
    rate = {
        "fuel_surcharge_percent": 12,
        "revised_on": "2024-10-01",
        "revised_fuel_surcharge_percent": 18,
    }
    wrong_surcharge = 21250.0 * 0.12  # 2550 — old rate
    passed, _ = check_fuel_surcharge(wrong_surcharge, 21250.0, rate, "2024-11-20")
    assert passed is False


# ── check_ftl_billing ──────────────────────────────────────────────────────────

def test_ftl_flat_billing():
    rate = {"rate_per_unit": 48000.0, "unit": "FTL", "alternate_rate_per_kg": 6.50}
    passed, detail = check_ftl_billing(7800, 48000.0, rate)
    assert passed is True
    assert detail["mode"] == "FTL_flat"


def test_ftl_per_kg_alternate_fb107():
    # FB-2025-107: 7800 kg × ₹6.50 = ₹50,700 — valid alternate billing
    rate = {"rate_per_unit": 48000.0, "unit": "FTL", "alternate_rate_per_kg": 6.50}
    passed, detail = check_ftl_billing(7800, 50700.0, rate)
    assert passed is True
    assert detail["mode"] == "per_kg_alternate"


# ── compute_confidence ─────────────────────────────────────────────────────────

def test_confidence_clean_match():
    checks = [
        ("carrier_known",    True,  {}),
        ("duplicate",        True,  {}),
        ("contract_active",  True,  {}),
        ("rate",             True,  {}),
        ("weight",           True,  {}),
        ("fuel_surcharge",   True,  {}),
        ("contract_overlap", True,  {}),
    ]
    score, flags = compute_confidence(checks)
    assert score == 1.0
    assert flags == []


def test_confidence_rate_drift_only():
    checks = [
        ("carrier_known",    True,  {}),
        ("duplicate",        True,  {}),
        ("contract_active",  True,  {}),
        ("rate",             False, {"deviation_pct": 8.75}),
        ("weight",           True,  {}),
        ("fuel_surcharge",   True,  {}),
        ("contract_overlap", True,  {}),
    ]
    score, flags = compute_confidence(checks)
    assert score == pytest.approx(0.85, rel=0.01)
    assert any("rate" in f for f in flags)


def test_confidence_unknown_carrier():
    checks = [
        ("carrier_known", False, {"carrier_id": None}),
    ]
    score, flags = compute_confidence(checks)
    assert score == pytest.approx(0.80, rel=0.01)
