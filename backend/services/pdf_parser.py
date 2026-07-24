import fitz
import os
import re
import zipfile
import io
import unicodedata
import shutil
import base64
import json
import hashlib
import time
from datetime import datetime
from collections import defaultdict
import pytesseract
import requests
from PIL import Image, ImageOps
from services.ai_extractor import extract_pdf_transactions_ai
from services.cache_service import get_cached_metrics, set_cached_metrics

# Flexible date formats: DD/MM/YYYY, YYYY-MM-DD, DD.MM.YYYY, DD-MM-YYYY
DATE_REGEX_STR = r"\d{2}[/\.-]\d{2}[/\.-]\d{2,4}|\d{4}-\d{2}-\d{2}"

# Flexible decimal amounts: handles spaces, non-breaking spaces, commas, or periods
AMOUNT_REGEX_STR = r"\d{1,3}(?:[\s\u00a0\.,]\d{3})*(?:[\.,]\d{2})?"

# Pattern for integrated single-line rows: Date [Reference Text] Amount
ROW_PATTERN = re.compile(
    rf"({DATE_REGEX_STR})\s+(.+?)\s+({AMOUNT_REGEX_STR})$"
)

DATE_PATTERN = re.compile(rf"^(?:{DATE_REGEX_STR})$")
AMOUNT_PATTERN = re.compile(rf"^(?:{AMOUNT_REGEX_STR})$")

SKIP_LINES = re.compile(
    r"^(DATE|LIBELLÉ|LIBELLE|RÉFÉRENCE|REFERENCE|DÉBIT|DEBIT|"
    r"CRÉDIT|CREDIT|EUROS?|Solde|Total|Votre compte|Montant|"
    r"Opérations?|Relevé|N°\s*de\s*compte)",
    re.IGNORECASE
)

OCR_FRONT_WINDOW = 12
OCR_BACK_WINDOW = 12
OCR_SAMPLE_STRIDE = 5
OCR_PREVIEW_DPI = int(os.environ.get("EBA_OCR_PREVIEW_DPI", "120"))
OCR_FULL_DPI = 120
STRUCTURED_OCR_DPI = int(os.environ.get("EBA_STRUCTURED_OCR_DPI", "180"))
VLM_PREVIEW_DPI = int(os.environ.get("EBA_VLM_PREVIEW_DPI", "110"))
VLM_RENDER_DPI = int(os.environ.get("EBA_VLM_RENDER_DPI", "80"))
VLM_MAX_SIDE = int(os.environ.get("EBA_VLM_MAX_SIDE", "900"))
VLM_MAX_PIXELS = int(os.environ.get("EBA_VLM_MAX_PIXELS", "550000"))
VLM_NUM_CTX = int(os.environ.get("EBA_VLM_NUM_CTX", "1536"))
VLM_NUM_PREDICT = int(os.environ.get("EBA_VLM_NUM_PREDICT", "64"))
_TARGET_PAGE_MARKERS = (
    "eu km1",
    "key metrics template",
    "key metrics",
    "indicateurs cles",
    "indicateurs clés",
    "eu ov1",
    "overview of risk-weighted exposure amounts",
    "overview of risk weighted exposure amounts",
    "risk-weighted exposure amounts",
    "risk weighted exposure amounts",
    "capital requirement and risk-weighted assets",
    "capital requirement and risk weighted assets",
    "overview of total risk exposure amounts",
    "total risk exposure amounts",
    "montants totaux d'exposition au risque",
    "montants totaux dexposition au risque",
)

OLLAMA_GENERATE_URL = os.environ.get("OLLAMA_GENERATE_URL", "http://localhost:11434/api/generate")
VLM_MODEL = os.environ.get("EBA_VLM_MODEL", "qwen2.5vl:3b")
VLM_TIMEOUT = int(os.environ.get("EBA_VLM_TIMEOUT", "120"))
VLM_MAX_PAGES = int(os.environ.get("EBA_VLM_MAX_PAGES", "4"))
VLM_PAGES_PROCESSED = 0
VLM_MAX_TOTAL_PAGES = int(os.environ.get("VLM_MAX_TOTAL_PAGES", "20"))
VLM_LOG_FILE = os.path.join(os.path.dirname(__file__), "..", "..", "logs", "vlm_cost.csv")

_TESSERACT_CMD: str | None = None


