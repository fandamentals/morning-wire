"""Red/green fixture for audit/lessons.md L8: commits_touching's `since_days`
window is anchored to actual wall-clock "now" (git `--since` always is), so
a check that walks commit pairs to find deletions/backdates will silently
stop reaching an old-enough commit pair as real time passes -- with ZERO
error or signal, just a quiet drop to 0 findings.

Unlike test_against_incident.py (which proves the fix against the REAL
cd206e3 incident, and therefore depends on today's date), this fixture
builds a synthetic, deliberately-old commit pair in an isolated temp repo so
the mechanism itself is provable independent of when this test happens to
run: a small (production-sized) since_days window must NOT reach a
deletion far in the past; the SAME check with a wide since_days_override
MUST catch it. This is the causal mechanism L8 is about, demonstrated
directly rather than inferred from one real commit's current age.

Run manually: python3 scripts/audit_checks/fixtures/test_l8_since_days_time_bomb.py
Exits non-zero if any assertion fails.
"""
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
OLD_DAYS_AGO = 60  # far outside any ~12/30-day production window, comfortably inside a wide override


def _git(args, cwd, env=None):
    return subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True, text=True, check=True,
                           timeout=30, env=env).stdout


def _commit_digest(repo, items, generated_at, when):
    (repo / "data").mkdir(parents=True, exist_ok=True)
    digest = {"generated_at": generated_at, "items": items, "source_health": [], "run_log": [], "radar": [],
              "top_of_mind": ""}
    (repo / "data" / "digest.json").write_text(json.dumps(digest), encoding="utf-8")
    ts = when.strftime("%Y-%m-%dT%H:%M:%S")
    env = {"GIT_AUTHOR_DATE": ts, "GIT_COMMITTER_DATE": ts,
           "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.com",
           "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.com"}
    import os
    full_env = {**os.environ, **env}
    _git(["add", "data/digest.json"], repo, env=full_env)
    _git(["commit", "-m", f"digest as of {ts}", "--allow-empty"], repo, env=full_env)


def _build_synthetic_repo(tmp):
    repo = Path(tmp) / "synthetic"
    repo.mkdir()
    _git(["init", "-q"], repo)
    _git(["checkout", "-q", "-b", "main"], repo)

    # Copy every sibling module, not just run.py: run.py imports fetch/heal/etc
    # at load time, so a partial copy fails with an unrelated ImportError that
    # would masquerade as (and be mistaken for) this fixture's own red case.
    shutil.copytree(REPO_ROOT / "scripts", repo / "scripts",
                     ignore=shutil.ignore_patterns("audit_checks", "templates", "__pycache__"))

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(days=OLD_DAYS_AGO)
    item = {
        "id": "fixture-item-1", "url": "https://example.com/fixture-item-1",
        "title": "Fixture item that gets illegally deleted", "type": "news", "jurisdiction": "GLOBAL",
        "priority": "normal", "status": "new", "summary": "x", "so_what": "x",
        "first_seen": old_time.isoformat(), "published": old_time.isoformat(), "date_source": "feed",
        "verification": {"level": "single_source", "sources": [{"name": "x", "url": "https://example.com/fixture-item-1"}]},
    }
    # Commit A: item present, generated_at = old_time (a normal daily commit from 60 days ago).
    _commit_digest(repo, [item], old_time.isoformat(), old_time)
    # Commit B: same day, a few hours later, item REMOVED while still well
    # inside DIGEST_ITEMS_MAX_AGE_DAYS (8) of commit A's generated_at --
    # exactly the L1 illegal-deletion shape, just far in the past.
    newer_time = old_time + timedelta(hours=6)
    _commit_digest(repo, [], newer_time.isoformat(), newer_time)
    return repo


def main():
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        repo = _build_synthetic_repo(tmp)
        sys.path.insert(0, str(REPO_ROOT / "scripts" / "audit_checks"))
        import check_deletion_diff as check

        # Small, production-sized window (bootstrap_cutoff=None so it isn't
        # excluded by BOOTSTRAP_CUTOFF too -- isolating since_days as the only
        # variable under test): must NOT reach a 60-day-old commit pair with
        # the default ~12-day window, so 0 findings here proves the BUG
        # mechanism, not a clean bill of health.
        findings_narrow = check.run(repo, bootstrap_cutoff=None)
        criticals_narrow = [f for f in findings_narrow if f["severity"] == "critical"]
        print(f"narrow (default) since_days: {len(findings_narrow)} finding(s), {len(criticals_narrow)} critical")
        if criticals_narrow:
            failures.append("expected the narrow/default window to MISS the 60-day-old deletion "
                             "(proving it would otherwise give false confidence) -- but it found it")

        # Wide override: must catch the exact same illegal deletion.
        findings_wide = check.run(repo, bootstrap_cutoff=None, since_days_override=OLD_DAYS_AGO + 5)
        criticals_wide = [f for f in findings_wide if f["severity"] == "critical"]
        print(f"wide (override={OLD_DAYS_AGO + 5}) since_days: {len(findings_wide)} finding(s), {len(criticals_wide)} critical")
        if not criticals_wide:
            failures.append("RED FIXTURE FAILED: even the wide since_days_override did not catch "
                             "the synthetic 60-day-old illegal deletion")
        elif not any(f["evidence"].get("id") == "fixture-item-1" for f in criticals_wide):
            failures.append(f"wide window found critical(s) but none reference fixture-item-1: {criticals_wide}")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll L8 since_days time-bomb assertions pass.")
    sys.exit(0)


if __name__ == "__main__":
    main()
