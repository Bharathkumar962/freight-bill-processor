import os, json, logging
logger = logging.getLogger(__name__)

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    _llm = ChatGoogleGenerativeAI(model="gemini-1.5-flash",
                                   google_api_key=os.getenv("GEMINI_API_KEY", ""), temperature=0)
    LLM_AVAILABLE = True
except Exception as e:
    logger.warning(f"LLM not available: {e}")
    LLM_AVAILABLE = False
    _llm = None

def normalise_carrier_name(billed_name, known_names):
    if not LLM_AVAILABLE or not known_names:
        return None
    prompt = f"""Match this carrier name to the closest in the list.
Billed name: "{billed_name}"
Known carriers: {json.dumps(known_names)}
Return ONLY the exact matching name, or NO_MATCH if none fits."""
    try:
        result = _llm.invoke(prompt).content.strip()
        return result if result in known_names else None
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return None

def generate_explanation(bill_id, status, confidence, flags, checks, chosen_contract):
    if not LLM_AVAILABLE:
        return _fallback(bill_id, status, confidence, flags, checks)
    passed = [c[0] for c in checks if c[1]]
    failed = [c[0] for c in checks if not c[1]]
    contract_id = chosen_contract["contract"]["id"] if chosen_contract else "none"
    prompt = f"""Write a 2-3 sentence audit note for a logistics team.
Bill: {bill_id} | Decision: {status.upper()} | Confidence: {confidence:.0%}
Contract: {contract_id} | Passed: {passed} | Failed: {failed} | Flags: {flags}
Plain English, no bullet points."""
    try:
        return _llm.invoke(prompt).content.strip()
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return _fallback(bill_id, status, confidence, flags, checks)

def _fallback(bill_id, status, confidence, flags, checks):
    passed = [c[0] for c in checks if c[1]]
    failed = [c[0] for c in checks if not c[1]]
    parts = [f"Bill {bill_id} | {status.upper()} ({confidence:.0%})."]
    if passed: parts.append(f"Passed: {', '.join(passed)}.")
    if failed: parts.append(f"Failed: {', '.join(failed)}.")
    return " ".join(parts)
