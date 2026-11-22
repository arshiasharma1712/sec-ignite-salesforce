"""Local ML anomaly detection and deterministic data-quality checks.

Run after normalization and before routing. No external API required.
Call flag_anomalies(normalized_leads), then split_for_review(flagged_leads).
Only route the first returned list. Merge the second into Manager Review.

The model detects unusual profiles; explicit data-quality flags are rules,
not ML predictions. Inputs are not modified.
"""

import math

import numpy as np
from sklearn.ensemble import IsolationForest

REASON = "Suspicious data (ML anomaly check)"
CONTAMINATION = 0.01
HUGE_SIZE = 1_000_000
TINY_SIZE = 0
RANDOM_STATE = 0

SEND_TO_REVIEW = {
    "model": False,
    "huge_size": True,
    "tiny_size": False,
    "fused_region": True,
    "duplicate_id": True,
    "vip_unknown": True,
}

QUALITY_FLAGS = {
    "region_fused",
    "duplicate_or_missing_id",
    "vip_unknown",
    "size_missing",
    "size_invalid",
    "size_interpreted",
    "size_outlier",
}


def _size(lead):
    value = lead.get("company_size")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        if math.isfinite(number) and number >= 0:
            return number
    return None


def _features(lead, typical_log_size):
    size = _size(lead)
    unknown = sum(
        lead.get(field) is None
        or str(lead.get(field)).strip().lower() in ("", "unknown", "n/a")
        for field in ("region", "language", "industry", "recent_activity")
    ) + int(size is None)
    log_size = math.log1p(min(size, HUGE_SIZE)) if size is not None else typical_log_size
    quality = sum(flag in QUALITY_FLAGS for flag in (lead.get("flags") or []))
    return [log_size, float(unknown), float(quality)]


def _descriptions(lead, keys):
    size = _size(lead)
    descriptions = []
    if "model" in keys:
        descriptions.append("Unusual lead profile detected by Isolation Forest (ML)")
    if "huge_size" in keys:
        descriptions.append(f"Unrealistic company size: {size:,.0f} employees")
    if "tiny_size" in keys:
        descriptions.append(f"Unusually small company size: {size:,.0f} employees (verify)")
    
    if "fused_region" in keys:
        original = lead.get("region_original") or lead.get("region", "Unknown")
        descriptions.append( f"Ambiguous region: multiple regions detected in one field " f"({original}); verify correct region")
    if "duplicate_id" in keys:
        descriptions.append("Duplicate or missing Lead ID: verify identity before assignment")
    if "vip_unknown" in keys:
        descriptions.append("VIP status unknown: verify referral status before assignment")
    return descriptions


def flag_anomalies(leads):
    """Return copies with anomaly_flag, anomaly_review and anomaly_reasons."""
    out = [dict(lead) for lead in leads]
    keys = [set() for _ in out]

    if len(out) >= 50:
        known = [math.log1p(min(s, HUGE_SIZE)) for lead in out if (s := _size(lead)) is not None]
        typical = float(np.median(known)) if known else 0.0
        features = np.asarray([_features(lead, typical) for lead in out], dtype=float)
        model = IsolationForest(
            n_estimators=200,
            contamination=CONTAMINATION,
            random_state=RANDOM_STATE,
        )
        predictions = model.fit_predict(features)
        for index, prediction in enumerate(predictions):
            if prediction == -1:
                keys[index].add("model")

    for index, lead in enumerate(out):
        size = _size(lead)
        if size is not None and size > HUGE_SIZE:
            keys[index].add("huge_size")
        elif size is not None and size <= TINY_SIZE:
            keys[index].add("tiny_size")

        flags = set(lead.get("flags") or [])
        if "region_fused" in flags:
            keys[index].add("fused_region")
        if "duplicate_or_missing_id" in flags:
            keys[index].add("duplicate_id")
        if "vip_unknown" in flags:
            keys[index].add("vip_unknown")

    for lead, reasons in zip(out, keys):
        lead["anomaly_reasons"] = _descriptions(lead, reasons)
        lead["anomaly_flag"] = bool(reasons)
        lead["anomaly_review"] = any(SEND_TO_REVIEW[reason] for reason in reasons)
    return out


def split_for_review(leads):
    """Return (safe_to_route, review_rows), preserving detailed reasons."""
    clean = [dict(lead) for lead in leads if not lead.get("anomaly_review")]
    suspicious = []
    for lead in leads:
        if not lead.get("anomaly_review"):
            continue
        details = "; ".join(lead.get("anomaly_reasons") or [])
        suspicious.append({
            **lead,
            "rep_id": None,
            "rep_name": None,
            "assignment_status": "Manager Review",
            "reason": f"{REASON}: {details}" if details else REASON,
        })
    return clean, suspicious
