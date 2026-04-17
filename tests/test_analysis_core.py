import json

from analysis_core import (
    ATOM_PROFILE,
    DOODSTREAM_PROFILE,
    GENERIC_PROFILE,
    ProviderProfile,
    create_provider_profile,
    detect_provider_profile,
    get_allowed_host_hints,
    is_allowed_url,
    is_m3u8,
    is_playlist_url,
    is_skip,
    is_stream_url,
    is_youtube,
    normalize_url,
    register_provider_profile,
    reload_provider_profiles,
    score_url,
    set_allowed_host_hints,
)


def test_detect_provider_profile_doodstream():
    profile = detect_provider_profile("https://doodstream.com/e/abcd1234")
    assert profile.name == DOODSTREAM_PROFILE.name


def test_detect_provider_profile_generic_when_unknown_host():
    profile = detect_provider_profile("https://example.org/video-page")
    assert profile.name == GENERIC_PROFILE.name


def test_detect_provider_profile_close():
    profile = detect_provider_profile("https://closeload.com/e/stream123")
    assert profile.name == "close"


def test_detect_provider_profile_rapidrame():
    profile = detect_provider_profile("https://rapidrame.com/embed/stream123")
    assert profile.name == "rapidrame"


def test_detect_provider_profile_drakkar():
    profile = detect_provider_profile("https://video.drakkarstream.net/embed/stream123")
    assert profile.name == "drakkar"


def test_detect_provider_profile_vidrame():
    profile = detect_provider_profile("https://vidrame.com/v/stream123")
    assert profile.name == "vidrame"


def test_is_youtube_true_for_youtu_be():
    assert is_youtube("https://youtu.be/abc123") is True


def test_is_youtube_false_for_non_youtube():
    assert is_youtube("https://vimeo.com/123") is False


def test_is_playlist_url_detects_list_query_param():
    assert is_playlist_url("https://www.youtube.com/watch?v=abc&list=PL123") is True


def test_normalize_url_protocol_relative():
    assert normalize_url("//cdn.site/video.m3u8", "https://host/page") == "https://cdn.site/video.m3u8"


def test_normalize_url_relative_path():
    assert normalize_url("/media/master.m3u8", "https://host/page") == "https://host/media/master.m3u8"


def test_stream_detection_filters_tracking_domains():
    blocked = "https://google-analytics.com/collect?x=.m3u8"
    assert is_skip(blocked) is True
    assert is_stream_url(blocked) is False


def test_is_m3u8_detects_manifest_keyword():
    assert is_m3u8("https://site/cdn/manifest?token=1") is True


def test_score_prefers_master_m3u8_over_mp4_for_atom_profile():
    m3u8_score = score_url("https://cdn.site/master.m3u8", ATOM_PROFILE)
    mp4_score = score_url("https://cdn.site/video-720.mp4", ATOM_PROFILE)
    assert m3u8_score > mp4_score


def test_register_provider_profile_adds_runtime_profile():
    register_provider_profile(
        ProviderProfile(
            name="samplehost",
            host_hints=("samplehost.com",),
            play_selectors=[".sample-play"],
            popup_close_selectors=[".sample-close"],
            score_boost_patterns=("samplehost", ".m3u8"),
        )
    )

    profile = detect_provider_profile("https://samplehost.com/embed/abc")
    assert profile.name == "samplehost"

    reload_provider_profiles()


def test_reload_provider_profiles_loads_external_json(tmp_path):
    config_path = tmp_path / "providers.json"
    config_path.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "name": "newsource",
                        "host_hints": ["newsource.com", "cdn.newsource.com"],
                        "play_selectors": [".newsource-play"],
                        "popup_close_selectors": [".newsource-close"],
                        "score_boost_patterns": ["newsource", ".m3u8"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    loaded = reload_provider_profiles(str(config_path))
    profile = detect_provider_profile("https://cdn.newsource.com/embed/abc")

    assert loaded == 1
    assert profile.name == "newsource"

    reload_provider_profiles()


def test_create_provider_profile_uses_generic_selectors_when_missing():
    profile = create_provider_profile({"name": "fallback", "host_hints": ["fallback.com"]})

    assert profile.name == "fallback"
    assert profile.play_selectors
    assert profile.popup_close_selectors


def test_set_allowed_host_hints_controls_is_allowed_url():
    set_allowed_host_hints(["example.com", "cdn.example.com"])

    assert is_allowed_url("https://example.com/watch") is True
    assert is_allowed_url("https://cdn.example.com/stream/master.m3u8") is True
    assert is_allowed_url("https://not-allowed.test/video") is False

    set_allowed_host_hints(None)


def test_reload_provider_profiles_loads_allowed_host_hints(tmp_path):
    config_path = tmp_path / "providers_with_policy.json"
    config_path.write_text(
        json.dumps(
            {
                "policy": {
                    "allowed_host_hints": ["allowed.example", "cdn.allowed.example"]
                },
                "profiles": [],
            }
        ),
        encoding="utf-8",
    )

    reload_provider_profiles(str(config_path))

    allowed_hints = get_allowed_host_hints()
    assert allowed_hints == {"allowed.example", "cdn.allowed.example"}
    assert is_allowed_url("https://allowed.example/embed/abc") is True
    assert is_allowed_url("https://denied.example/embed/abc") is False

    reload_provider_profiles()