def _resolve_tesseract_cmd() -> str | None:
    """Find a usable tesseract executable even if PATH was not inherited."""
    global _TESSERACT_CMD
    if _TESSERACT_CMD:
        return _TESSERACT_CMD

    candidates = [
        os.environ.get("TESSERACT_CMD"),
        shutil.which("tesseract"),
        "/usr/bin/tesseract",
        "/usr/local/bin/tesseract",
        r"E:\tesseract\tesseract.exe",
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            _TESSERACT_CMD = candidate
            pytesseract.pytesseract.tesseract_cmd = candidate
            return candidate
    return None


def _normalize_for_match(text: str) -> str:
    """Accent-strip and lowercase text for robust label matching."""
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii").lower()


def _ocr_page_text(page, dpi: int = OCR_FULL_DPI) -> str:
    if not _resolve_tesseract_cmd():
        return ""
    img = _normalize_ocr_image(_render_page_image(page, dpi=dpi))
    try:
        return pytesseract.image_to_string(img, config="--psm 6")
    except pytesseract.TesseractNotFoundError:
        return ""


def _is_metric_candidate(text: str) -> bool:
    normalized = _normalize_for_match(text)
    return bool(_detect_table_kinds(text)) or any(marker in normalized for marker in _TARGET_PAGE_MARKERS)


def _build_ocr_candidate_pages(doc) -> tuple[set[int], dict[int, str]]:
    """
    For textless PDFs, OCR a tight set of pages instead of the whole document.

    We inspect the front matter first, then sample forward only until both KM1
    and OV1 pages have been located. If either table family is still missing,
    the back matter is inspected as a final fallback.
    """
    page_count = doc.page_count
    candidates: set[int] = set()
    cached_texts: dict[int, str] = {}
    found_tables: set[str] = set()

    def inspect_page(page_number: int) -> None:
        if page_number < 1 or page_number > page_count or page_number in cached_texts:
            return
        preview_text = _ocr_page_text(doc[page_number - 1], dpi=OCR_PREVIEW_DPI)
        cached_texts[page_number] = preview_text
        detected_tables = _detect_table_kinds(preview_text)
        found_tables.update(detected_tables)
        if detected_tables or _is_metric_candidate(preview_text):
            window_start = max(1, page_number - 2)
            window_end = min(page_count, page_number + 2)
            candidates.update(range(window_start, window_end + 1))

    try:
        for lvl, title, page_num in doc.get_toc():
            title_lower = str(title).lower()
            if any(kw in title_lower for kw in ["km1", "ov1", "key metrics", "overview of", "indicateurs cl", "vue d'ensemble", "exigences de fonds", "exigences en fonds"]):
                inspect_page(page_num)
                inspect_page(page_num + 1)
    except Exception:
        pass

    if {"KM1", "OV1"} <= found_tables:
        return candidates, cached_texts

    front_end = min(page_count, OCR_FRONT_WINDOW)
    candidates.update(range(1, front_end + 1))
    for page_number in range(1, front_end + 1):
        inspect_page(page_number)

    for page_number in range(1, page_count + 1, OCR_SAMPLE_STRIDE):
        if page_number <= front_end:
            continue
        inspect_page(page_number)
        if {"KM1", "OV1"} <= found_tables:
            break

    if not {"KM1", "OV1"} <= found_tables:
        back_start = max(1, page_count - OCR_BACK_WINDOW + 1)
        candidates.update(range(back_start, page_count + 1))
        for page_number in range(back_start, page_count + 1):
            inspect_page(page_number)

    if not {"KM1", "OV1"} <= found_tables:
        for page_number in range(front_end + 1, page_count + 1):
            inspect_page(page_number)
            if {"KM1", "OV1"} <= found_tables:
                break

    return candidates, cached_texts


def _to_float(raw: str) -> float:
    if not raw:
        return 0.0
    clean = raw.replace("\u00a0", "").replace("\u202f", "").replace(" ", "")
    # Standardize comma decimals to period decimals
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    try:
        return float(clean)
    except ValueError:
        return 0.0


def extract_transactions(pdf_path: str) -> list[dict]:
    doc = fitz.open(pdf_path)
    lines = []

    for page in doc:
        text = page.get_text("text")
        for line in text.splitlines():
            clean_line = line.strip()
            if clean_line:
                lines.append(clean_line)
    doc.close()

    transactions = []
    current = {}

    for line in lines:
        if SKIP_LINES.match(line):
            continue

        # Check for matching single-line format
        row_match = ROW_PATTERN.search(line)
        if row_match:
            if current and "Amount" in current and "Reference" in current:
                transactions.append(current)
            current = {}

            date, ref, amt_str = row_match.groups()
            transactions.append({
                "Date": date,
                "Reference": ref.strip(),
                "Amount": _to_float(amt_str)
            })
            continue

        # Check for sequential (state machine) format
        if DATE_PATTERN.match(line):
            if current and "Amount" in current and "Reference" in current:
                transactions.append(current)
            current = {"Date": line}
            continue

        if AMOUNT_PATTERN.match(line):
            if current and "Amount" not in current:
                current["Amount"] = _to_float(line)
            continue

        if current and "Reference" not in current:
            current["Reference"] = line

    if current and "Amount" in current and "Reference" in current:
        transactions.append(current)

    return transactions

def extract_transactions_ai(pdf_path: str) -> list[dict]:
    """
    Use the LLM to extract transactions from a PDF.
    If it fails, fall back to the normal regex parser (call original extract_transactions).
    """
    doc = fitz.open(pdf_path)
    full_text = "\n".join(page.get_text("text") for page in doc)
    doc.close()

    transactions = extract_pdf_transactions_ai(full_text)
    if not transactions:
        # AI failed, fall back to the classic regex approach
        return extract_transactions(pdf_path)
    return transactions


_METRIC_PATTERNS = {
    "CET1 Ratio": [r"cet1 ratio", r"common equity tier 1 ratio"],
    "Tier 1 Ratio": [r"tier 1 ratio"],
    "Total Capital Ratio": [r"total capital ratio"],
    "Leverage Ratio": [r"leverage ratio"],
    "LCR": [r"liquidity coverage ratio", r"\blcr\b"],
    "NSFR": [r"net stable funding ratio", r"\bnsfr\b"],
    "CET1 Capital": [r"common equity tier 1 \(cet1\) capital", r"cet1 capital before regulatory adjustments"],
    "Tier 1 Capital": [r"tier 1 capital"],
    "Total Capital": [r"total capital"],
    "RWA Total": [r"risk-weighted assets \(rwa\)", r"total exposure measure"],
    "RWA Crédit": [r"credit risk"],
    "RWA CCR": [r"counterparty credit risk"],
    "RWA Marché": [r"market risk"],
    "RWA Opérationnel": [r"operational risk"],
}


_METRIC_PATTERNS_EXTRA = {
    "CET1 Ratio": [
        r"cet1 ratio",
        r"common equity tier 1 ratio",
        r"ratio de fonds propres de base de categorie 1",
        r"ratio de fonds propres de base categorie 1",
    ],
    "Tier 1 Ratio": [
        r"tier 1 ratio",
        r"ratio de fonds propres de categorie 1",
    ],
    "Total Capital Ratio": [
        r"total capital ratio",
        r"ratio de fonds propres totaux",
    ],
    "Leverage Ratio": [
        r"leverage ratio",
        r"ratio de levier",
    ],
    "LCR": [
        r"liquidity coverage ratio",
        r"\blcr\b",
        r"ratio de couverture des besoins de liquidite",
        r"couverture des besoins de liquidite",
    ],
    "NSFR": [
        r"net stable funding ratio",
        r"\bnsfr\b",
        r"ratio nsfr",
    ],
    "CET1 Capital": [
        r"common equity tier 1 \(cet1\) capital",
        r"cet1 capital before regulatory adjustments",
        r"fonds propres de base de categorie 1 \(cet1\)",
        r"fonds propres de base de categorie 1",
    ],
    "Tier 1 Capital": [
        r"tier 1 capital",
        r"fonds propres de categorie 1",
    ],
    "Total Capital": [
        r"total capital",
        r"fonds propres totaux",
    ],
    "RWA Total": [
        r"risk-weighted assets \(rwa\)",
        r"total risk exposure amount",
        r"total risk exposure amounts",
        r"total rwa",
        r"montant total d'exposition au risque",
        r"montant total dexposition au risque",
        r"montant total des risques ponderes",
        r"total des risques ponderes",
        r"risques ponderes",
    ],
    "RWA Crédit": [
        r"credit risk \(excluding ccr\)",
        r"risque de credit \(hors ccr\)",
        r"total credit risk",
        r"total risque de credit",
    ],
    "RWA CCR": [
        r"counterparty credit risk", 
        r"risque de credit de contrepartie", 
        r"risque de contrepartie"
    ],
    "RWA Marché": [
        r"market risk",
        r"risque de marche",
    ],
    "RWA Opérationnel": [
        r"operational risk",
        r"risque operationnel",
    ],
}

_METRIC_PATTERNS = {**_METRIC_PATTERNS, **_METRIC_PATTERNS_EXTRA}


_METRIC_PATTERN_OVERRIDES = {
    "cet1 ratio": [
        r"^ratio de fonds propres de base de categorie 1$",
        r"^ratio de fonds propres de base categorie 1$",
    ],
    "tier 1 ratio": [
        r"^ratio de fonds propres de categorie 1$",
    ],
    "total capital ratio": [
        r"^ratio de fonds propres totaux$",
    ],
    "leverage ratio": [
        r"^ratio de levier$",
    ],
    "lcr": [
        r"^ratio de couverture des besoins de liquidite$",
    ],
    "nsfr": [
        r"^ratio nsfr$",
    ],
    "cet1 capital": [
        r"^fonds propres de base de categorie 1 \(cet1\)$",
    ],
    "tier 1 capital": [
        r"^fonds propres de categorie 1$",
    ],
    "total capital": [
        r"^fonds propres totaux$",
    ],
    "rwa total": [
        r"^montant total des risques ponderes$",
        r"^total des risques ponderes$",
        r"^risques ponderes$",
    ],
    "rwa credit": [
        r"^risque de credit \(hors ccr\)$",
    ],
    "rwa ccr": [
        r"^risque de credit de contrepartie - ccr$",
    ],
    "rwa marche": [
        r"^risque de marche$",
    ],
    "rwa operationnel": [
        r"^risque operationnel$",
    ],
}

_METRIC_NAME_CANONICAL: dict[str, str] = {}
for metric_name in _METRIC_PATTERNS:
    normalized = _normalize_for_match(metric_name)
    _METRIC_NAME_CANONICAL.setdefault(normalized, metric_name)

def _canonical_metric_key(normalized_name: str) -> str | None:
    for metric_name in _METRIC_PATTERNS:
        if _normalize_for_match(metric_name) == normalized_name:
            return metric_name
    return None

for alias_normalized, preferred_normalized in {
    "rwa cradit": "rwa credit",
    "rwa marcha": "rwa marche",
    "rwa oparationnel": "rwa operationnel",
}.items():
    preferred_key = _canonical_metric_key(preferred_normalized)
    if preferred_key is not None:
        _METRIC_NAME_CANONICAL[alias_normalized] = preferred_key

_CANONICAL_METRIC_PATTERNS: dict[str, list[str]] = {}
for metric_name, patterns in _METRIC_PATTERNS.items():
    canonical_name = _METRIC_NAME_CANONICAL[_normalize_for_match(metric_name)]
    if metric_name != canonical_name:
        continue
    pattern_bucket = _CANONICAL_METRIC_PATTERNS.setdefault(canonical_name, [])
    merged_patterns = list(patterns)
    merged_patterns.extend(_METRIC_PATTERN_OVERRIDES.get(_normalize_for_match(metric_name), []))
    for pattern in merged_patterns:
        if pattern not in pattern_bucket:
            pattern_bucket.append(pattern)

_METRIC_PATTERNS = _CANONICAL_METRIC_PATTERNS

_METRIC_ORDER = [
    "CET1 Ratio",
    "Tier 1 Ratio",
    "Total Capital Ratio",
    "Leverage Ratio",
    "LCR",
    "NSFR",
    "CET1 Capital",
    "Tier 1 Capital",
    "Total Capital",
    "RWA Total",
    "RWA Crédit",
    "RWA CCR",
    "RWA Marché",
    "RWA Opérationnel",
]

_KM1_METRICS = {
    "CET1 Ratio",
    "Tier 1 Ratio",
    "Total Capital Ratio",
    "Leverage Ratio",
    "LCR",
    "NSFR",
    "CET1 Capital",
    "Tier 1 Capital",
    "Total Capital",
    "RWA Total",
}

_OV1_METRICS = {"RWA Total", "RWA Crédit", "RWA CCR", "RWA Marché", "RWA Opérationnel"}

_ROW_SCHEMAS = {
    "KM1": {
        "CET1 Capital": {
            "codes": {"1"},
            "patterns": [
                r"(common equity tier\s*1|cet1).*capital",
                r"fonds propres de base.*categorie\s*1",
                r"fonds propres.*cet1",
            ],
            "reject": [r"\bratio\b", r"requirement", r"exigence"],
        },
        "Tier 1 Capital": {
            "codes": {"2"},
            "patterns": [
                r"\btier\s*1\s*capital\b",
                r"\btier\s+capital\b",
                r"fonds propres de categorie\s*1",
                r"total fonds propres de categorie\s*1",
                r"total fonds propres de categorie",
            ],
            "reject": [r"common equity", r"\bcet1\b", r"\bratio\b"],
        },
        "Total Capital": {
            "codes": {"3"},
            "patterns": [
                r"\btotal\s+capital\b",
                r"fonds propres totaux",
                r"fonds propres globaux",
                r"total des fonds propres",
                r"total fonds propres prudentiels",
            ],
            "reject": [r"\bratio\b", r"requirement", r"exigence"],
        },
        "RWA Total": {
            "codes": {"4"},
            "patterns": [
                r"total risk exposure amount",
                r"total risk[-\s]?weighted assets",
                r"risk[-\s]?weighted assets \(?rwa\)?",
                r"montant total .*risques? ponder",
                r"montant total d'?exposition au risque",
                r"total des risques ponder",
                r"total des expositions en risque",
            ],
            "reject": [r"un[-\s]?floored", r"sans application", r"without output"],
        },
        "CET1 Ratio": {
            "codes": {"5"},
            "patterns": [
                r"\bcet1\s+ratio\b",
                r"common equity tier\s*1\s+ratio",
                r"ratio de common equity tier\s*1",
                r"ratio de fonds propres de base",
                r"ratio de cet1",
            ],
            "reject": [r"un[-\s]?floored", r"sans application", r"without output", r"sans plancher", r"avant plancher"],
        },
        "Tier 1 Ratio": {
            "codes": {"6"},
            "patterns": [
                r"\btier\s*1\s+ratio\b",
                r"\btier\s+ratio\b",
                r"ratio de tier\s*1",
                r"ratio de fonds propres de categorie\s*1",
                r"ratio\s+t1\b",
            ],
            "reject": [r"un[-\s]?floored", r"sans application", r"without output", r"sans plancher", r"avant plancher"],
        },
        "Total Capital Ratio": {
            "codes": {"7"},
            "patterns": [
                r"total capital ratio",
                r"ratio de fonds propres totaux",
                r"ratio de fonds propres globaux",
                r"ratio de solvabilite global",
                r"ratio global",
            ],
            "reject": [r"un[-\s]?floored", r"sans application", r"without output", r"sans plancher", r"avant plancher"],
        },
        "Leverage Ratio": {
            "codes": {"14", "13", "12", "15", "16"},
            "patterns": [r"leverage ratio", r"ratio de levier", r"levier", r"leverage"],
            "reject": [r"exposure", r"exposition", r"requirement", r"exigence"],
        },
        "LCR": {
            "codes": set(),
            "patterns": [
                r"liquidity coverage ratio",
                r"\blcr\b",
                r"\blcr\s+ratio\b",
                r"ratio\s+lcr\b",
                r"ratio de couverture des besoins de liquidite",
                r"couverture des besoins de liquidite",
            ],
            "reject": [],
        },
        "NSFR": {
            "codes": set(),
            "patterns": [
                r"net stable funding ratio",
                r"\bnsfr\b",
                r"\bnsfr\s+ratio\b",
                r"ratio\s+nsfr\b",
                r"ratio de financement stable net",
                r"financement stable net",
            ],
            "reject": [],
        },
    },
    "OV1": {
        "RWA Crédit": {
            "codes": {"1", "2"},
            "patterns": [r"credit risk \(?excluding ccr\)?", r"\bcredit risk\b", r"risque de credit"],
            "reject": [r"counterparty", r"contrepartie", r"cva", r"valuation", r"settlement", r"securiti", r"market", r"marche", r"operational", r"operationnel", r"of which", r"dont\b"],
        },
        "RWA CCR": {
            "codes": {"6", "5"},
            "patterns": [r"counterparty credit risk", r"\bccr\b", r"risque de credit de contrepartie", r"risque de contrepartie"],
            "reject": [r"cva", r"including", r"y compris", r"excluding", r"hors", r"of which", r"dont\b"],
        },
        "RWA Marché": {
            "codes": {"20"},
            "patterns": [r"market risk", r"foreign exchange.*commodit", r"risque de marche", r"position.*change.*matieres"],
            "reject": [r"of which", r"dont\b"],
        },
        "RWA Opérationnel": {
            "codes": {"24"},
            "patterns": [r"operational risk", r"risque operationnel"],
            "reject": [r"of which", r"dont\b"],
        },
        "RWA Total": {
            "codes": {"29", "30", "31"},
            "patterns": [r"^total$", r"\btotal\b", r"total risk exposure amount", r"total risk[-\s]?weighted assets"],
            "reject": [r"sub[-\s]?total", r"sous[-\s]?total", r"un[-\s]?floored", r"sans application", r"without output", r"sans plancher", r"avant plancher"],
        },
    },
}


def _matches_any_pattern(normalized_text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, normalized_text, flags=re.IGNORECASE) for pattern in patterns)


