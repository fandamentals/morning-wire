"""SOFT, but with a HARD-flavoured guardrail baked in. A jurisdiction with
zero live official sources is a structural coverage hole -- distinct from a
jurisdiction merely having no crypto news today (normal; MAS routinely
contributes 0 relevant items while still being reachable). This check
judges LIVENESS (source_health status), never item volume, so it can't be
fooled by a quiet news day into crying wolf, and can't be silenced by a
source quietly having nothing to report.

A jurisdiction with zero official sources CONFIGURED AT ALL (as opposed to
configured-then-gone-dead) is a related but distinct hole: a one-time data-
completeness gap rather than a liveness regression, so it is reported at
`info` (not `warn`) and won't recur once a human adds a source -- unlike the
all-dead case, which can recur every run until the underlying sources are
fixed. Found live on this project 2026-07-24 (weekly audit deep-dive): UK
had been a first-class jurisdiction in the enum since 15b283d but had zero
sources of any kind configured, so this branch never fired for it -- only
manual review caught it. This is that manual finding turned into a standing
check, so the next such gap (for any jurisdiction) doesn't need a human to
rediscover it from scratch.

Guardrail: official-tier and register sources, and any source that is its
jurisdiction's ONLY official source, may never appear in
audit/baseline.json's human-maintained accepted_dead list. That list exists
for known, permanent, non-fixable blocks (FATF's Cloudflare 403) on
industry-tier or redundantly-covered sources only -- this check verifies
the humans maintaining that file haven't violated their own policy.
"""
import json

from base import finding, could_not_run

CHECK_ID = "jurisdiction_coverage"
MODE = "soft"

JURISDICTIONS = ["HK", "CN", "US", "EU", "SG", "UK"]  # GLOBAL excluded: no single-jurisdiction bar applies


def run(repo_root):
    try:
        sources = json.loads((repo_root / "data" / "sources.json").read_text(encoding="utf-8"))
        digest = json.loads((repo_root / "data" / "digest.json").read_text(encoding="utf-8"))
    except Exception as exc:
        return [could_not_run(CHECK_ID, f"could not read data/sources.json or digest.json: {exc}")]

    health_by_name = {h["name"]: h for h in digest.get("source_health", [])}
    findings = []

    for j in JURISDICTIONS:
        official = [s for s in sources if s["jurisdiction"] == j and s.get("tier") == "official"]
        if not official:
            findings.append(finding(
                CHECK_ID, "info",
                f"{j}: no official source configured at all",
                f"{j} is a first-class jurisdiction (see JURISDICTIONS) but data/sources.json has "
                f"zero official-tier sources for it -- a data-completeness gap, not a liveness "
                f"regression. Propose one on a branch + PR per the audit playbook's Phase 5, "
                f"source-coverage deep-dive.",
                {"jurisdiction": j},
            ))
            continue  # nothing alive to check liveness of
        alive = [s for s in official
                 if health_by_name.get(s["name"], {}).get("status") not in ("dead",)]
        if not alive:
            findings.append(finding(
                CHECK_ID, "warn",
                f"{j}: every official source shows status=dead",
                f"{len(official)} official source(s) configured for {j}, all currently reported dead: "
                f"{[s['name'] for s in official]}. This jurisdiction has no live official coverage.",
                {"jurisdiction": j, "dead_sources": [s["name"] for s in official]},
            ))

    # Guardrail check on the human-maintained accepted_dead list.
    baseline_path = repo_root / "audit" / "baseline.json"
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return findings + [finding(CHECK_ID, "warn", "audit/baseline.json is not valid JSON", str(exc), {})]

        source_by_name = {s["name"]: s for s in sources}
        for entry in baseline.get("accepted_dead", []):
            name = entry.get("source")
            s = source_by_name.get(name)
            if not s:
                continue
            same_juris_official = [x for x in sources if x["jurisdiction"] == s["jurisdiction"] and x.get("tier") == "official"]
            if s.get("tier") == "official" or s.get("kind") == "register" or len(same_juris_official) <= 1:
                findings.append(finding(
                    CHECK_ID, "critical",
                    f"accepted_dead policy violation: '{name}'",
                    f"audit/baseline.json accepts '{name}' as a known-dead exception, but it is "
                    f"tier={s.get('tier')} kind={s.get('kind')} and is one of only "
                    f"{len(same_juris_official)} official source(s) for {s['jurisdiction']}. "
                    "Official/register sources and a jurisdiction's sole official source may never "
                    "be baselined dead -- this entry should be removed from accepted_dead.",
                    {"source": name, "entry": entry},
                ))
    return findings
