"""Red/green fixture for check_jurisdiction_coverage.py's zero-official-source
detection, added 2026-07-24 during the weekly audit's source-coverage
deep-dive after UK was found to have zero configured sources despite being a
first-class jurisdiction since 15b283d -- the check's own prior code
documented (in a comment) that it deliberately skipped this exact case
("a design gap, not this check's job"), so it never fired live for UK.

Run manually: python3 scripts/audit_checks/fixtures/test_jurisdiction_coverage_zero_source.py
Exits non-zero if any assertion fails.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _write(root, sources, digest):
    (root / "data").mkdir(parents=True, exist_ok=True)
    (root / "data" / "sources.json").write_text(json.dumps(sources), encoding="utf-8")
    (root / "data" / "digest.json").write_text(json.dumps(digest), encoding="utf-8")


def _run_check(root):
    sys.path.insert(0, str(REPO_ROOT / "scripts" / "audit_checks"))
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    import importlib
    import check_jurisdiction_coverage as check
    importlib.reload(check)  # in case a prior test in the same process cached an older sources.json path
    return check.run(root)


def test_zero_source_jurisdiction_is_flagged_info():
    """RED case (pre-fix): a jurisdiction with no official source at all
    used to produce no finding whatsoever. Must now produce exactly one
    `info`-severity finding naming that jurisdiction."""
    sources = [
        {"name": "Some HK Regulator", "jurisdiction": "HK", "tier": "official"},
        # UK: intentionally absent -- this is the case under test
    ]
    digest = {"source_health": [{"name": "Some HK Regulator", "status": "ok"}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, sources, digest)
        findings = _run_check(root)
    uk_findings = [f for f in findings if f["evidence"].get("jurisdiction") == "UK"]
    assert len(uk_findings) == 1, f"expected exactly one UK finding, got {uk_findings}"
    assert uk_findings[0]["severity"] == "info", uk_findings[0]
    assert "no official source configured" in uk_findings[0]["title"]
    print("PASS: zero-source jurisdiction (UK) correctly flagged at info severity")


def test_covered_jurisdiction_is_not_flagged():
    """GREEN case: a jurisdiction with at least one live official source
    must not trip the new branch (proves no over-firing / false positive)."""
    sources = [
        {"name": "Financial Conduct Authority — News", "jurisdiction": "UK", "tier": "official"},
    ]
    digest = {"source_health": [{"name": "Financial Conduct Authority — News", "status": "ok"}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, sources, digest)
        findings = _run_check(root)
    uk_findings = [f for f in findings if f["evidence"].get("jurisdiction") == "UK"]
    assert not uk_findings, f"expected no UK finding once a source exists, got {uk_findings}"
    print("PASS: jurisdiction with a live official source is not flagged")


def test_all_dead_still_flagged_warn_not_info():
    """GREEN case: the pre-existing all-dead branch (a DIFFERENT, more
    severe case -- sources exist but every one is dead) must still fire at
    `warn`, proving the new zero-source branch didn't swallow or downgrade
    the existing liveness check."""
    sources = [
        {"name": "Some EU Regulator", "jurisdiction": "EU", "tier": "official"},
    ]
    digest = {"source_health": [{"name": "Some EU Regulator", "status": "dead"}]}
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write(root, sources, digest)
        findings = _run_check(root)
    eu_findings = [f for f in findings if f["evidence"].get("jurisdiction") == "EU"]
    assert len(eu_findings) == 1, f"expected exactly one EU finding, got {eu_findings}"
    assert eu_findings[0]["severity"] == "warn", eu_findings[0]
    assert "all currently reported dead" in eu_findings[0]["detail"]
    print("PASS: all-dead jurisdiction still correctly flagged at warn severity (unweakened)")


def test_live_repo_uk_gap_is_closed():
    """Sanity check against the REAL repo data (not a synthetic fixture):
    after this run's Phase 5 fix (adding FCA + Bank of England as UK
    sources), the live data/sources.json must no longer trip the
    zero-source branch for UK. This is the one assertion that would fail if
    the accompanying data/sources.json edit in this same PR were reverted
    without reverting this test."""
    findings = _run_check(REPO_ROOT)
    uk_findings = [f for f in findings if f["evidence"].get("jurisdiction") == "UK"
                   and "no official source configured" in f["title"]]
    assert not uk_findings, f"live repo still has a UK zero-source gap: {uk_findings}"
    print("PASS: live repo's UK gap is closed (FCA + Bank of England now configured)")


if __name__ == "__main__":
    test_zero_source_jurisdiction_is_flagged_info()
    test_covered_jurisdiction_is_not_flagged()
    test_all_dead_still_flagged_warn_not_info()
    test_live_repo_uk_gap_is_closed()
    print("\nAll tests passed.")
