import requests
import json
import re

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:1.5b"         

def _call_llm(prompt: str) -> str:
    """Send a prompt to Ollama and return the raw text response."""
    response = requests.post(
        OLLAMA_URL,
        json={"model": MODEL, "prompt": prompt, "stream": False},
        timeout=180
    )
    response.raise_for_status()
    return response.json()["response"]

def extract_pdf_transactions_ai(pdf_text: str) -> list[dict]:
    """
    Ask the LLM to extract a clean JSON list of transactions.
    Each transaction must have: Date, Reference, Amount (float).
    Amount is positive if not specified otherwise.
    """
    prompt = f"""
Tu es un assistant financier. Extrais du texte ci-dessous toutes les transactions bancaires.
Retourne UNIQUEMENT un tableau JSON valide sans aucun autre texte.
Chaque transaction doit avoir les champs : "Date", "Reference", "Amount".
Amount doit être un nombre (float), positif par défaut.
N'inclus pas les lignes de solde ou de total.

Texte :
{pdf_text[:8000]}
"""
    try:
        raw = _call_llm(prompt)
        # The LLM may wrap the JSON in markdown fences; strip them
        json_str = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        transactions = json.loads(json_str)
        # Basic validation: ensure it's a list of dicts with required keys
        if not isinstance(transactions, list):
            return []
        for tx in transactions:
            if not all(k in tx for k in ("Date", "Reference", "Amount")):
                return []       # invalid format, fallback will be used
        return transactions
    except Exception:
        return []               # fallback to rule‑based parser