def _table_evidence_score(normalized_text: str, table: str) -> int:
    score = 0
    for schema in _ROW_SCHEMAS[table].values():
        if _matches_any_pattern(normalized_text, schema["patterns"]):
            score += 1
    return score


def _is_blacklisted_page(normalized_text: str) -> bool:
    blacklist = [
        "liste des tableaux",
        "table de concordance",
        "cross-reference table",
        "table of contents",
        "list of tables",
        "personne responsable",
        "declaration de la personne responsable",
        "declaration of the responsible person"
    ]
    return any(phrase in normalized_text for phrase in blacklist)


def _detect_table_kinds(text: str) -> set[str]:
    normalized = _normalize_for_match(text)
    normalized = re.sub(r"\s+", " ", normalized)
    
    if _is_blacklisted_page(normalized):
        return set()

    kinds: set[str] = set()

    explicit_km1 = re.search(r"\beu\s+km\s*1\b|\bkm\s*1\b", normalized) is not None
    km1_marker = any(
        marker in normalized
        for marker in (
            "key metrics template",
            "key indicators",
            "indicateurs cles",
            "principaux indicateurs",
            "synthese des principaux indicateurs",
            "fonds propres prudentiels et ratios de solvabilite",
        )
    )
    if explicit_km1 or (km1_marker and _table_evidence_score(normalized, "KM1") >= 2):
        kinds.add("KM1")

    explicit_ov1 = re.search(r"\beu\s+ov\s*1\b|\bov\s*1\b|\beu\s+ovi\b", normalized) is not None
    ov1_marker = any(
        marker in normalized
        for marker in (
            "overview of total risk exposure amounts",
            "overview of risk-weighted exposure amounts",
            "overview of risk weighted exposure amounts",
            "vue densemble des risques ponderes",
            "vue densemble des montants dexposition au risque",
        )
    )
    if explicit_ov1 or (ov1_marker and _table_evidence_score(normalized, "OV1") >= 2):
        kinds.add("OV1")

    return kinds


def _normalize_number(raw: str, as_percent: bool = False, as_million_eur: bool = False) -> float | None:
    if not raw:
        return None
    clean = (
        raw.replace("\u00a0", "")
        .replace("\u202f", "")
        .replace(" ", "")
        .replace("%", "")
        .replace("€", "")
        .replace("$", "")
        .replace("£", "")
    )
    if as_million_eur:
        if clean.startswith("(") and clean.endswith(")"):
            clean = f"-{clean[1:-1]}"
        # EBA KM1/OV1 amount cells are integer values in EUR millions.
        clean = clean.replace(",", "").replace(".", "")
        try:
            return float(clean) * 1_000_000
        except ValueError:
            return None
    if clean.startswith("(") and clean.endswith(")"):
        clean = f"-{clean[1:-1]}"
    if "," in clean and "." in clean:
        if clean.rfind(",") > clean.rfind("."):
            clean = clean.replace(".", "").replace(",", ".")
        else:
            clean = clean.replace(",", "")
    elif "," in clean:
        clean = clean.replace(",", ".")
    try:
        value = float(clean)
    except ValueError:
        return None
    if as_percent:
        return value / 100.0
    if as_million_eur:
        return value * 1_000_000
    return value


def _cache_identifier_for_input(file_name: str, payload: bytes | None, file_path: str | None = None) -> str:
    digest = hashlib.md5()
    if payload is not None:
        digest.update(payload)
    elif file_path:
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    return f"{file_name}:{digest.hexdigest()}"


def _metric_is_percent(metric_name: str) -> bool:
    return metric_name.lower().endswith("ratio") or metric_name in {"LCR", "NSFR"}


def _normalize_amount_number(raw: str) -> float | None:
    if not raw:
        return None

    clean = (
        raw.replace("\u00a0", " ")
        .replace("\u202f", " ")
        .replace("€", "")
        .replace("â‚¬", "")
        .replace("$", "")
        .replace("£", "")
        .replace("Â£", "")
        .replace("%", "")
        .strip()
    )
    if not re.search(r"\d", clean):
        return None

    negative = clean.startswith("(") and clean.endswith(")")
    clean = clean.strip("()")
    clean = re.sub(r"\s+", "", clean)

    if "," in clean and "." in clean:
        decimal_sep = "," if clean.rfind(",") > clean.rfind(".") else "."
        thousand_sep = "." if decimal_sep == "," else ","
        clean = clean.replace(thousand_sep, "").replace(decimal_sep, ".")
    elif "," in clean:
        parts = clean.split(",")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            clean = "".join(parts)
        elif len(parts[-1]) in {1, 2}:
            clean = "".join(parts[:-1]) + "." + parts[-1]
        else:
            clean = clean.replace(",", "")
    elif "." in clean:
        parts = clean.split(".")
        if len(parts) > 1 and all(len(part) == 3 for part in parts[1:]):
            clean = "".join(parts)

    try:
        value = float(clean)
    except ValueError:
        return None
    return -value if negative else value


def _amount_multiplier_from_text(text: str) -> float:
    normalized = _normalize_for_match(text)
    compact = normalized.replace(" ", "")
    if re.search(r"\b(eur|euro|euros|en|in).{0,30}(thousand|thousands|milliers|k\s?euros?|k\s?eur)\b", normalized):
        return 1_000.0
    if "inthousand" in compact or "inethousands" in compact or "enmilliers" in compact or "enkeur" in compact:
        return 1_000.0
    if re.search(r"\b(eur|euro|euros|en|in).{0,30}(million|millions|eurm|m\s?euros?|m\s?eur|mio)\b", normalized):
        return 1_000_000.0
    if "ineurm" in compact or "enmillions" in compact or "millionsdeuros" in compact:
        return 1_000_000.0
    if re.search(r"\b(in|en)\s+(eur|euro|euros)\b", normalized):
        return 1.0
    return 1_000_000.0


