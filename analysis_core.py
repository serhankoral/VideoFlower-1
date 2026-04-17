import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlparse

STREAM_PATTERNS = [
    ".m3u8", ".mp4", ".ts", ".mkv", ".webm",
    "manifest", "playlist", "/hls/", "/dash/",
    "videoplayback", "get_video", "stream",
]

SKIP_DOMAINS = [
    "google-analytics", "googletagmanager", "facebook", "twitter",
    "ads", "adservice", "doubleclick", "analytics", "tracking",
    "recaptcha", "captcha", "fonts.googleapis", "fonts.gstatic",
]

VIDEO_CONTENT_TYPES = [
    "video/", "audio/", "application/x-mpegurl",
    "application/vnd.apple.mpegurl", "application/dash+xml",
    "application/octet-stream",
]

YOUTUBE_DOMAINS = {
    "youtube.com", "youtu.be", "www.youtube.com",
    "m.youtube.com", "music.youtube.com",
}

DOODSTREAM_DOMAINS = {
    "doodstream.com", "dood.to", "dood.so", "dood.cx", "dood.sh", "dood.wf",
}

ATOM_DOMAINS = {
    "fullhdfilmizlesene.live", "www.fullhdfilmizlesene.live",
}

CLOSE_DOMAINS = {
    "closeload.com", "www.closeload.com", "close", "closeload",
}

RAPIDRAME_DOMAINS = {
    "rapidrame.com", "www.rapidrame.com", "rapidrame",
}

DRAKKAR_DOMAINS = {
    "drakkar", "drakkarvideo", "drakkarstream",
}

VIDRAME_DOMAINS = {
    "vidrame.com", "www.vidrame.com", "vidrame",
}

GENERIC_PLAY_SELECTORS = [
    ".vjs-big-play-button",
    ".plyr__control--overlaid",
    "button[aria-label*='Play']",
    "button[title*='Play']",
    "[class*='play']",
    "video",
    "iframe",
]

GENERIC_POPUP_CLOSE_SELECTORS = [
    "button[aria-label*='close' i]",
    "button[title*='close' i]",
    "button[class*='close' i]",
    ".close",
    ".btn-close",
    "[id*='close' i]",
    "[class*='cookie' i] button",
]

ATOM_PLAY_SELECTORS = [
    "[class*='atom' i] [class*='play' i]",
    "[id*='atom' i] [class*='play' i]",
    ".jw-icon-play",
    ".jw-display-icon-container",
    ".vjs-big-play-button",
    "[data-player*='atom' i]",
    *GENERIC_PLAY_SELECTORS,
]

ATOM_POPUP_CLOSE_SELECTORS = [
    "[class*='ads' i] [class*='close' i]",
    "[id*='ads' i] [class*='close' i]",
    "[class*='overlay' i] [class*='close' i]",
    *GENERIC_POPUP_CLOSE_SELECTORS,
]

CLOSE_PLAY_SELECTORS = [
    "[id*='close' i] [class*='play' i]",
    "[class*='close' i] [class*='play' i]",
    "[data-player*='close' i]",
    ".jw-icon-play",
    ".jw-display-icon-container",
    ".vjs-big-play-button",
    *GENERIC_PLAY_SELECTORS,
]

CLOSE_POPUP_CLOSE_SELECTORS = [
    "[class*='close' i] button",
    "[id*='close' i] button",
    "[class*='overlay' i] [class*='close' i]",
    *GENERIC_POPUP_CLOSE_SELECTORS,
]

RAPIDRAME_PLAY_SELECTORS = [
    "[id*='rapidrame' i] [class*='play' i]",
    "[class*='rapidrame' i] [class*='play' i]",
    "[data-player*='rapidrame' i]",
    "button[class*='play' i]",
    ".jw-icon-play",
    ".jw-display-icon-container",
    *GENERIC_PLAY_SELECTORS,
]

RAPIDRAME_POPUP_CLOSE_SELECTORS = [
    "[class*='rapidrame' i] [class*='close' i]",
    "[id*='rapidrame' i] [class*='close' i]",
    "[class*='overlay' i] [class*='close' i]",
    *GENERIC_POPUP_CLOSE_SELECTORS,
]

DRAKKAR_PLAY_SELECTORS = [
    "[id*='drakkar' i] [class*='play' i]",
    "[class*='drakkar' i] [class*='play' i]",
    "[data-player*='drakkar' i]",
    ".jw-display-icon-container",
    ".jw-icon-play",
    ".vjs-big-play-button",
    *GENERIC_PLAY_SELECTORS,
]

