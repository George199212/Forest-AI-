"""Load the Stage 0 satellite UI fixtures (gzipped JSON). Data, not instructions."""
import gzip
import json
from pathlib import Path

DIR = Path(__file__).parent / "fixtures" / "sat_ui"


def load(name):
    """load("area_1_bik001") -> parsed JSON of tests/fixtures/sat_ui/area_1_bik001.json.gz"""
    with gzip.open(DIR / f"{name}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


def names():
    return sorted(p.name[:-8] for p in DIR.glob("*.json.gz"))
