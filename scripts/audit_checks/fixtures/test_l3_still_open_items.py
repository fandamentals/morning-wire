"""Red/green fixtures for audit/lessons.md L3's remaining still-open items
(2026-07-07), closed out in a follow-up pass:

1. scripts/heal.py: `_validate_candidate` only demanded a topically relevant
   item for no-selector "page" candidates. A "feed" candidate, or a "page"
   candidate WITH a selector, validated on liveness alone -- a live-but-wrong
   feed (or a selector matching the wrong section of a page) could self-heal
   in undetected. Fixed by requiring relevance for every non-register kind.

2. scripts/verify.py's prompt-injection hardening (commit 8f92cf5) shipped
   without a red fixture, so per this file's own STATUS convention
   ("absorbed only once a check exists that actually fires on the bad case")
   it was never formally closed out. This proves the fix actually works:
   a model response that CLAIMS a confirming source not present in the
   call's own web_search_tool_result blocks must not be trusted as
   corroboration -- only a claim backed by a real search result may be.

(The third still-open L3 item, pinning GitHub Actions to commit SHAs, is
low-priority supply-chain hardening unrelated to either of the above and is
left open.)

Run manually: python3 scripts/audit_checks/fixtures/test_l3_still_open_items.py
Exits non-zero if any assertion fails.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS = REPO_ROOT / "scripts"


def test_heal_rejects_live_but_irrelevant_candidate():
    sys.path.insert(0, str(SCRIPTS))
    import heal

    irrelevant_items = [
        {"url": "https://example.com/a", "title": "Council approves new car park budget", "summary": ""},
        {"url": "https://example.com/b", "title": "Mayor opens community centre", "summary": ""},
    ]
    relevant_items = [
        {"url": "https://example.com/c", "title": "Regulator issues stablecoin licensing guidance", "summary": ""},
    ]
    source = {"name": "Fixture Source", "jurisdiction": "GLOBAL", "kind": "feed",
              "url": "https://example.com/old-feed.xml", "tier": "industry"}
    candidate = {"url": "https://example.com/new-feed.xml", "kind": "feed", "selector": None}

    orig_fetch_source = heal.fetch_source
    try:
        # RED: liveness alone (items returned) must not be enough for a
        # "feed" candidate -- this is exactly the still-open gap.
        heal.fetch_source = lambda synthetic, require_relevant=False: (irrelevant_items, None, len(irrelevant_items))
        if heal._validate_candidate(source, candidate):
            return False, "RED FIXTURE FAILED: live-but-irrelevant feed candidate was accepted"

        # GREEN: a candidate with at least one topically relevant item must
        # still validate -- the fix must not be so strict it rejects a good
        # replacement.
        heal.fetch_source = lambda synthetic, require_relevant=False: (relevant_items, None, len(relevant_items))
        if not heal._validate_candidate(source, candidate):
            return False, "GREEN FIXTURE FAILED: live-and-relevant feed candidate was rejected"
    finally:
        heal.fetch_source = orig_fetch_source

    # Same red case for a "page" candidate WITH a selector -- the exact
    # second half of the documented gap (only no-selector pages were checked).
    page_source = {"name": "Fixture Page Source", "jurisdiction": "GLOBAL", "kind": "page",
                   "url": "https://example.com/old-page", "tier": "industry", "selector": ".item"}
    page_candidate = {"url": "https://example.com/new-page", "kind": "page", "selector": ".item"}
    try:
        heal.fetch_source = lambda synthetic, require_relevant=False: (irrelevant_items, None, len(irrelevant_items))
        if heal._validate_candidate(page_source, page_candidate):
            return False, "RED FIXTURE FAILED: live-but-irrelevant selector-based page candidate was accepted"
    finally:
        heal.fetch_source = orig_fetch_source

    return True, None


class _FakeSearchResult:
    def __init__(self, url):
        self.url = url


class _FakeSearchToolResultBlock:
    type = "web_search_tool_result"

    def __init__(self, urls):
        self.content = [_FakeSearchResult(u) for u in urls]


class _FakeTextBlock:
    type = "text"

    def __init__(self, text):
        self.text = text


def _fake_response(claimed_json, actual_search_urls):
    return SimpleNamespace(content=[
        _FakeSearchToolResultBlock(actual_search_urls),
        _FakeTextBlock(claimed_json),
    ])


def test_verify_rejects_unconfirmed_claimed_source():
    sys.path.insert(0, str(SCRIPTS))
    import verify

    item = {"source": "Some Industry Blog", "url": "https://industry-blog.example/post",
            "title": "Regulator to fine exchange, sources claim", "summary": "unverified claim",
            "tier": "industry"}

    class _FakeMessages:
        def __init__(self, response):
            self._response = response

        def create(self, **kwargs):
            return self._response

    class _FakeClient:
        def __init__(self, response):
            self.messages = _FakeMessages(response)

    orig_get_client = verify.get_client
    try:
        # RED: the model CLAIMS a confirming Reuters URL, but that URL never
        # actually appears among this call's own web_search_tool_result
        # blocks -- exactly what a prompt injection embedded in title/summary
        # could try to fabricate. Must be rejected.
        claimed_but_not_searched = (
            '{"confirmed": true, "source": {"name": "Reuters", '
            '"url": "https://reuters.com/fake-not-actually-searched"}}'
        )
        response = _fake_response(
            claimed_but_not_searched,
            actual_search_urls=["https://reuters.com/some-other-real-result"],
        )
        verify.get_client = lambda: _FakeClient(response)
        verification, _ = verify.verify_item(item, calls_used=0)
        if verification["level"] != "single_source":
            return False, (
                "RED FIXTURE FAILED: corroboration accepted on an unverified "
                f"claimed URL: {verification}")

        # GREEN: the model claims a confirming URL that DOES appear among the
        # actual search results for this call -- must be accepted.
        claimed_url = "https://reuters.com/some-other-real-result"
        confirmed_and_searched = (
            f'{{"confirmed": true, "source": {{"name": "Reuters", "url": "{claimed_url}"}}}}'
        )
        response = _fake_response(confirmed_and_searched, actual_search_urls=[claimed_url])
        verify.get_client = lambda: _FakeClient(response)
        verification, _ = verify.verify_item(item, calls_used=0)
        if verification["level"] != "corroborated":
            return False, (
                "GREEN FIXTURE FAILED: a genuinely search-backed confirming "
                f"source was not accepted: {verification}")
    finally:
        verify.get_client = orig_get_client

    return True, None


def main():
    tests = [
        test_heal_rejects_live_but_irrelevant_candidate,
        test_verify_rejects_unconfirmed_claimed_source,
    ]
    failures = []
    for t in tests:
        ok, msg = t()
        print(f"{t.__name__}: {'PASS' if ok else 'FAIL'}")
        if not ok:
            failures.append(msg)
    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f" - {f}")
        return 1
    print("\nAll assertions passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