DRAKKAR_POPUP_CLOSE_SELECTORS = [
    "[class*='drakkar' i] [class*='close' i]",
    "[id*='drakkar' i] [class*='close' i]",
    "[class*='ads' i] [class*='close' i]",
    *GENERIC_POPUP_CLOSE_SELECTORS,
]

VIDRAME_PLAY_SELECTORS = [
    "[id*='vidrame' i] [class*='play' i]",
    "[class*='vidrame' i] [class*='play' i]",
    "[data-player*='vidrame' i]",
    "button[aria-label*='Play']",
    ".jw-icon-play",
    ".jw-display-icon-container",
    *GENERIC_PLAY_SELECTORS,
]

VIDRAME_POPUP_CLOSE_SELECTORS = [
    "[class*='vidrame' i] [class*='close' i]",
    "[id*='vidrame' i] [class*='close' i]",
    "[class*='overlay' i] [class*='close' i]",
    *GENERIC_POPUP_CLOSE_SELECTORS,
]


@dataclass
class ProviderProfile:
    name: str
    host_hints: tuple[str, ...]
    play_selectors: list[str]
    popup_close_selectors: list[str]
    score_boost_patterns: tuple[str, ...]


GENERIC_PROFILE = ProviderProfile(
    name="generic",
    host_hints=tuple(),
    play_selectors=GENERIC_PLAY_SELECTORS,
    popup_close_selectors=GENERIC_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=(".m3u8", "manifest", "/hls/", ".mp4"),
)

DOODSTREAM_PROFILE = ProviderProfile(
    name="doodstream",
    host_hints=tuple(DOODSTREAM_DOMAINS),
    play_selectors=[
        "#dplayer .dplayer-play-icon",
        "[id*='dood' i] [class*='play' i]",
        "[class*='play-button' i]",
        *GENERIC_PLAY_SELECTORS,
    ],
    popup_close_selectors=[
        "[id*='overlay' i] button",
        "[class*='popup' i] button",
        *GENERIC_POPUP_CLOSE_SELECTORS,
    ],
    score_boost_patterns=(".m3u8", "master.m3u8", "/pass_md5/", ".mp4"),
)

ATOM_PROFILE = ProviderProfile(
    name="atom",
    host_hints=tuple(ATOM_DOMAINS),
    play_selectors=ATOM_PLAY_SELECTORS,
    popup_close_selectors=ATOM_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=("master.m3u8", ".m3u8", "/hls/", "/embed/", "atom", ".mp4"),
)

CLOSE_PROFILE = ProviderProfile(
    name="close",
    host_hints=tuple(CLOSE_DOMAINS),
    play_selectors=CLOSE_PLAY_SELECTORS,
    popup_close_selectors=CLOSE_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=("close", ".m3u8", "master.m3u8", "/hls/", ".mp4"),
)

RAPIDRAME_PROFILE = ProviderProfile(
    name="rapidrame",
    host_hints=tuple(RAPIDRAME_DOMAINS),
    play_selectors=RAPIDRAME_PLAY_SELECTORS,
    popup_close_selectors=RAPIDRAME_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=("rapidrame", ".m3u8", "manifest", "/hls/", ".mp4"),
)

DRAKKAR_PROFILE = ProviderProfile(
    name="drakkar",
    host_hints=tuple(DRAKKAR_DOMAINS),
    play_selectors=DRAKKAR_PLAY_SELECTORS,
    popup_close_selectors=DRAKKAR_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=("drakkar", ".m3u8", "master.m3u8", "/hls/", ".mp4"),
)

VIDRAME_PROFILE = ProviderProfile(
    name="vidrame",
    host_hints=tuple(VIDRAME_DOMAINS),
    play_selectors=VIDRAME_PLAY_SELECTORS,
    popup_close_selectors=VIDRAME_POPUP_CLOSE_SELECTORS,
    score_boost_patterns=("vidrame", ".m3u8", "manifest", "/hls/", ".mp4"),
)

BUILTIN_PROVIDER_PROFILES = [
    DOODSTREAM_PROFILE,
    ATOM_PROFILE,
    CLOSE_PROFILE,
    RAPIDRAME_PROFILE,
    DRAKKAR_PROFILE,
    VIDRAME_PROFILE,
    GENERIC_PROFILE,
]

PROVIDER_PROFILES = list(BUILTIN_PROVIDER_PROFILES)
ALLOWED_HOST_HINTS: set[str] | None = None