def _parse_table_number(raw: str, metric_name: str, amount_multiplier: float = 1_000_000.0) -> float | None:
    if _metric_is_percent(metric_name):
        value = _normalize_number(raw, as_percent=True)
        compact = raw.replace("\u00a0", "").replace(" ", "").replace("%", "").replace(",", "").replace(".", "")
        if value is not None and value > 1 and re.fullmatch(r"\d{3,4}", compact):
            corrected = float(f"{compact[:-2]}.{compact[-2:]}") / 100.0
            if _is_valid_metric_value(metric_name, corrected):
                return corrected
        # Handle OCR decimal-drop: '66' read as '6,6' → try value/10
        if value is not None and not _is_valid_metric_value(metric_name, value):
            corrected_tenth = value / 10.0
            if _is_valid_metric_value(metric_name, corrected_tenth):
                return corrected_tenth
        return value

    raw_value = _normalize_amount_number(raw)
    if raw_value is None:
        return None

    if abs(raw_value) >= 1_000_000_000:
        return raw_value
        
    value = raw_value * amount_multiplier
    if _is_valid_metric_value(metric_name, value):
        return value
        
    # If the scaled value is invalid, we might have guessed the wrong unit for this specific table.
    # Fallback to checking other common multipliers, but prefer the parsed multiplier.
    for fallback in (1_000_000.0, 1_000.0, 1.0):
        if fallback == amount_multiplier:
            continue
        test_val = raw_value * fallback
        if _is_valid_metric_value(metric_name, test_val):
            return test_val
            
    return value


def _is_valid_metric_value(metric_name: str, value: float | None) -> bool:
    if value is None:
        return False
    if metric_name in {"CET1 Ratio", "Tier 1 Ratio", "Total Capital Ratio"}:
        return 0.04 <= value <= 2.0
    if metric_name == "Leverage Ratio":
        return 0.02 <= value <= 0.30
    if metric_name in {"LCR", "NSFR"}:
        return 0.50 <= value <= 1000.0
    if metric_name in {"CET1 Capital", "Tier 1 Capital", "Total Capital"}:
        return 10_000_000 <= value <= 2_000_000_000_000
    if metric_name.startswith("RWA"):
        return 1_000_000 <= value <= 10_000_000_000_000
    return True


def _looks_numeric_cell(text: str) -> bool:
    compact = text.strip().replace("\u00a0", "").replace(" ", "")
    if not re.search(r"\d", compact):
        return False
    return re.fullmatch(r"[\(\)\-+€$£\d,\.:%]+", compact) is not None


def _clean_cell_text(text: str) -> str:
    return text.strip().strip("|").strip()


def _find_value(lines: list[str], start_index: int, as_percent: bool = False, as_million_eur: bool = False) -> float | None:
    numeric_pattern = re.compile(r"\(?-?\d[\d\s\u00a0,\.]*%?\)?")
    search_window = 12 if as_percent else 5

    def scan(prefer_percent: bool = False) -> float | None:
        for offset in range(0, search_window):
            if start_index + offset >= len(lines):
                break
            candidate_line = lines[start_index + offset].strip()
            if not candidate_line:
                continue
            matches = numeric_pattern.findall(candidate_line)
            if prefer_percent:
                matches = [match for match in matches if "%" in match]
            for match in matches:
                if re.fullmatch(r"\(?\d+\)?", match.strip()) and len(match.strip().strip("()")) <= 2:
                    continue
                value = _normalize_number(match, as_percent=as_percent, as_million_eur=as_million_eur)
                if value is not None:
                    return value
        return None

    if as_percent:
        value = scan(prefer_percent=True)
        if value is not None:
            return value
    else:
        value = scan(prefer_percent=False)
        if value is not None:
            return value
    return None


def _strip_json_fences(raw: str) -> str:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start:end + 1]
    return raw


def _render_page_image(page, dpi: int = OCR_FULL_DPI, clip: fitz.Rect | None = None) -> Image.Image:
    pix = page.get_pixmap(dpi=dpi, clip=clip, alpha=False)
    return Image.frombytes("RGB", [pix.width, pix.height], pix.samples)


def _normalize_ocr_image(image: Image.Image) -> Image.Image:
    # Tesseract reads clean, high-contrast grayscale scans more reliably than raw RGB pages.
    grayscale = ImageOps.grayscale(image)
    return ImageOps.autocontrast(grayscale)


def _group_ocr_lines(image: Image.Image) -> list[tuple[str, tuple[int, int, int, int]]]:
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config="--psm 6",
    )
    lines: dict[tuple[int, int, int], dict[str, list[int] | list[str]]] = defaultdict(
        lambda: {"words": [], "left": [], "top": [], "right": [], "bottom": []}
    )

    for index, raw_text in enumerate(data.get("text", [])):
        text = (raw_text or "").strip()
        if not text:
            continue

        key = (
            int(data.get("block_num", [0])[index]),
            int(data.get("par_num", [0])[index]),
            int(data.get("line_num", [0])[index]),
        )
        entry = lines[key]
        entry["words"].append(text)

        left = int(data.get("left", [0])[index])
        top = int(data.get("top", [0])[index])
        width = int(data.get("width", [0])[index])
        height = int(data.get("height", [0])[index])
        entry["left"].append(left)
        entry["top"].append(top)
        entry["right"].append(left + width)
        entry["bottom"].append(top + height)

    grouped_lines: list[tuple[str, tuple[int, int, int, int]]] = []
    for entry in lines.values():
        text = " ".join(entry["words"]).strip()
        if not text:
            continue
        grouped_lines.append(
            (
                text,
                (
                    min(entry["left"]),
                    min(entry["top"]),
                    max(entry["right"]),
                    max(entry["bottom"]),
                ),
            )
        )

    grouped_lines.sort(key=lambda item: (item[1][1], item[1][0]))
    return grouped_lines


def _group_words_by_y(words: list[dict], width: float) -> list[tuple[list[dict], float]]:
    if not words:
        return []

    heights = sorted(max(1.0, word["y1"] - word["y0"]) for word in words)
    median_height = heights[len(heights) // 2]
    tolerance = max(2.5, median_height * 0.65)
    rows: list[list[dict]] = []

    for word in sorted(words, key=lambda item: ((item["y0"] + item["y1"]) / 2.0, item["x0"])):
        center_y = (word["y0"] + word["y1"]) / 2.0
        if not rows:
            rows.append([word])
            continue

        row = rows[-1]
        row_center = sum((item["y0"] + item["y1"]) / 2.0 for item in row) / len(row)
        if abs(center_y - row_center) <= tolerance:
            row.append(word)
        else:
            rows.append([word])

    grouped = [(sorted(row, key=lambda item: item["x0"]), width) for row in rows if row]
    grouped.sort(key=lambda item: (min(word["y0"] for word in item[0]), min(word["x0"] for word in item[0])))
    return grouped


def _extract_row_code(words: list[dict], width: float, table: str) -> str:
    prefix = "km1" if table == "KM1" else "ov1"
    for word in sorted(words, key=lambda item: item["x0"])[:6]:
        if word["x0"] > width * 0.22:
            break
        normalized = _normalize_for_match(word["text"])
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        match = re.fullmatch(rf"(?:eu)?(?:{prefix})?(\d{{1,2}})([a-z]?)", compact)
        if match:
            return f"{int(match.group(1))}{match.group(2)}"
    return ""


def _split_row_words(words: list[dict], width: float, table: str) -> tuple[str, str, list[dict]]:
    sorted_words = sorted(words, key=lambda item: item["x0"])
    first_value_index: int | None = None
    saw_label = False

    for index, word in enumerate(sorted_words):
        text = word["text"]
        normalized = _normalize_for_match(text)
        compact = re.sub(r"[^a-z0-9]", "", normalized)
        is_row_code = (
            word["x0"] <= width * 0.22
            and re.fullmatch(r"(?:eu)?(?:km1|ov1)?\d{1,2}[a-z]?", compact or "") is not None
        )
        if is_row_code:
            continue
        if not _looks_numeric_cell(text):
            saw_label = True
            continue
        compact_digits = re.sub(r"\D", "", text)
        if saw_label and (word["x0"] >= width * 0.38 or "%" in text or len(compact_digits) > 2):
            first_value_index = index
            break

    if first_value_index is None:
        first_value_index = len(sorted_words)

    label_words = []
    for word in sorted_words[:first_value_index]:
        text = word["text"]
        if word["x0"] <= width * 0.22 and _looks_numeric_cell(text):
            continue
        label_words.append(text)

    return (
        _extract_row_code(sorted_words, width, table),
        " ".join(label_words).strip(),
        sorted_words[first_value_index:],
    )


def _row_label_text(words: list[dict], width: float, table: str = "KM1") -> str:
    _, label, _ = _split_row_words(words, width, table)
    return label


def _row_matches_metric(metric_name: str, label: str, table: str, row_code: str = "") -> bool:
    normalized = _normalize_for_match(label)
    normalized = re.sub(r"[_|]+", " ", normalized)
    
    # Strip out standard parenthesized "excluding/hors" clauses to prevent false rejects
    normalized = re.sub(r"\(hors\s+[^)]+\)", "", normalized)
    normalized = re.sub(r"\(excluding\s+[^)]+\)", "", normalized)
    normalized = re.sub(r"\bhors\s+risque\s+de\s+[^)]+\b", "", normalized)
    normalized = re.sub(r"\bexcluding\s+ccr\b", "", normalized)
    normalized = re.sub(r"\bexcluding\s+counterparty\b", "", normalized)
    
    normalized = re.sub(r"\s+", " ", normalized).strip()

    schema = _ROW_SCHEMAS.get(table, {}).get(metric_name)
    if not schema:
        return False
    if _matches_any_pattern(normalized, schema["reject"]):
        return False
    if row_code and schema["codes"] and row_code not in schema["codes"]:
        return False
    return _matches_any_pattern(normalized, schema["patterns"])


def _numeric_cell_texts(words: list[dict], width: float) -> list[str]:
    numeric_words = [
        word
        for word in sorted(words, key=lambda item: item["x0"])
        if _looks_numeric_cell(word["text"])
    ]
    if not numeric_words:
        return []

    cells: list[list[str]] = []
    previous: dict | None = None
    for word in numeric_words:
        if previous is None:
            cells.append([word["text"]])
        else:
            gap = word["x0"] - previous["x1"]
            same_number_gap = max(width * 0.025, 9.0)
            if gap <= same_number_gap:
                cells[-1].append(word["text"])
            else:
                cells.append([word["text"]])
        previous = word

    return [" ".join(cell).strip() for cell in cells if cell]


def _extract_first_value_from_line(
    value_words: list[dict],
    width: float,
    metric_name: str,
    amount_multiplier: float = 1_000_000.0,
) -> float | None:
    for cell_text in _numeric_cell_texts(value_words, width):
        value = _parse_table_number(_clean_cell_text(cell_text), metric_name, amount_multiplier=amount_multiplier)
        if _is_valid_metric_value(metric_name, value):
            return value
    return None


def _ocr_table_lines(page, dpi: int = STRUCTURED_OCR_DPI) -> tuple[list[tuple[list[dict], float]], str]:
    if not _resolve_tesseract_cmd():
        return [], ""
    image = _normalize_ocr_image(_render_page_image(page, dpi=dpi))
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        config="--psm 6",
    )
    word_items: list[dict] = []
    text_parts: list[str] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = _clean_cell_text(raw_text or "")
        if not text:
            continue
        left = float(data.get("left", [0])[index])
        top = float(data.get("top", [0])[index])
        width = float(data.get("width", [0])[index])
        height = float(data.get("height", [0])[index])
        word_items.append({
            "text": text,
            "x0": left,
            "y0": top,
            "x1": left + width,
            "y1": top + height,
        })
        text_parts.append(text)

    lines = _group_words_by_y(word_items, float(image.width))
    return lines, " ".join(text_parts)


