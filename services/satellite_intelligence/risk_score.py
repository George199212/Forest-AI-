"""
Satellite monitoring score — deliberately separate from api.py's calc_risk_score().

Relationship between the two scores (read this before changing either):

  calc_risk_score(sector)            — OPERATIONAL risk. Sums confirmed incidents
                                        already in the `risks` table (HIGH/MEDIUM
                                        counts), rejected GPS check-ins, and timber
                                        volume mismatches. Feeds the existing
                                        dashboard KPIs and AI Inspector. Bands:
                                        LOW/MEDIUM/HIGH. NOT modified by this file.

  satellite_monitoring_score(sector) — SATELLITE-SPECIFIC monitoring priority,
                                        computed here. Answers "how urgently does
                                        this sector need a satellite look right
                                        now" — a different question from "how much
                                        operational risk has already been confirmed
                                        here". Bands: NORMAL/WATCH/MEDIUM/HIGH/
                                        CRITICAL (finer-grained on purpose, because
                                        it drives a 4-tier cost escalation decision,
                                        not just a 3-color dashboard chip).

They are NOT merged: the two numbers can legitimately disagree (a sector can be
satellite-CRITICAL — e.g. a storm just hit it — while calc_risk_score is still LOW
because no confirmed incident exists yet; conversely a sector can carry a high
calc_risk_score from an old resolved timber mismatch while satellite monitoring
stays NORMAL). One does feed the other in one direction only: this score's DB
inputs below (timber anomalies, rejected GPS, prior HIGH risks) reuse the same
underlying facts calc_risk_score reads, so the two don't silently diverge on facts
— they diverge on WHICH facts matter for which question, and on the anomaly/event
signals below that calc_risk_score has no notion of at all. Per the project's
existing convention of showing "Расчётный риск по операции" and "Риск по
инцидентам" side by side with distinct labels, the UI must show these two scores
side by side too, distinctly labeled — never merged into one number.
"""

import sqlite3
import os
from datetime import datetime

DB_NAME = os.environ.get("DB_PATH", "data/forest_ai.db")

BAND_NORMAL = "NORMAL"
BAND_WATCH = "WATCH"
BAND_MEDIUM = "MEDIUM"
BAND_HIGH = "HIGH"
BAND_CRITICAL = "CRITICAL"

BAND_COLORS = {
    BAND_NORMAL: "green",
    BAND_WATCH: "green",
    BAND_MEDIUM: "yellow",
    BAND_HIGH: "red",
    BAND_CRITICAL: "red",
}


def _band_for(score: float) -> str:
    if score >= 85:
        return BAND_CRITICAL
    if score >= 70:
        return BAND_HIGH
    if score >= 50:
        return BAND_MEDIUM
    if score >= 30:
        return BAND_WATCH
    return BAND_NORMAL


def _n(sql, params=()):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute(sql, params)
    row = cur.fetchone()
    conn.close()
    return (row[0] if row else 0) or 0


def _prior_score(sector: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT score FROM sector_satellite_scores WHERE sector=? ORDER BY computed_at DESC, id DESC LIMIT 1",
        (sector,)
    )
    row = cur.fetchone()
    conn.close()
    return row["score"] if row else None