def create_provider_profile(config: dict) -> ProviderProfile:
    name = str(config["name"]).strip().lower()
    host_hints = tuple(str(item).strip().lower() for item in config.get("host_hints", []) if str(item).strip())
    play_selectors = [str(item).strip() for item in config.get("play_selectors", []) if str(item).strip()]
    popup_close_selectors = [
        str(item).strip() for item in config.get("popup_close_selectors", []) if str(item).strip()
    ]
    score_boost_patterns = tuple(
        str(item).strip().lower() for item in config.get("score_boost_patterns", []) if str(item).strip()
    )

    if not name:
        raise ValueError("Provider profile name cannot be empty.")

    return ProviderProfile(
        name=name,
        host_hints=host_hints,
        play_selectors=play_selectors or list(GENERIC_PLAY_SELECTORS),
        popup_close_selectors=popup_close_selectors or list(GENERIC_POPUP_CLOSE_SELECTORS),
        score_boost_patterns=score_boost_patterns,
    )


def register_provider_profile(profile: ProviderProfile) -> None:
    global PROVIDER_PROFILES

    without_same_name = [item for item in PROVIDER_PROFILES if item.name != profile.name]
    generic_profiles = [item for item in without_same_name if item.name == GENERIC_PROFILE.name]
    non_generic_profiles = [item for item in without_same_name if item.name != GENERIC_PROFILE.name]
    PROVIDER_PROFILES = [*non_generic_profiles, profile, *generic_profiles]


def set_allowed_host_hints(host_hints: list[str] | tuple[str, ...] | set[str] | None) -> None:
    global ALLOWED_HOST_HINTS
    if not host_hints:
        ALLOWED_HOST_HINTS = None
        return

    normalized = {str(item).strip().lower() for item in host_hints if str(item).strip()}
    ALLOWED_HOST_HINTS = normalized or None


def get_allowed_host_hints() -> set[str] | None:
    if ALLOWED_HOST_HINTS is None:
        return None
    return set(ALLOWED_HOST_HINTS)


def is_allowed_url(url: str) -> bool:
    if ALLOWED_HOST_HINTS is None:
        return True

    host = urlparse(url).netloc.lower()
    return any(hint in host for hint in ALLOWED_HOST_HINTS)


def reload_provider_profiles(config_path: str | None = None) -> int:
    global PROVIDER_PROFILES

    PROVIDER_PROFILES = list(BUILTIN_PROVIDER_PROFILES)
    set_allowed_host_hints(None)
    if not config_path:
        return 0

    path = Path(config_path)
    if not path.exists():
        return 0

    raw_data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw_data, list):
        configs = raw_data
        allowed_hints = None
    else:
        configs = raw_data.get("profiles", [])
        policy = raw_data.get("policy", {})
        allowed_hints = policy.get("allowed_host_hints")
        if allowed_hints is None:
            allowed_hints = raw_data.get("allowed_host_hints")

    set_allowed_host_hints(allowed_hints)

    loaded = 0
    for config in configs:
        profile = create_provider_profile(config)
        register_provider_profile(profile)
        loaded += 1
    return loaded


def is_youtube(url: str) -> bool:
    domain = urlparse(url).netloc.lower().lstrip("www.")
    return domain in {d.lstrip("www.") for d in YOUTUBE_DOMAINS}


def is_playlist_url(url: str) -> bool:
    query = parse_qs(urlparse(url).query)
    return bool(query.get("list"))


def detect_provider_profile(url: str) -> ProviderProfile:
    host = urlparse(url).netloc.lower()
    for profile in PROVIDER_PROFILES:
        if any(h in host for h in profile.host_hints):
            return profile
    return GENERIC_PROFILE


def is_skip(url: str) -> bool:
    url_lower = url.lower()
    return any(s in url_lower for s in SKIP_DOMAINS)


def is_stream_url(url: str) -> bool:
    if is_skip(url):
        return False
    return any(p in url.lower() for p in STREAM_PATTERNS)


def normalize_url(raw_url: str, base_url: str) -> str:
    if not raw_url:
        return raw_url
    if raw_url.startswith("//"):
        return f"https:{raw_url}"
    if raw_url.startswith("/"):
        return urljoin(base_url, raw_url)
    return raw_url


def is_video_content_type(ct: str) -> bool:
    return any(ct.startswith(v) for v in VIDEO_CONTENT_TYPES)


def is_m3u8(url: str) -> bool:
    u = url.lower()
    return ".m3u8" in u or "manifest" in u or "mpegurl" in u


def score_url(url: str, profile: ProviderProfile) -> int:
    s = 0
    u = url.lower()
    if ".m3u8" in u:
        s += 100
    if "master.m3u8" in u:
        s += 110
    if "manifest" in u:
        s += 90
    if "/hls/" in u:
        s += 80
    if ".mp4" in u:
        s += 50
    if ".json" in u:
        s -= 160
    if "blob:" in u:
        s -= 120
    for p in profile.score_boost_patterns:
        if p in u:
            s += 20
    if is_skip(url):
        s -= 200
    return s
