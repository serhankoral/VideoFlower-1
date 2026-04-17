from candidate_store import CandidateStore
from validator_pipeline import ValidationPolicy, filter_candidates


def test_candidate_store_merges_headers_and_sources():
    store = CandidateStore()

    store.add_or_update(
        "https://cdn.example.com/master.m3u8",
        "request",
        headers={"Referer": "https://page.example.com"},
    )
    store.add_or_update(
        "https://cdn.example.com/master.m3u8",
        "response",
        headers={"Content-Length": "2048"},
        content_length=2048,
    )

    items = store.all()
    assert len(items) == 1
    candidate = items[0]
    assert "request" in candidate.sources
    assert "response" in candidate.sources
    assert candidate.headers.get("referer") == "https://page.example.com"
    assert candidate.content_length == 2048


def test_validator_rejects_blacklisted_urls():
    store = CandidateStore()
    store.add_or_update("https://ads.example.com/preroll.m3u8", "response")

    policy = ValidationPolicy(blacklist_entries=("ads.example.com",))
    accepted, rejected = filter_candidates(store.all(), policy)

    assert not accepted
    assert "https://ads.example.com/preroll.m3u8" in rejected


def test_validator_rejects_small_content_length_when_configured():
    store = CandidateStore()
    store.add_or_update(
        "https://cdn.example.com/video.mp4",
        "response",
        content_length=512 * 1024,
    )

    policy = ValidationPolicy(min_content_length_mb=2)
    accepted, rejected = filter_candidates(store.all(), policy)

    assert not accepted
    assert rejected["https://cdn.example.com/video.mp4"] == "content-length-too-small"
