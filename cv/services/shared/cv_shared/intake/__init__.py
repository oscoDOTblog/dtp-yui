"""Job intake: normalize, fingerprint, location gate, upsert, Gmail source."""

from __future__ import annotations

__all__ = [
    "assess_location",
    "build_fingerprints",
    "load_location_config",
    "normalize_raw_job",
    "normalize_text",
    "run_ingest",
    "upsert_normalized_job",
]


def __getattr__(name: str):
    if name in ("assess_location", "load_location_config"):
        from .location import assess_location, load_location_config

        return {
            "assess_location": assess_location,
            "load_location_config": load_location_config,
        }[name]
    if name in ("build_fingerprints", "normalize_text"):
        from .fingerprints import build_fingerprints, normalize_text

        return {
            "build_fingerprints": build_fingerprints,
            "normalize_text": normalize_text,
        }[name]
    if name == "normalize_raw_job":
        from .normalize import normalize_raw_job

        return normalize_raw_job
    if name == "upsert_normalized_job":
        from .upsert import upsert_normalized_job

        return upsert_normalized_job
    if name == "run_ingest":
        from .pipeline import run_ingest

        return run_ingest
    raise AttributeError(name)