def _pdf_table_lines(page) -> tuple[list[tuple[list[dict], float]], str]:
    word_items: list[dict] = []
    text_parts: list[str] = []
    for word in page.get_text("words"):
        x0, y0, x1, y1, text, block_number, line_number, *_ = word
        text = _clean_cell_text(str(text))
        if not text:
            continue
        word_items.append({
            "text": text,
            "x0": float(x0),
            "y0": float(y0),
            "x1": float(x1),
            "y1": float(y1),
        })
        text_parts.append(text)

    lines = _group_words_by_y(word_items, float(page.rect.width))
    return lines, " ".join(text_parts)


def _table_lines_for_page(page, use_ocr: bool) -> tuple[list[tuple[list[dict], float]], str]:
    if use_ocr:
        return _ocr_table_lines(page)
    lines, text = _pdf_table_lines(page)
    
    if text and len(text) > 100:
        mojibake_chars = sum(1 for c in text if c in r"\[]{}^_~")
        if mojibake_chars > len(text) * 0.02:
            print(f"Mojibake detected, ratio {mojibake_chars/len(text):.2f}, running OCR fallback!")
            return _ocr_table_lines(page)

    if lines:
        return lines, text
    return _ocr_table_lines(page)


def _extract_structured_metrics_from_page(
    page,
    page_number: int,
    table: str,
    wanted_metrics: set[str],
    use_ocr: bool,
) -> dict[str, tuple[float, int]]:
    table_metrics = {"KM1": _KM1_METRICS, "OV1": _OV1_METRICS}[table]
    wanted = table_metrics & wanted_metrics
    if not wanted:
        return {}

    lines, page_text = _table_lines_for_page(page, use_ocr=use_ocr)
    amount_multiplier = _amount_multiplier_from_text(page_text or page.get_text("text"))
    
    candidates: dict[str, list[tuple[float, int, str]]] = {m: [] for m in wanted}
    
    for words, width in lines:
        row_code, label, value_words = _split_row_words(words, width, table)
        if not label:
            continue
            
        for metric_name in wanted:
            if not _row_matches_metric(metric_name, label, table, row_code=row_code):
                continue
            value = _extract_first_value_from_line(
                value_words,
                width,
                metric_name,
                amount_multiplier=amount_multiplier,
            )
            if value is not None:
                candidates[metric_name].append((value, page_number, row_code))

    found: dict[str, tuple[float, int]] = {}
    for metric_name, matches in candidates.items():
        if not matches:
            continue
            
        # If multiple matches, try to resolve using strict row code
        schema = _ROW_SCHEMAS.get(table, {}).get(metric_name)
        valid_codes = schema.get("codes", set()) if schema else set()
        
        if len(matches) > 1:
            # Try to filter by exact row code match if codes are defined
            if valid_codes:
                strict_matches = [m for m in matches if m[2] in valid_codes]
                if len(strict_matches) == 1:
                    found[metric_name] = (strict_matches[0][0], strict_matches[0][1])
                    continue
                elif len(strict_matches) > 1:
                    matches = strict_matches # still ambiguous, but narrowed down
                    
            # If all remaining matches have the same value, it's safe
            first_val = matches[0][0]
            if all(m[0] == first_val for m in matches):
                found[metric_name] = (first_val, matches[0][1])
            else:
                # Ambiguous values! Fail loud by not extracting it, avoiding silent wrong values.
                print(f"AMBIGUOUS MATCH for {metric_name} on page {page_number}: {[m[0] for m in matches]}")
        else:
            found[metric_name] = (matches[0][0], matches[0][1])

    return found


def _expand_table_pages(
    page_set: list[tuple[int, list[str], list[str], str]],
    pages: list[tuple[int, list[str], list[str], str]],
    table: str,
    max_forward_pages: int = 2,
) -> list[tuple[int, list[str], list[str], str]]:
    by_number = {page_number: page_info for page_number, *page_info in pages}
    selected = {page_number for page_number, *_ in page_set}
    expanded = list(page_set)

    for base_page, *_ in page_set:
        for offset in range(1, max_forward_pages + 1):
            page_number = base_page + offset
            if page_number in selected or page_number not in by_number:
                continue
            lines, normalized_lines, normalized_text = by_number[page_number]
            
            if _is_blacklisted_page(normalized_text):
                break
            
            # Continuation pages might only have 1 metric remaining (e.g., NSFR on page 2)
            # or they might have explicit "suite" keywords.
            is_continuation = (
                table in _detect_table_kinds(normalized_text)
                or _table_evidence_score(normalized_text, table) >= 1
                or "suite" in normalized_text[:500]
                or "continued" in normalized_text[:500]
            )
            
            if is_continuation:
                expanded.append((page_number, lines, normalized_lines, normalized_text))
                selected.add(page_number)
            else:
                break

    expanded.sort(key=lambda item: item[0])
    return expanded


def _metric_matches_text(metric_name: str, text: str) -> bool:
    normalized_text = _normalize_for_match(text)
    patterns = list(_METRIC_PATTERNS.get(metric_name, []))
    patterns.extend(_METRIC_PATTERN_OVERRIDES.get(_normalize_for_match(metric_name), []))
    return any(re.search(pattern, normalized_text, re.IGNORECASE) for pattern in patterns)


def _build_vlm_crop_rect(page, wanted_metrics: list[str]) -> fitz.Rect | None:
    preview = _normalize_ocr_image(_render_page_image(page, dpi=VLM_PREVIEW_DPI))
    line_boxes = _group_ocr_lines(preview)
    matched_boxes = [
        bbox
        for text, bbox in line_boxes
        if any(_metric_matches_text(metric_name, text) for metric_name in wanted_metrics)
    ]

    if not matched_boxes:
        return None

    width, height = preview.size
    x0 = min(box[0] for box in matched_boxes)
    y0 = min(box[1] for box in matched_boxes)
    x1 = max(box[2] for box in matched_boxes)
    y1 = max(box[3] for box in matched_boxes)

    # Keep the crop broad enough to preserve table columns, but narrow enough to stay well inside context.
    if (x1 - x0) < width * 0.70:
        x0 = int(width * 0.04)
        x1 = int(width * 0.96)
    else:
        x0 = max(0, x0 - int(width * 0.03))
        x1 = min(width, x1 + int(width * 0.03))

    vertical_pad = max(int((y1 - y0) * 0.35), int(height * 0.05), 20)
    y0 = max(0, y0 - vertical_pad)
    y1 = min(height, y1 + vertical_pad)

    scale = 72.0 / float(VLM_PREVIEW_DPI)
    crop = fitz.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale)
    crop &= page.rect
    if crop.is_empty or crop.width <= 0 or crop.height <= 0:
        return None
    return crop


def _image_to_base64_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _prepare_vlm_image(page, crop: fitz.Rect, dpi: int) -> Image.Image:
    image = _render_page_image(page, dpi=dpi, clip=crop)
    image = _normalize_ocr_image(image)

    max_side = max(image.size)
    total_pixels = image.width * image.height
    if max_side > VLM_MAX_SIDE or total_pixels > VLM_MAX_PIXELS:
        side_scale = VLM_MAX_SIDE / float(max_side) if max_side > VLM_MAX_SIDE else 1.0
        pixel_scale = (VLM_MAX_PIXELS / float(total_pixels)) ** 0.5 if total_pixels > VLM_MAX_PIXELS else 1.0
        scale = min(side_scale, pixel_scale)
        resized = (
            max(1, int(round(image.width * scale))),
            max(1, int(round(image.height * scale))),
        )
        resampling = getattr(Image, "Resampling", Image).LANCZOS
        image = image.resize(resized, resampling)

    return image


def _log_vlm_call(entity: str, field: str, prompt_tokens: int, completion_tokens: int):
    global VLM_PAGES_PROCESSED
    VLM_PAGES_PROCESSED += 1
    
    os.makedirs(os.path.dirname(VLM_LOG_FILE), exist_ok=True)
    file_exists = os.path.exists(VLM_LOG_FILE)
    with open(VLM_LOG_FILE, "a", encoding="utf-8") as f:
        if not file_exists:
            f.write("timestamp,entity,field,prompt_tokens,completion_tokens\n")
        ts = datetime.now().isoformat()
        f.write(f"{ts},{entity},{field},{prompt_tokens},{completion_tokens}\n")

