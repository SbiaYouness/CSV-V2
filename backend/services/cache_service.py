import os
import json
import hashlib
from pathlib import Path

# Bump this string whenever extraction logic changes.
# Any cache entry written with a different version will be ignored.
PARSER_VERSION = "31"

CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _get_cache_path(identifier: str) -> Path:
    key = f"{PARSER_VERSION}:{identifier}"
    safe_name = hashlib.md5(key.encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{safe_name}.json"


def get_cached_metrics(identifier: str) -> list[dict] | None:
    """Return completed, non-empty metric extractions for the current parser version."""
    cache_path = _get_cache_path(identifier)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                if payload.get("parser_version") != PARSER_VERSION:
                    return None
                if payload.get("status") != "complete":
                    return None
                metrics = payload.get("metrics")
                if isinstance(metrics, list) and metrics:
                    return metrics
                return None

            # Accept same-version bare lists only as a local development fallback.
            if isinstance(payload, list):
                return payload or None
        except Exception:
            pass
    return None


def set_cached_metrics(identifier: str, metrics: list[dict], metadata: dict | None = None) -> None:
    """Persist successful metric extractions, keyed by parser version + identifier."""
    if not metrics:
        return

    cache_path = _get_cache_path(identifier)
    payload = {
        "parser_version": PARSER_VERSION,
        "status": "complete",
        "metric_count": len(metrics),
        "metrics": metrics,
    }
    if metadata:
        payload["metadata"] = metadata
    try:
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Cache write failed for {identifier}: {e}")
