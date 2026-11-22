from src.ml_anomaly import flag_anomalies, split_for_review, REASON


def lead(i, size, unknown=0):
    fields = ["region", "language", "industry", "recent_activity"]
    row = {"record_id": f"L-{i}", "company_size": size, "flags": []}
    for n, field in enumerate(fields):
        row[field] = "Unknown" if n < unknown else "x"
    return row


def test_flags_and_split():
    leads = [lead(i, 500 + i * 7) for i in range(300)]
    leads += [lead(900, 10_000_000_000), lead(901, 2)]
    before = [dict(item) for item in leads]
    out = flag_anomalies(leads)
    assert leads == before
    by = {item["record_id"]: item for item in out}
    assert by["L-900"]["anomaly_flag"]
    assert by["L-901"]["anomaly_flag"]
    assert not by["L-150"]["anomaly_flag"]
    clean, bad = split_for_review(out)
    assert len(clean) + len(bad) == len(out)
    assert all(item["reason"].startswith(REASON) and item["rep_id"] is None for item in bad)
    assert any("10,000,000,000" in item["reason"] for item in bad)


def test_many_unknown_fields_is_flagged():
    leads = [lead(i, 500 + i * 7) for i in range(300)]
    leads.append(lead(950, None, unknown=4))
    out = flag_anomalies(leads)
    assert out[-1]["anomaly_flag"]


def test_all_three_quality_flags_go_to_review_with_specific_reasons():
    leads = [lead(i, 500 + i * 7) for i in range(300)]
    cases = [
        (960, "region_fused", "Ambiguous region"),
        (961, "duplicate_or_missing_id", "Duplicate or missing Lead ID"),
        (962, "vip_unknown", "VIP status unknown"),
    ]
    for number, flag, _ in cases:
        item = lead(number, 800)
        item["flags"] = [flag]
        leads.append(item)
    out = flag_anomalies(leads)
    by = {item["record_id"]: item for item in out}
    clean, bad = split_for_review(out)
    reviewed = {item["record_id"]: item for item in bad}
    for number, _, text in cases:
        key = f"L-{number}"
        assert by[key]["anomaly_flag"]
        assert by[key]["anomaly_review"]
        assert key in reviewed
        assert text in reviewed[key]["reason"]
        assert key not in {item["record_id"] for item in clean}