def _call_vlm(page, wanted_metrics: list[str], crop: fitz.Rect, dpi: int, file_name: str) -> dict:
    global VLM_PAGES_PROCESSED
    if VLM_PAGES_PROCESSED >= VLM_MAX_TOTAL_PAGES:
        print(f"VLM HARD STOP REACHED: Exceeded max pages ({VLM_MAX_TOTAL_PAGES}) per run.")
        return {}

    prompt = (
        "Extract only the requested metric values from this page image. "
        "Return JSON only. "
        f"Keys: {wanted_metrics}. "
        "Use null when a value is not visible. "
        "Ratios must be decimals, e.g. 12.6% -> 0.126. "
        "Amounts are in euros; if the table states EUR millions, multiply by 1000000."
    )

    image = _prepare_vlm_image(page, crop, dpi)
    b64_image = _image_to_base64_png(image)
    
    start_time = time.time()
    # Load .env file automatically if present
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        os.environ.setdefault(k.strip(), v.strip().strip("'\""))
        except Exception:
            pass

    use_openai = os.environ.get("EBA_USE_OPENAI_VLM") == "1"
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    
    try:
        if use_openai and openai_api_key:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "gpt-4o",
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_image}"}}
                            ]
                        }
                    ],
                    "response_format": {"type": "json_object"}
                },
                timeout=(10, VLM_TIMEOUT)
            )
            response.raise_for_status()
            response_json = response.json()
            payload = json.loads(response_json["choices"][0]["message"]["content"])
            usage = response_json.get("usage", {})
            _log_vlm_call(
                entity=file_name,
                field="|".join(wanted_metrics),
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0)
            )
        else:
            response = requests.post(
                OLLAMA_GENERATE_URL,
                json={
                    "model": VLM_MODEL,
                    "prompt": prompt,
                    "images": [b64_image],
                    "stream": False,
                    "format": "json",
                    "keep_alive": "15m",
                    "options": {
                        "temperature": 0,
                        "num_ctx": VLM_NUM_CTX,
                        "num_predict": VLM_NUM_PREDICT,
                    },
                },
                timeout=(10, VLM_TIMEOUT),
            )
            response.raise_for_status()
            response_json = response.json()
            payload = json.loads(_strip_json_fences(response_json.get("response", "")))
            
    finally:
        elapsed = time.time() - start_time
        print(f"VLM call for page {page.number} took {elapsed:.2f} seconds.")

    return payload if isinstance(payload, dict) else {}


def _extract_missing_metrics_with_vlm(doc, page_numbers: list[int], wanted_metrics: list[str], file_name: str) -> dict[str, tuple[float, int]]:
    """
    Use Qwen2.5-VL as a narrow last resort.

    We keep the prompt small, crop the page to the metric table area, and
    progressively relax the request only if the first attempt fails.
    """
    if (
        not wanted_metrics
        or os.environ.get("EBA_DISABLE_VLM") == "1"
    ):
        return {}

    results: dict[str, tuple[float, int]] = {}
    page_numbers = list(dict.fromkeys(page_numbers))[:VLM_MAX_PAGES]
    metric_chunks = [
        wanted_metrics[i:i + 4]
        for i in range(0, len(wanted_metrics), 4)
    ]

    for page_number in page_numbers:
        remaining = [name for name in wanted_metrics if name not in results]
        if not remaining:
            break

        page = doc[page_number - 1]

        # First try the full remaining set. If that fails, fall back to smaller chunks.
        request_sets = [remaining]
        if len(remaining) > 4:
            request_sets = metric_chunks

        crop = _build_vlm_crop_rect(page, remaining)
        if crop is None:
            # A broad fallback crop is still far cheaper than sending the full page.
            page_rect = page.rect
            crop = fitz.Rect(
                page_rect.x0 + (page_rect.width * 0.04),
                page_rect.y0 + (page_rect.height * 0.12),
                page_rect.x1 - (page_rect.width * 0.04),
                page_rect.y1 - (page_rect.height * 0.12),
            )

        for request_metrics in request_sets:
            remaining = [name for name in wanted_metrics if name not in results]
            request_metrics = [metric for metric in request_metrics if metric in remaining]
            if not request_metrics:
                continue

            attempts = [(VLM_RENDER_DPI, crop), (max(50, VLM_RENDER_DPI - 20), crop)]
            for attempt_dpi, attempt_crop in attempts:
                try:
                    payload = _call_vlm(page, request_metrics, attempt_crop, attempt_dpi, file_name)
                except Exception as exc:
                    print(f"Qwen2.5-VL metric extraction skipped on page {page_number}: {exc}")
                    continue

                if not payload:
                    continue

                for raw_name, raw_value in payload.items():
                    metric_name = next(
                        (
                            candidate
                            for candidate in request_metrics
                            if _normalize_for_match(candidate) == _normalize_for_match(raw_name)
                        ),
                        None,
                    )
                    if not metric_name or raw_value in (None, ""):
                        continue

                    if isinstance(raw_value, str):
                        parsed = _normalize_number(
                            raw_value,
                            as_percent=metric_name.lower().endswith("ratio") or metric_name in {"LCR", "NSFR"},
                        )
                    else:
                        try:
                            parsed = float(raw_value)
                        except (TypeError, ValueError):
                            parsed = None

                    if _is_valid_metric_value(metric_name, parsed) and metric_name not in results:
                        results[metric_name] = (parsed, page_number)

                break

            if not [name for name in wanted_metrics if name not in results]:
                break

    return results


