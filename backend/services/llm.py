import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "qwen2.5:1.5b"


def summarize_reconciliation(result: dict) -> str:
    prompt = f"""
Tu es un analyste financier spécialisé dans l'audit et le rapprochement de données réglementaires.

Voici le bilan du rapprochement effectué :
- Lignes concordantes : {result.get("matched", 0)}
- Écarts détectés : {result.get("mismatched", 0)}
- Lignes présentes uniquement dans le PDF : {result.get("pdf_only", 0)}
- Lignes présentes uniquement dans le fichier source : {result.get("csv_only", 0)}
- Taux de conformité globale : {result.get("score", 0)}%

Détails des anomalies : {result.get("details", [])}
Détails des lignes orphelines : {result.get("csv_only_details", [])}

Rédige une synthèse d'audit concise et structurée en français (maximum 6 lignes).
Explique brièvement la nature des écarts s'il y en a, et suggère une action corrective précise.
"""
    try:
        response = requests.post(
            OLLAMA_URL,
            json={"model": MODEL, "prompt": prompt, "stream": False},
            timeout=160
        )
        response.raise_for_status()
        return response.json()["response"]
    except Exception as e:
        return f"Résumé d'analyse indisponible : {str(e)}"