def compute_satellite_monitoring_score(sector_name: str, signals: dict = None) -> dict:
    """
    Compute the 0-100 satellite monitoring score for one sector.

    `signals` carries event-driven / detection-driven inputs that this system
    doesn't yet detect automatically end-to-end (no live change-detection
    pipeline exists) — event trigger functions (events.py, stage c) and the demo
    seed populate these explicitly; a real production caller with no specific
    signal to report can omit `signals` entirely and still gets a meaningful
    score from the DB-derived inputs below.

    Recognized signals (all optional):
      ndvi_change_pct (float, negative = vegetation loss)
      sar_change_detected (bool)
      new_road_detected (bool)
      suspected_clear_cut (bool)
      machinery_detected (bool)          — anomalous/unexpected presence only;
                                            routine operator activity is not a signal
      storm_event (bool)
      fire_event (bool)
      contractor_activity_outside_boundary (bool)
      cloud_cover_pct (float, 0-100)
      days_since_last_image (int)
      ai_detection_confidence (float, 0-1, default 1.0)
      affected_area_ha (float)           — carried through to the justification string, not scored

    Returns a dict with score/band/color plus the full inputs breakdown (also
    what gets persisted to sector_satellite_scores.inputs_json for the "previous
    risk history" input on the next call, and shown in the UI for transparency).
    """
    signals = signals or {}

    ndvi_change_pct = signals.get("ndvi_change_pct")
    sar_change_detected = bool(signals.get("sar_change_detected"))
    new_road_detected = bool(signals.get("new_road_detected"))
    suspected_clear_cut = bool(signals.get("suspected_clear_cut"))
    machinery_detected = bool(signals.get("machinery_detected"))
    storm_event = bool(signals.get("storm_event"))
    fire_event = bool(signals.get("fire_event"))
    contractor_outside = bool(signals.get("contractor_activity_outside_boundary"))
    cloud_cover_pct = signals.get("cloud_cover_pct")
    days_since_last_image = signals.get("days_since_last_image")
    ai_confidence = signals.get("ai_detection_confidence")
    ai_confidence = 1.0 if ai_confidence is None else max(0.0, min(1.0, ai_confidence))

    # Optical-only signals (NDVI loss, suspected clear-cut) lose confirmation
    # power under heavy cloud cover unless SAR corroborates them — a cloudy
    # "vegetation loss" reading is less trustworthy than a clear one. This is
    # cloud cover's role in the score: it discounts unconfirmed optical
    # evidence, it does not add points of its own.
    optical_pts = 0.0
    if ndvi_change_pct is not None:
        if ndvi_change_pct <= -30:
            optical_pts += 35
        elif ndvi_change_pct <= -15:
            optical_pts += 20
        elif ndvi_change_pct <= -5:
            optical_pts += 8
    if suspected_clear_cut:
        optical_pts += 30
    if cloud_cover_pct is not None and cloud_cover_pct > 70 and not sar_change_detected:
        optical_pts *= 0.7

    other_pts = 0.0
    if sar_change_detected:
        other_pts += 15
    if new_road_detected:
        other_pts += 25
    if machinery_detected:
        other_pts += 12
    if storm_event:
        other_pts += 20
    if fire_event:
        other_pts += 35
    if contractor_outside:
        other_pts += 15

    # AI confidence tempers the WHOLE anomaly signal, optical or not — per
    # CODING_RULES.md, an AI detection never gets to push a score straight to
    # CRITICAL on its own; a low-confidence detection contributes proportionally
    # less, and a human still has to act on the resulting incident either way
    # (see decision_engine.py / inspector_bridge.py — nothing here auto-confirms
    # a finding).
    anomaly_pts = (optical_pts + other_pts) * ai_confidence

    # DB-derived inputs — reuse the exact facts calc_risk_score() also reads,
    # so the two scores never silently diverge on the underlying data, only on
    # how they weigh it (see module docstring).
    timber_anomaly_count = _n(
        "SELECT COUNT(*) FROM timber_movements WHERE sector=? AND status IN ('MISSING_VOLUME','OVER_VOLUME')",
        (sector_name,)
    )
    rejected_gps_count = _n(
        "SELECT COUNT(*) FROM work_sessions WHERE sector=? AND approved='NO'", (sector_name,)
    )
    prior_high_risk_count = _n(
        "SELECT COUNT(*) FROM risks WHERE sector=? AND risk_level='HIGH'", (sector_name,)
    )
    db_pts = min(20, timber_anomaly_count * 10) + min(16, rejected_gps_count * 8) + min(18, prior_high_risk_count * 6)

    # Stale monitoring is itself a small risk factor — the longer since a
    # useful image, the less confidence we have that NOTHING happened.
    staleness_pts = 0.0
    if days_since_last_image is not None:
        if days_since_last_image > 30:
            staleness_pts = 18
        elif days_since_last_image > 14:
            staleness_pts = 10

    # Persistence: an already-elevated score for this sector carries forward a
    # small amount — this sector's own satellite-score history IS its
    # "previous risk history for the sector" input, distinct from
    # calc_risk_score's operational history above.
    prior_score = _prior_score(sector_name)
    persistence_pts = 5.0 if (prior_score is not None and prior_score >= 50) else 0.0

    score = round(min(100.0, anomaly_pts + db_pts + staleness_pts + persistence_pts))
    band = _band_for(score)

    return {
        "score": score,
        "band": band,
        "color": BAND_COLORS[band],
        "inputs": {
            "ndvi_change_pct": ndvi_change_pct,
            "sar_change_detected": sar_change_detected,
            "new_road_detected": new_road_detected,
            "suspected_clear_cut": suspected_clear_cut,
            "machinery_detected": machinery_detected,
            "storm_event": storm_event,
            "fire_event": fire_event,
            "contractor_activity_outside_boundary": contractor_outside,
            "cloud_cover_pct": cloud_cover_pct,
            "days_since_last_image": days_since_last_image,
            "ai_detection_confidence": ai_confidence,
            "affected_area_ha": signals.get("affected_area_ha"),
            "timber_anomaly_count": timber_anomaly_count,
            "rejected_gps_count": rejected_gps_count,
            "prior_high_risk_count": prior_high_risk_count,
            "prior_satellite_score": prior_score,
        },
        "computed_at": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