def _extract_bank_metrics_legacy(file_path: str, use_vlm: bool = False) -> list[dict]:
    """Extract a compact set of bank metrics from a ZIP or PDF file."""
    # 1. Check Cache
    file_name = file_path.split("/")[-1].split("\\")[-1]
    cached = get_cached_metrics(file_name)
    if cached is not None:
        return cached

    # 2. Extract PDF from ZIP if needed
    pdf_bytes = None
    if file_path.lower().endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            for name in zip_ref.namelist():
                if name.lower().endswith('.pdf'):
                    pdf_bytes = zip_ref.read(name)
                    break
        if not pdf_bytes:
            return []
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    else:
        doc = fitz.open(file_path)

    metrics: list[dict] = []
    seen = set()
    pages: list[tuple[int, list[str], list[str], str]] = []
    summary_pages: list[tuple[int, list[str], list[str], str]] = []
    ov1_pages: list[tuple[int, list[str], list[str], str]] = []
    summary_text: str | None = None
    summary_page_number: int | None = None
    ov1_text: str | None = None
    ov1_page_number: int | None = None

    # Check text content length to decide if OCR is needed
    total_chars = 0
    for page in doc:
        total_chars += len(page.get_text("text"))

    needs_ocr = total_chars < 1000
    ocr_candidate_pages: set[int] = set()
    ocr_text_cache: dict[int, str] = {}
    if needs_ocr:
        ocr_candidate_pages, ocr_text_cache = _build_ocr_candidate_pages(doc)

    for page_number, page in enumerate(doc, start=1):
        text = page.get_text("text")
        
        # 3. Open-source OCR fallback using pytesseract if text is empty
        if needs_ocr and not text.strip():
            if ocr_candidate_pages and page_number not in ocr_candidate_pages:
                continue
            try:
                text = ocr_text_cache.get(page_number) or _ocr_page_text(page, dpi=OCR_FULL_DPI)
            except Exception as e:
                print(f"OCR failed on page {page_number}: {e}")
                text = ""

        if not text:
            continue
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        normalized_lines = [_normalize_for_match(line) for line in lines]
        normalized_text = _normalize_for_match(text)
        pages.append((page_number, lines, normalized_lines, normalized_text))
        if "eu km1" in normalized_text or "key metrics template" in normalized_text:
            summary_pages.append((page_number, lines, normalized_lines, normalized_text))
            if summary_text is None:
                summary_text = text
                summary_page_number = page_number
        if (
            "eu ov1" in normalized_text
            or "overview of total risk exposure amounts" in normalized_text
            or "overview of risk-weighted exposure amounts" in normalized_text
            or "overview of risk weighted exposure amounts" in normalized_text
            or "risk-weighted exposure amounts" in normalized_text
            or "risk weighted exposure amounts" in normalized_text
            or "capital requirement and risk-weighted assets" in normalized_text
            or "capital requirement and risk weighted assets" in normalized_text
        ):
            ov1_pages.append((page_number, lines, normalized_lines, normalized_text))
            if ov1_text is None:
                ov1_text = text
                ov1_page_number = page_number

    def add_metric(metric_name: str, value: float, page_number: int) -> None:
        if metric_name in seen:
            return
        seen.add(metric_name)
        metrics.append({
            "Indicateur": metric_name,
            "Valeur PDF (EBA)": value,
            "Source PDF": f"page {page_number}",
        })

    if summary_text and summary_page_number is not None:
        summary_patterns = {
            "CET1 Ratio": (r"Common Equity Tier\s*1 ratio \(%\)\s+([\d\.,]+)%", True, False),
            "Tier 1 Ratio": (r"Tier\s*1 ratio \(%\)\s+([\d\.,]+)%", True, False),
            "Total Capital Ratio": (r"Total capital ratio \(%\)\s+([\d\.,]+)%", True, False),
            "Leverage Ratio": (r"Leverage ratio \(%\)\s+([\d\.,]+)%", True, False),
            "LCR": (r"Liquidity coverage ratio \(%\)\s+([\d\.,]+)%", True, False),
            "NSFR": (r"NSFR ratio \(%\)\s+([\d\.,]+)%", True, False),
            "CET1 Capital": (r"Common Equity Tier ?1 \(CET1\) capital\s+([\d\.,]+)", False, True),
            "Tier 1 Capital": (r"Tier 1 capital\s+([\d\.,]+)", False, True),
            "Total Capital": (r"Total capital\s+([\d\.,]+)", False, True),
        }

        for metric_name, (pattern, as_percent, as_million_eur) in summary_patterns.items():
            match = re.search(pattern, summary_text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            value = _normalize_number(match.group(1), as_percent=as_percent, as_million_eur=as_million_eur)
            if value is not None:
                add_metric(metric_name, value, summary_page_number)

    if ov1_text and ov1_page_number is not None:
        ov1_patterns = {
            "RWA Crédit": r"Credit risk \(excluding CCR\)\s+([\d\.,]+)",
            "RWA CCR": r"Counterparty credit risk - CCR\s+([\d\.,]+)",
            "RWA Marché": r"Position, foreign exchange and commodities risks \(Market risk\)\s+([\d\.,]+)",
            "RWA Opérationnel": r"Operational risk\s+([\d\.,]+)",
            "RWA Total": r"TOTAL\s+([\d\.,]+)",
        }

        for metric_name, pattern in ov1_patterns.items():
            match = re.search(pattern, ov1_text, flags=re.IGNORECASE | re.DOTALL)
            if not match:
                continue
            value = _normalize_number(match.group(1), as_million_eur=True)
            if value is not None:
                add_metric(metric_name, value, ov1_page_number)

    for metric_name, patterns in _METRIC_PATTERNS.items():
        strict_patterns = _METRIC_PATTERN_OVERRIDES.get(_normalize_for_match(metric_name), [])
        candidates = pages
        if metric_name in {"CET1 Ratio", "Tier 1 Ratio", "Total Capital Ratio", "Leverage Ratio", "LCR", "NSFR", "CET1 Capital", "Tier 1 Capital", "Total Capital"}:
            candidates = summary_pages or pages
        elif metric_name in {"RWA Total", "RWA Crédit", "RWA CCR", "RWA Marché", "RWA Opérationnel"}:
            candidates = ov1_pages or pages

        chosen_value = None
        chosen_page = None
        for page_number, lines, normalized_lines, normalized_text in candidates:
            if metric_name in seen:
                break

            matching_indexes: list[int] = []
            if strict_patterns:
                for index, normalized_line in enumerate(normalized_lines):
                    if any(re.search(pattern, normalized_line, re.IGNORECASE) for pattern in strict_patterns):
                        matching_indexes.append(index)

            if not matching_indexes:
                for index, normalized_line in enumerate(normalized_lines):
                    if any(re.search(pattern, normalized_line, re.IGNORECASE) for pattern in patterns):
                        matching_indexes.append(index)

            if not matching_indexes:
                continue

            as_percent = _metric_is_percent(metric_name)
            as_million_eur = not as_percent

            for matched_index in matching_indexes:
                value = _find_value(lines, matched_index, as_percent=as_percent, as_million_eur=as_million_eur)
                if value is None:
                    continue

                chosen_value = value
                chosen_page = page_number
                break

            if chosen_value is not None and chosen_page is not None:
                break

        if chosen_value is None or chosen_page is None:
            continue

        seen.add(metric_name)
        metrics.append({
            "Indicateur": metric_name,
            "Valeur PDF (EBA)": chosen_value,
            "Source PDF": f"page {chosen_page} (OCR)" if needs_ocr else f"page {chosen_page}",
        })

    missing_metrics = [metric_name for metric_name in _METRIC_PATTERNS if metric_name not in seen]
    if missing_metrics and use_vlm and os.environ.get("EBA_DISABLE_VLM") != "1":
        vlm_page_numbers: list[int] = []
        for page_number, *_ in summary_pages + ov1_pages:
            if page_number not in vlm_page_numbers:
                vlm_page_numbers.append(page_number)
        for page_number, _, _, normalized_text in pages:
            if _is_metric_candidate(normalized_text) and page_number not in vlm_page_numbers:
                vlm_page_numbers.append(page_number)
        for page_number in range(1, min(doc.page_count, 12) + 1):
            if page_number not in vlm_page_numbers:
                vlm_page_numbers.append(page_number)

        vlm_metrics = _extract_missing_metrics_with_vlm(doc, vlm_page_numbers, missing_metrics, file_name)
        for metric_name, (value, page_number) in vlm_metrics.items():
            if metric_name in seen:
                continue
            seen.add(metric_name)
            metrics.append({
                "Indicateur": metric_name,
                "Valeur PDF (EBA)": value,
                "Source PDF": f"page {page_number} (Qwen2.5-VL)",
            })

    doc.close()
    
    # Save to Cache
    set_cached_metrics(file_name, metrics)
    return metrics


def extract_bank_metrics(file_path: str, use_vlm: bool = False) -> list[dict]:
    """Extract bank KM1/OV1 metrics deterministically from a ZIP or PDF file."""
    file_name = file_path.split("/")[-1].split("\\")[-1]
    pdf_bytes = None

    if file_path.lower().endswith(".zip"):
        with zipfile.ZipFile(file_path, "r") as zip_ref:
            for name in zip_ref.namelist():
                if name.lower().endswith(".pdf"):
                    pdf_bytes = zip_ref.read(name)
                    break
        if not pdf_bytes:
            return []
        cache_identifier = _cache_identifier_for_input(file_name, pdf_bytes)
        cached = get_cached_metrics(cache_identifier)
        if cached is not None:
            return cached
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    else:
        cache_identifier = _cache_identifier_for_input(file_name, None, file_path)
        cached = get_cached_metrics(cache_identifier)
        if cached is not None:
            return cached
        doc = fitz.open(file_path)

    metrics: list[dict] = []
    seen: set[str] = set()
    pages: list[tuple[int, list[str], list[str], str]] = []
    summary_pages: list[tuple[int, list[str], list[str], str]] = []
    ov1_pages: list[tuple[int, list[str], list[str], str]] = []
    summary_text: str | None = None
    summary_page_number: int | None = None
    ov1_text: str | None = None
    ov1_page_number: int | None = None

    try:
        total_chars = 0
        has_mojibake_page = False
        for page in doc:
            text = page.get_text("text")
            total_chars += len(text)
            if len(text) > 500:
                mojibake_chars = sum(1 for c in text if c in r"\[]{}^_~")
                if mojibake_chars / len(text) > 0.05:
                    has_mojibake_page = True

        needs_ocr = total_chars < 1000 or has_mojibake_page
        ocr_candidate_pages: set[int] = set()
        ocr_text_cache: dict[int, str] = {}
        if needs_ocr:
            ocr_candidate_pages, ocr_text_cache = _build_ocr_candidate_pages(doc)

        ocr_used_pages: set[int] = set()

        toc_target_pages = set()
        try:
            for lvl, title, page_num in doc.get_toc():
                title_lower = str(title).lower()
                if any(kw in title_lower for kw in ["km1", "ov1", "key metrics", "overview of", "indicateurs cl", "vue d'ensemble", "exigences de fonds", "exigences en fonds"]):
                    toc_target_pages.add(page_num)
                    toc_target_pages.add(page_num + 1)
        except Exception:
            pass

        page_sequence = sorted(list(toc_target_pages)) + [p for p in range(1, doc.page_count + 1) if p not in toc_target_pages]

        for page_number in page_sequence:
            page = doc[page_number - 1]
            native_text = page.get_text("text")
            text = native_text
            
            # Check if this page specifically needs OCR fallback (e.g. is mostly empty or scanned)
            page_needs_ocr = needs_ocr
            if not page_needs_ocr:
                trimmed_len = len(native_text.strip())
                if trimmed_len < 1500:
                    lowered = native_text.lower()
                    has_keywords = any(kw in lowered for kw in [
                        "km1", "ov1", "key metrics", "overview of", "indicateurs cles", 
                        "vue d'ensemble", "exigences de fonds", "capital requirement"
                    ])
                    if has_keywords or trimmed_len < 100:
                        page_needs_ocr = True

            if page_needs_ocr:
                if ocr_candidate_pages and page_number not in ocr_candidate_pages and needs_ocr:
                    # Not a table-candidate page in a purely scanned PDF
                    if not native_text.strip():
                        continue
                else:
                    # Candidate page: run OCR
                    try:
                        text = ocr_text_cache.get(page_number)
                        if not text:
                            text = _ocr_page_text(page, dpi=OCR_FULL_DPI)
                            ocr_text_cache[page_number] = text
                        ocr_used_pages.add(page_number)
                    except Exception as exc:
                        print(f"OCR failed on page {page_number}: {exc}")
                        text = native_text  # fall back to native if OCR fails

            if not text:
                continue
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            normalized_lines = [_normalize_for_match(line) for line in lines]
            normalized_text = _normalize_for_match(text)
            pages.append((page_number, lines, normalized_lines, normalized_text))

            detected_tables = _detect_table_kinds(text)

            if "KM1" in detected_tables:
                summary_pages.append((page_number, lines, normalized_lines, normalized_text))
                if summary_text is None:
                    summary_text = text
                    summary_page_number = page_number

            if "OV1" in detected_tables:
                ov1_pages.append((page_number, lines, normalized_lines, normalized_text))
                if ov1_text is None:
                    ov1_text = text
                    ov1_page_number = page_number

        def add_metric(metric_name: str, value: float, page_number: int, source_suffix: str = "") -> None:
            if metric_name in seen or not _is_valid_metric_value(metric_name, value):
                return
            seen.add(metric_name)
            source = f"page {page_number}{source_suffix}"
            metrics.append({
                "Indicateur": metric_name,
                "Valeur PDF (EBA)": value,
                "Source PDF": source,
            })

        summary_pages = _expand_table_pages(summary_pages, pages, "KM1")
        ov1_pages = _expand_table_pages(ov1_pages, pages, "OV1")
        
        wanted_metrics = set(_METRIC_ORDER)
        for table_name, page_set in (("KM1", summary_pages), ("OV1", ov1_pages)):
            for page_number, *_ in page_set:
                page_was_ocr = (needs_ocr or page_number in ocr_used_pages)
                extracted = _extract_structured_metrics_from_page(
                    doc[page_number - 1],
                    page_number,
                    table_name,
                    wanted_metrics - seen,
                    use_ocr=page_was_ocr,
                )
                for metric_name, (value, source_page) in extracted.items():
                    add_metric(metric_name, value, source_page, " (OCR table)" if page_was_ocr else " (table)")

        if summary_text and summary_page_number is not None:
            # Each entry: (patterns list, as_percent, as_million_eur)
            # Multiple patterns tried in order; first successful match wins.
            summary_patterns: dict[str, tuple[list[str], bool, bool]] = {
                "CET1 Ratio": ([
                    r"Common Equity Tier\s*1 ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio de fonds propres de base de cat.{1,15}gorie\s*1\s*\(%\)\s+([\d\.,]+)%",
                    r"cet1\s+ratio\s*\(?%\)?\s+([\d\.,]+)%",
                    r"Ratio\s+CET\s*1\s*:\s*([\d\.,]+)%",
                    r"CET\s*1\s*:\s*([\d\.,]+)%",
                ], True, False),
                "Tier 1 Ratio": ([
                    r"Tier\s*1 ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio de fonds propres de cat.{1,15}gorie\s*1\s*\(%\)\s+([\d\.,]+)%",
                ], True, False),
                "Total Capital Ratio": ([
                    r"Total capital ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio de fonds propres totaux\s*\(%\)\s+([\d\.,]+)%",
                ], True, False),
                "Leverage Ratio": ([
                    r"Leverage ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio de levier\s*\(%\)\s+([\d\.,]+)%",
                ], True, False),
                "LCR": ([
                    r"Liquidity coverage ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio de couverture des besoins de liquidit.{1,5}\s*\(%\)\s+([\d\.,]+)%",
                ], True, False),
                "NSFR": ([
                    r"NSFR ratio \(%\)\s+([\d\.,]+)%",
                    r"ratio\s+nsfr\s*\(%\)\s+([\d\.,]+)%",
                ], True, False),
                "CET1 Capital": ([
                    r"Common Equity Tier ?1 \(CET1\) capital\s+([\d\.,]+)",
                    r"fonds propres de base de cat.{1,15}gorie\s*1\s*\(CET1\)\s+([\d\s\u00a0]+)",
                ], False, True),
                "Tier 1 Capital": ([
                    r"Tier 1 capital\s+([\d\.,]+)",
                    r"fonds propres de cat.{1,15}gorie\s*1\s+([\d\s\u00a0]+)",
                ], False, True),
                "Total Capital": ([
                    r"Total capital\s+([\d\.,]+)",
                    r"fonds propres totaux\s+([\d\s\u00a0]+)",
                ], False, True),
            }
            # Try each summary page (not just the first) so multi-page tables are covered
            all_summary_texts = [(pn, pg_text) for pn, *_, pg_text in summary_pages]
            if not all_summary_texts:
                all_summary_texts = [(summary_page_number, summary_text)]
            for metric_name, (patterns, as_percent, as_million_eur) in summary_patterns.items():
                if metric_name in seen:
                    continue
                for pg_num, pg_text in all_summary_texts:
                    matched = False
                    for pattern in patterns:
                        match = re.search(pattern, pg_text, flags=re.IGNORECASE | re.DOTALL)
                        if match:
                            value = _normalize_number(match.group(1), as_percent=as_percent, as_million_eur=as_million_eur)
                            if value is not None:
                                add_metric(metric_name, value, pg_num)
                                matched = True
                                break
                    if matched or metric_name in seen:
                        break

            # Last-resort: search ALL pages for metrics still missing (catches narrative ratio lines)
            # Only try patterns that are purely textual (compact label:value format)
            narrative_patterns: dict[str, tuple[list[str], bool]] = {
                "CET1 Ratio": ([
                    r"Ratio\s+CET\s*1\s*[:\-]\s*([\d,\.]+)%",
                    r"CET\s*1\s*[:\-]\s*([\d,\.]+)%",
                ], True),
                "Tier 1 Ratio": ([
                    r"Ratio\s+Tier\s*1\s*[:\-]\s*([\d,\.]+)%",
                ], True),
                "Leverage Ratio": ([
                    r"Ratio\s+de\s+levier\s*[:\-]\s*([\d,\.]+)%",
                    r"Leverage\s+ratio\s*[:\-]\s*([\d,\.]+)%",
                ], True),
                "LCR": ([
                    r"Ratio\s+LCR\s*[:\-]\s*([\d,\.]+)%",
                ], True),
                "NSFR": ([
                    r"Ratio\s+NSFR\s*[:\-]\s*([\d,\.]+)%",
                ], True),
            }
            for metric_name, (patterns, as_percent) in narrative_patterns.items():
                if metric_name in seen:
                    continue
                for pg_num, lines, _, pg_text in pages:
                    for pattern in patterns:
                        match = re.search(pattern, pg_text, flags=re.IGNORECASE)
                        if match:
                            value = _normalize_number(match.group(1), as_percent=as_percent)
                            if value is not None and _is_valid_metric_value(metric_name, value):
                                add_metric(metric_name, value, pg_num, " (narrative)")
                                break
                    if metric_name in seen:
                        break

        if ov1_text and ov1_page_number is not None:
            # Patterns: (english, french) — first match wins per metric
            ov1_patterns: dict[str, list[str]] = {
                "RWA Crédit": [
                    r"Credit risk \(excluding CCR\)\s+([\d\.,\s\u00a0]+)",
                    r"Risque de cr.{1,5}dit \(?hors CCR\)?\s+([\d\.,\s\u00a0]+)",
                ],
                "RWA CCR": [
                    r"Counterparty credit risk - CCR\s+([\d\.,\s\u00a0]+)",
                    r"Risque de cr.{1,5}dit de contrepartie\s*[-–]?\s*CCR\s+([\d\.,\s\u00a0]+)",
                ],
                "RWA Marché": [
                    r"Position, foreign exchange and commodities risks \(Market risk\)\s+([\d\.,\s\u00a0]+)",
                    r"Risque de march.{1,5}\s+([\d\.,\s\u00a0]+)",
                ],
                "RWA Opérationnel": [
                    r"Operational risk\s+([\d\.,\s\u00a0]+)",
                    r"Risque op.{1,10}rationnel\s+([\d\.,\s\u00a0]+)",
                ],
                "RWA Total": [
                    r"TOTAL\s+([\d\.,\s\u00a0]+)",
                ],
            }
            all_ov1_texts = [(pn, pg_text) for pn, *_, pg_text in ov1_pages]
            if not all_ov1_texts:
                all_ov1_texts = [(ov1_page_number, ov1_text)]
            for metric_name, patterns in ov1_patterns.items():
                if metric_name in seen:
                    continue
                for pg_num, pg_text in all_ov1_texts:
                    matched = False
                    for pattern in patterns:
                        match = re.search(pattern, pg_text, flags=re.IGNORECASE | re.DOTALL)
                        if match:
                            raw_val = match.group(1).strip()
                            value = _normalize_number(raw_val, as_million_eur=True)
                            if value is not None:
                                add_metric(metric_name, value, pg_num)
                                matched = True
                                break
                    if matched or metric_name in seen:
                        break

        missing_metrics = [metric_name for metric_name in _METRIC_ORDER if metric_name not in seen]
        if missing_metrics and not needs_ocr:
            for table_name, page_set in (("KM1", summary_pages), ("OV1", ov1_pages)):
                for page_number, *_ in page_set:
                    if page_number in ocr_used_pages:
                        continue
                    extracted = _extract_structured_metrics_from_page(
                        doc[page_number - 1],
                        page_number,
                        table_name,
                        set(missing_metrics) - seen,
                        use_ocr=True,
                    )
                    ocr_used_pages.add(page_number)
                    for metric_name, (value, source_page) in extracted.items():
                        add_metric(metric_name, value, source_page, " (OCR table fallback)")
            missing_metrics = [metric_name for metric_name in _METRIC_ORDER if metric_name not in seen]

        if missing_metrics and use_vlm and os.environ.get("EBA_DISABLE_VLM") != "1":
            vlm_page_numbers: list[int] = []
            for page_number, *_ in summary_pages + ov1_pages:
                if page_number not in vlm_page_numbers:
                    vlm_page_numbers.append(page_number)
            for page_number, _, _, normalized_text in pages:
                if _is_metric_candidate(normalized_text) and page_number not in vlm_page_numbers:
                    vlm_page_numbers.append(page_number)
            for page_number in range(1, min(doc.page_count, 12) + 1):
                if page_number not in vlm_page_numbers:
                    vlm_page_numbers.append(page_number)

            vlm_metrics = _extract_missing_metrics_with_vlm(doc, vlm_page_numbers, missing_metrics)
            for metric_name, (value, page_number) in vlm_metrics.items():
                add_metric(metric_name, value, page_number, " (Qwen2.5-VL)")

        set_cached_metrics(
            cache_identifier,
            metrics,
            metadata={
                "source_file": file_name,
                "needs_ocr": needs_ocr,
                "summary_pages": [page_number for page_number, *_ in summary_pages],
                "ov1_pages": [page_number for page_number, *_ in ov1_pages],
            },
        )
        return metrics
    finally:
        doc.close()
