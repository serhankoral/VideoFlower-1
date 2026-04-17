#!/usr/bin/env python3
"""
Video URL Interceptor & Downloader - Gelişmiş Stealth Versiyon
"""

import asyncio
import json
import subprocess
import sys
import argparse
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from playwright.async_api import async_playwright
from candidate_store import CandidateStore
from validator_pipeline import ValidationPolicy, filter_candidates
from analysis_core import (
    ProviderProfile,
    detect_provider_profile,
    get_allowed_host_hints,
    is_allowed_url,
    is_m3u8,
    is_playlist_url,
    is_skip,
    is_stream_url,
    is_video_content_type,
    is_youtube,
    normalize_url,
    reload_provider_profiles,
    score_url,
)

# Eğer yüklü değilse: pip install playwright-stealth
try:
    from playwright_stealth import stealth_async
except ImportError:
    stealth_async = None

JS_INTERCEPTOR = """
(function() {
    window.__vf_urls__ = window.__vf_urls__ || [];
    function capture(url) {
        if (!url || url.startsWith('data:') || url.startsWith('about:')) return;
        if (window.__vf_urls__.indexOf(url) === -1) {
            window.__vf_urls__.push(url);
            try { window.__vf_capture__(url); } catch(e) {}
        }
    }
    var XHR = window.XMLHttpRequest;
    var origOpen = XHR.prototype.open;
    XHR.prototype.open = function(method, url) {
        capture(url);
        return origOpen.apply(this, arguments);
    };
    var origFetch = window.fetch;
    window.fetch = function(input, init) {
        capture(typeof input === 'string' ? input : input.url);
        return origFetch.apply(this, arguments);
    };
    var origAddSourceBuffer = MediaSource.prototype.addSourceBuffer;
    MediaSource.prototype.addSourceBuffer = function(mimeType) {
        capture('mediasource:' + mimeType);
        return origAddSourceBuffer.apply(this, arguments);
    };

    function harvestPlayerSources() {
        try {
            var videos = Array.from(document.querySelectorAll('video, source'));
            videos.forEach(function(v) {
                capture(v.currentSrc || v.src);
            });

            if (window.jwplayer && typeof window.jwplayer === 'function') {
                try {
                    var player = window.jwplayer();
                    if (player && typeof player.getPlaylist === 'function') {
                        var playlist = player.getPlaylist() || [];
                        playlist.forEach(function(item) {
                            capture(item.file);
                            if (Array.isArray(item.sources)) {
                                item.sources.forEach(function(s) { capture(s.file || s.src); });
                            }
                        });
                    }
                } catch (e) {}
            }

            var atomCandidates = [window.AtomPlayer, window.atomPlayer, window.player, window.videojs && window.videojs.players];
            atomCandidates.forEach(function(obj) {
                if (!obj) return;
                if (typeof obj === 'string') capture(obj);
                if (obj.src) capture(obj.src);
                if (obj.file) capture(obj.file);
            });
        } catch (e) {}
    }

    setTimeout(harvestPlayerSources, 800);
    setInterval(harvestPlayerSources, 2000);
})();
"""

AD_SKIP_SELECTORS = [
    "button[class*='skip' i]",
    "a[class*='skip' i]",
    "button[id*='skip' i]",
    "a[id*='skip' i]",
    "[class*='ad' i] button[class*='close' i]",
    "[id*='ad' i] button[class*='close' i]",
    "text=/skip\\s*ad/i",
    "text=/reklam(ı|i)?\\s*gec/i",
    "text=/reklami\\s*gec/i",
    "text=/reklamı\\s*gec/i",
    "text=/reklam\\s*gec/i",
]

AD_INDICATOR_SELECTORS = [
    ".ima-ad-container",
    ".video-ads",
    "[class*='ad-overlay' i]",
    "[class*='adplayer' i]",
    "[class*='preroll' i]",
    "[id*='preroll' i]",
    "[class*='vast' i]",
    "[id*='vast' i]",
]

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def load_validation_policy(config_path: str) -> ValidationPolicy:
    path = Path(config_path)
    if not path.exists():
        return ValidationPolicy()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ValidationPolicy()

    if not isinstance(raw, dict):
        return ValidationPolicy()

    policy_raw = raw.get("policy", {})
    if not isinstance(policy_raw, dict):
        policy_raw = {}

    blacklist_entries = tuple(
        str(item).strip().lower()
        for item in policy_raw.get("blacklist_entries", [])
        if str(item).strip()
    )

    min_content_length_mb = 0
    try:
        min_content_length_mb = int(policy_raw.get("min_content_length_mb", 0))
    except Exception:
        min_content_length_mb = 0

    return ValidationPolicy(
        blacklist_entries=blacklist_entries,
        min_content_length_mb=max(min_content_length_mb, 0),
        exclude_manifest=bool(policy_raw.get("exclude_manifest", False)),
    )


def format_seconds(value: float | None) -> str:
    if value is None or value <= 0:
        return "bilinmiyor"
    total = int(value)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def format_bytes(value: int | float | None) -> str:
    if value is None or value <= 0:
        return "bilinmiyor"
    size = float(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024
        idx += 1
    return f"{size:.2f} {units[idx]}"


def probe_video_metadata(stream_url: str, referer: str, debug: bool = False) -> dict:
    metadata = {
        "resolution": None,
        "format": None,
        "duration_seconds": None,
        "size_bytes": None,
    }

    domain = urlparse(referer).netloc
    cmd = [
        "yt-dlp",
        "--ignore-config",
        "--dump-single-json",
        "--no-download",
        "--referer",
        referer,
        "--add-header",
        f"Origin: https://{domain}",
        "--add-header",
        f"User-Agent: {DEFAULT_USER_AGENT}",
        stream_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        if result.returncode == 0 and result.stdout.strip():
            payload = json.loads(result.stdout)
            width = payload.get("width")
            height = payload.get("height")
            if width and height:
                metadata["resolution"] = f"{width}x{height}"

            metadata["format"] = payload.get("ext") or payload.get("format") or payload.get("protocol")
            metadata["duration_seconds"] = payload.get("duration")

            size = payload.get("filesize")
            if not size:
                size = payload.get("filesize_approx")
            metadata["size_bytes"] = size
        elif debug:
            print(f"[debug] yt-dlp metadata okunamadi (rc={result.returncode})")
    except Exception as exc:
        if debug:
            print(f"[debug] yt-dlp metadata hatasi: {exc}")

    header_blob = (
        f"Referer: {referer}\r\n"
        f"Origin: https://{domain}\r\n"
        f"User-Agent: {DEFAULT_USER_AGENT}\r\n"
    )

    if metadata["resolution"] is None or metadata["duration_seconds"] is None:
        ffprobe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,codec_name:format=duration,size,format_name",
            "-of",
            "json",
            "-headers",
            header_blob,
            stream_url,
        ]
        try:
            ff_result = subprocess.run(ffprobe_cmd, capture_output=True, text=True, timeout=25)
            if ff_result.returncode == 0 and ff_result.stdout.strip():
                info = json.loads(ff_result.stdout)
                stream = (info.get("streams") or [{}])[0]
                fmt = info.get("format") or {}

                width = stream.get("width")
                height = stream.get("height")
                if width and height and metadata["resolution"] is None:
                    metadata["resolution"] = f"{width}x{height}"

                if metadata["format"] is None:
                    metadata["format"] = fmt.get("format_name") or stream.get("codec_name")

                if metadata["duration_seconds"] is None:
                    try:
                        metadata["duration_seconds"] = float(fmt.get("duration"))
                    except Exception:
                        pass

                if metadata["size_bytes"] is None:
                    try:
                        metadata["size_bytes"] = int(float(fmt.get("size")))
                    except Exception:
                        pass
            elif debug:
                print(f"[debug] ffprobe metadata okunamadi (rc={ff_result.returncode})")
        except Exception as exc:
            if debug:
                print(f"[debug] ffprobe metadata hatasi: {exc}")

    if metadata["size_bytes"] is None:
        try:
            req = Request(
                stream_url,
                method="HEAD",
                headers={
                    "Referer": referer,
                    "Origin": f"https://{domain}",
                    "User-Agent": DEFAULT_USER_AGENT,
                },
            )
            with urlopen(req, timeout=12) as resp:
                length = resp.headers.get("Content-Length")
                if length:
                    metadata["size_bytes"] = int(length)
        except Exception:
            if debug:
                print("[debug] HEAD ile boyut okunamadi")

    return metadata

# ─── YouTube Modülü ──────────────────────────────────────────────────────────

def download_youtube(
    url: str,
    output_dir: str,
    quality: str = "best",
    no_download: bool = False,
    playlist_mode: bool = False,
    playlist_start: int | None = None,
    playlist_end: int | None = None,
):
    out_tpl = f"{output_dir}/%(title)s.%(ext)s"
    if playlist_mode:
        out_tpl = f"{output_dir}/%(playlist_index)03d - %(title)s.%(ext)s"

    if no_download:
        cmd = ["yt-dlp", "--ignore-config"]
        cmd.append("--yes-playlist" if playlist_mode else "--no-playlist")
        if playlist_mode and playlist_start is not None:
            cmd.extend(["--playlist-start", str(playlist_start)])
        if playlist_mode and playlist_end is not None:
            cmd.extend(["--playlist-end", str(playlist_end)])
        cmd.extend(["-F", url])
        subprocess.run(cmd)
        return
    
    fmt = "bestvideo+bestaudio/best"
    if quality != "best" and quality != "audio":
        h = quality.replace("p", "")
        fmt = f"bestvideo[height<={h}]+bestaudio/best"
    elif quality == "audio":
        fmt = "bestaudio"

    cmd = [
        "yt-dlp", "--ignore-config", "--newline",
        "-f", fmt,
        "-o", out_tpl,
        "--merge-output-format", "mp4", url
    ]

    cmd[3:3] = ["--yes-playlist" if playlist_mode else "--no-playlist"]
    if playlist_mode and playlist_start is not None:
        cmd[3:3] = ["--playlist-start", str(playlist_start)]
    if playlist_mode and playlist_end is not None:
        cmd[3:3] = ["--playlist-end", str(playlist_end)]

    subprocess.run(cmd)


def run_ytdlp_stream(cmd: list[str]) -> tuple[int, bool]:
    cookie_copy_error = "Could not copy Chrome cookie database"
    saw_cookie_error = False

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    assert proc.stdout is not None
    for line in proc.stdout:
        if cookie_copy_error in line:
            saw_cookie_error = True
        print(line, end="")

    rc = proc.wait()
    return rc, saw_cookie_error


def probe_stream_duration_seconds(stream_url: str, referer: str, debug: bool = False) -> float | None:
    domain = urlparse(referer).netloc
    header_blob = (
        f"Referer: {referer}\r\n"
        f"Origin: https://{domain}\r\n"
        f"User-Agent: {DEFAULT_USER_AGENT}\r\n"
    )

    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        "-headers",
        header_blob,
        stream_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if result.returncode != 0:
            if debug:
                print(f"[debug] ffprobe sure okuyamadi (rc={result.returncode}): {stream_url[:120]}")
            return None

        raw = (result.stdout or "").strip().splitlines()
        if not raw:
            return None
        duration = float(raw[0])
        if duration <= 0:
            return None
        return duration
    except Exception as exc:
        if debug:
            print(f"[debug] ffprobe hatasi: {exc}")
        return None

# ─── Ana İşlem (Playwright) ──────────────────────────────────────────────────

async def intercept_and_download(
    page_url: str,
    output_dir: str = ".",
    timeout: int = 45,
    headless: bool = True,
    debug: bool = False,
    no_download: bool = False,
    min_duration_seconds: int = 0,
    ad_finalize_seconds: int = 8,
    ad_stuck_seconds: int = 12,
    validation_policy: ValidationPolicy | None = None,
):
    found_urls: list[str] = []
    media_response_urls: set[str] = set()
    candidate_store = CandidateStore()
    profile = detect_provider_profile(page_url)
    generic_profile_name = "generic"

    def dbg(msg: str):
        if debug:
            print(f"[debug:{profile.name}] {msg}")

    def maybe_update_profile(observed_url: str):
        nonlocal profile

        detected = detect_provider_profile(observed_url)
        if detected.name == generic_profile_name:
            return
        if profile.name == detected.name:
            return

        # Baslangic URL'i generic olsa bile iframe/network kaynaklarindan daha spesifik profile gec.
        if profile.name == generic_profile_name:
            profile = detected
            dbg(f"profil guncellendi: {detected.name} ({observed_url[:120]})")

    async def close_popups(page):
        for frame in page.frames:
            for sel in profile.popup_close_selectors:
                try:
                    el = await frame.query_selector(sel)
                    if el:
                        await el.click(timeout=800, force=True)
                        dbg(f"popup kapatildi: {sel}")
                except Exception:
                    continue

    async def try_skip_ads(page):
        for frame in page.frames:
            for sel in AD_SKIP_SELECTORS:
                try:
                    el = await frame.query_selector(sel)
                    if el:
                        await el.click(timeout=600, force=True)
                        dbg(f"reklam gec denemesi: {sel}")
                except Exception:
                    continue

    async def get_ad_state(page) -> dict:
        has_skip = False
        ad_active = False

        async def visible_in_frame(frame, selector: str) -> bool:
            try:
                loc = frame.locator(selector).first
                if await loc.count() == 0:
                    return False
                return await loc.is_visible()
            except Exception:
                return False

        for frame in page.frames:
            for sel in AD_SKIP_SELECTORS:
                try:
                    if await visible_in_frame(frame, sel):
                        has_skip = True
                        ad_active = True
                        break
                except Exception:
                    continue
            if has_skip:
                continue

            for sel in AD_INDICATOR_SELECTORS:
                try:
                    if await visible_in_frame(frame, sel):
                        ad_active = True
                        break
                except Exception:
                    continue

        return {"ad_active": ad_active, "has_skip": has_skip}

    async def try_autoplay(page):
        # Main page + all frames: many film sites keep the player in cross-origin iframes.
        for frame in page.frames:
            for sel in profile.play_selectors:
                try:
                    el = await frame.query_selector(sel)
                    if el:
                        await el.click(timeout=1000, force=True)
                        dbg(f"autoplay tiklama: {sel}")
                except Exception:
                    continue

            try:
                await frame.evaluate(
                    """() => {
                        const videos = Array.from(document.querySelectorAll('video'));
                        videos.forEach(v => {
                            v.muted = true;
                            const p = v.play();
                            if (p && typeof p.catch === 'function') p.catch(() => {});
                        });
                        return videos.length;
                    }"""
                )
            except Exception:
                pass

    async def collect_player_candidates(page):
        try:
            for frame in page.frames:
                candidates = await frame.evaluate(
                    """() => {
                        const out = [];
                        const add = (u) => {
                            if (!u || typeof u !== 'string') return;
                            if (u.startsWith('blob:') || u.startsWith('about:') || u.startsWith('data:')) return;
                            out.push(u);
                        };

                        document.querySelectorAll('video, source, iframe').forEach(el => {
                            add(el.currentSrc || el.src);
                            add(el.getAttribute('data-src'));
                        });

                        try {
                            if (window.jwplayer && typeof window.jwplayer === 'function') {
                                const p = window.jwplayer();
                                if (p && typeof p.getPlaylist === 'function') {
                                    const pl = p.getPlaylist() || [];
                                    pl.forEach(item => {
                                        add(item.file);
                                        (item.sources || []).forEach(s => add(s.file || s.src));
                                    });
                                }
                            }
                        } catch (e) {}

                        return Array.from(new Set(out));
                    }"""
                )

                for u in candidates:
                    maybe_update_profile(u)
                    if is_stream_url(u) and u not in found_urls:
                        found_urls.append(u)
                        candidate_store.add_or_update(u, "player-candidate")
                        dbg(f"player adayi: {u[:120]}")
        except Exception:
            pass

    async with async_playwright() as p:
        # Geliştirilmiş Launch Ayarları
        browser = await p.chromium.launch(
            executable_path="C:/Program Files/Google/Chrome/Application/chrome.exe", 
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--autoplay-policy=no-user-gesture-required",
                "--mute-audio"
            ]
        )

        # Standart ve Yüksek Çözünürlüklü Context
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
        )

        dbg(f"profil secildi: {profile.name}")

        # Network Dinleme (Katman 1)
        def on_request(req):
            if not is_allowed_url(req.url):
                return
            maybe_update_profile(req.url)
            if is_stream_url(req.url) and req.url not in found_urls:
                found_urls.append(req.url)
                candidate_store.add_or_update(req.url, "network-request", headers=req.headers)
                dbg(f"request yakalandi: {req.url[:120]}")
                if is_m3u8(req.url): print(f"\n[⭐ M3U8 Bulundu] {req.url[:80]}...")

        def on_response(res):
            if not is_allowed_url(res.url):
                return
            maybe_update_profile(res.url)
            ct = (res.headers.get("content-type") or "").lower()
            if not ct:
                return
            content_length = None
            try:
                cl = res.headers.get("content-length")
                content_length = int(cl) if cl else None
            except Exception:
                content_length = None

            if is_video_content_type(ct) and not is_skip(res.url) and res.url not in found_urls:
                found_urls.append(res.url)
                media_response_urls.add(res.url)
                candidate_store.add_or_update(
                    res.url,
                    "network-response",
                    headers=res.headers,
                    content_type=ct,
                    content_length=content_length,
                )
                dbg(f"response yakalandi ({ct}): {res.url[:120]}")

        context.on("request", on_request)
        context.on("response", on_response)
        await context.add_init_script(JS_INTERCEPTOR)

        page = await context.new_page()
        
        # Stealth Uygula (Bot engellerini aşmak için)
        if stealth_async:
            await stealth_async(page)

        # JS'den gelen URL'leri yakala
        async def js_capture(url: str):
            normalized = normalize_url(url, page_url)
            if not is_allowed_url(normalized):
                return
            maybe_update_profile(normalized)
            if (is_stream_url(normalized) or is_m3u8(normalized) or ".mp4" in normalized.lower()) and normalized not in found_urls:
                found_urls.append(normalized)
                candidate_store.add_or_update(normalized, "js-capture")
                dbg(f"js capture: {normalized[:120]}")

        await page.expose_function("__vf_capture__", js_capture)

        print(f"🔄 Sayfa yükleniyor (Headless: {headless})...")
        try:
            await page.goto(page_url, wait_until="domcontentloaded", timeout=30000)
            
            # Lazy-load tetiklemek için aşağı kaydır
            if headless:
                await page.mouse.wheel(0, 1000)
                await asyncio.sleep(2)
        except Exception as e:
            print(f"⚠️ Yükleme uyarısı: {e}")

        await close_popups(page)

        # Oynatıcıyı tetikleme (ana sayfa + iframe)
        await try_autoplay(page)
        await try_skip_ads(page)
        await collect_player_candidates(page)

        # Bekleme ve Dinleme Döngüsü
        ad_finalize_deadline: int | None = None
        last_autoplay_tick = 0
        ad_active_streak = 0
        ad_stuck_threshold = max(ad_stuck_seconds, 0)
        for i in range(timeout):
            ad_state = await get_ad_state(page)
            ad_active = ad_state["ad_active"]
            has_skip = ad_state["has_skip"]

            if ad_active:
                ad_active_streak += 1
                ad_finalize_deadline = None
                await close_popups(page)
                if has_skip:
                    dbg("reklam aktif: skip bulundu, tiklama denenecek")
                    await try_skip_ads(page)
                else:
                    dbg("reklam aktif: skip bekleniyor")
            else:
                ad_active_streak = 0
                if i - last_autoplay_tick >= 6 and not found_urls:
                    # Reklam bitti ama oynatma kendiliginden baslamadiysa periyodik tetikleme dene.
                    await try_autoplay(page)
                    last_autoplay_tick = i

            # Reklam durumu uzun sure degismiyorsa false-positive ihtimaline karsi akisi zorla ilerlet.
            if ad_active and ad_stuck_threshold > 0 and ad_active_streak >= ad_stuck_threshold:
                dbg(f"reklam durumu {ad_active_streak}s degismedi, fallback devreye aliniyor")
                ad_active = False
                ad_active_streak = 0
                await try_autoplay(page)
                await collect_player_candidates(page)

            if i - last_autoplay_tick >= 6 and not found_urls and not ad_active:
                # Reklam bitti ama oynatma kendiliginden baslamadiysa periyodik tetikleme dene.
                await try_autoplay(page)
                last_autoplay_tick = i

            has_video_candidate = any(is_m3u8(u) or ".mp4" in u.lower() for u in found_urls)
            if has_video_candidate and ad_finalize_deadline is None and not ad_active:
                if ad_finalize_seconds > 0:
                    ad_finalize_deadline = i + ad_finalize_seconds
                    dbg(f"kaynak bulundu, reklam bitis fazi basladi (+{ad_finalize_seconds}s)")
                    await close_popups(page)
                    await try_skip_ads(page)
                    await try_autoplay(page)
                    await collect_player_candidates(page)
                else:
                    break

            if ad_finalize_deadline is not None:
                await close_popups(page)
                await try_skip_ads(page)
                if not ad_active:
                    await try_autoplay(page)
                await collect_player_candidates(page)
                if i >= ad_finalize_deadline:
                    dbg("reklam bitis fazi tamamlandi")
                    break

            if i > 0 and i % 5 == 0:
                await close_popups(page)
                await try_autoplay(page)
                await try_skip_ads(page)
                await collect_player_candidates(page)

            await asyncio.sleep(1)
            sys.stdout.write(f"\r⏳ Aranıyor... {i+1}/{timeout}s")
            sys.stdout.flush()
        print()

        # Son çare: performance API üzerinden kaynak isimlerini topla.
        if not found_urls:
            try:
                perf_urls = await page.evaluate(
                    """() => performance.getEntriesByType('resource').map(r => r.name)"""
                )
                for u in perf_urls:
                    normalized = normalize_url(u, page_url)
                    if not is_allowed_url(normalized):
                        continue
                    if is_stream_url(normalized) and normalized not in found_urls:
                        found_urls.append(normalized)
                        candidate_store.add_or_update(normalized, "performance")
                        dbg(f"performance kaynagi: {normalized[:120]}")
            except Exception:
                pass

        if not found_urls:
            await collect_player_candidates(page)

        await browser.close()

    # Sonuç ve İndirme
    if not found_urls:
        print("❌ Video bulunamadı.")
        return

    all_candidates = [
        c for c in candidate_store.all()
        if c.url in media_response_urls or is_stream_url(c.url) or is_m3u8(c.url) or ".mp4" in c.url.lower()
    ]
    if not all_candidates:
        print("❌ Video bulunamadı.")
        return

    policy = validation_policy or ValidationPolicy()
    filtered_candidates, rejected = filter_candidates(all_candidates, policy)
    if debug and rejected:
        for rejected_url, reason in rejected.items():
            print(f"[debug:validator] elendi ({reason}): {rejected_url[:120]}")

    if not filtered_candidates:
        print("❌ Filtreleme sonrasi uygun video adayi kalmadi.")
        return

    candidates = [candidate.url for candidate in filtered_candidates]

    candidates.sort(key=lambda u: score_url(u, profile), reverse=True)
    best_url = None

    if min_duration_seconds > 0:
        fallback_unknown_duration: list[str] = []
        for candidate in candidates:
            duration = probe_stream_duration_seconds(candidate, page_url, debug)
            if duration is None:
                fallback_unknown_duration.append(candidate)
                continue

            dbg(f"sure kontrolu: {candidate[:80]}... -> {int(duration)}s")
            if duration >= min_duration_seconds:
                best_url = candidate
                break

        if best_url is None and fallback_unknown_duration:
            best_url = fallback_unknown_duration[0]
            dbg("uygun sure bulunamadi, sure okunamayan en iyi aday secildi")
    else:
        best_url = candidates[0]

    if best_url is None:
        print(f"❌ {min_duration_seconds}s uzerinde video adayi bulunamadi.")
        return
    
    print(f"\n🎯 En iyi URL: {best_url[:100]}...")

    metadata = probe_video_metadata(best_url, page_url, debug)
    print("[meta] Cozunurluk:", metadata["resolution"] or "bilinmiyor")
    print("[meta] Format:", metadata["format"] or "bilinmiyor")
    print("[meta] Sure:", format_seconds(metadata["duration_seconds"]))
    print("[meta] Boyut:", format_bytes(metadata["size_bytes"]))

    if not no_download:
        download_with_ytdlp(best_url, page_url, output_dir, profile, debug)

def download_with_ytdlp(stream_url: str, referer: str, output_dir: str, profile: ProviderProfile, debug: bool = False):
    domain = urlparse(referer).netloc
    cmd = [
        "yt-dlp", "--ignore-config", "--newline", "--referer", referer,
        "--add-header", f"Origin: https://{domain}",
        "-o", f"{output_dir}/%(title)s.%(ext)s",
        "--merge-output-format", "mp4", stream_url
    ]

    if profile.name == "doodstream":
        # Doodstream benzeri hostlarda tarayici cookie baglamini kullanmak basariyi artirir.
        cmd[1:1] = ["--cookies-from-browser", "chrome"]

    if profile.name == "atom":
        # Atom benzeri embed akislarda tarayici cookie ve ek user-agent faydali olur.
        cmd[1:1] = ["--cookies-from-browser", "chrome"]
        cmd[1:1] = [
            "--add-header",
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        ]

    if debug:
        print("[debug] yt-dlp komutu:", " ".join(cmd))

    rc, saw_cookie_error = run_ytdlp_stream(cmd)

    has_cookie_flag = "--cookies-from-browser" in cmd
    if rc != 0 and has_cookie_flag and saw_cookie_error:
        retry_cmd: list[str] = []
        skip_next = False
        for token in cmd:
            if skip_next:
                skip_next = False
                continue
            if token == "--cookies-from-browser":
                skip_next = True
                continue
            retry_cmd.append(token)

        print("[uyari] Chrome cookie okunamadi, cookiesiz tekrar deneniyor...")
        if debug:
            print("[debug] yt-dlp retry:", " ".join(retry_cmd))

        retry_rc, _ = run_ytdlp_stream(retry_cmd)
        if retry_rc != 0:
            print("[hata] Indirme basarisiz oldu.")
        return

    if rc != 0:
        print("[hata] Indirme basarisiz oldu.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("-o", "--output", default=".")
    parser.add_argument("-q", "--quality", default="best")
    parser.add_argument("--visible", action="store_true") # Artık varsayılan headless, --visible opsiyonel
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-download", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--playlist", action="store_true", help="YouTube URL'lerinde listeyi sirali indir")
    parser.add_argument("--playlist-start", type=int, help="YouTube liste baslangic indexi (1 tabanli)")
    parser.add_argument("--playlist-end", type=int, help="YouTube liste bitis indexi (1 tabanli)")
    parser.add_argument("--min-duration-minutes", type=int, default=0, help="Minimum video suresi (dakika)")
    parser.add_argument(
        "--ad-finalize-seconds",
        type=int,
        default=8,
        help="Kaynak bulunduğunda reklam gecis/yenileme icin beklenecek ek sure (saniye)",
    )
    parser.add_argument(
        "--ad-stuck-seconds",
        type=int,
        default=12,
        help="Reklam aktif durumu degismeden kalirsa fallback tetikleme suresi (saniye)",
    )
    parser.add_argument(
        "--providers-config",
        default="providers.json",
        help="Harici provider ve policy ayarlari JSON dosyasi",
    )
    args = parser.parse_args()

    print("[uyari] Bu arac yalnizca size ait veya acik izinli icerikler icin kullanilmalidir.")

    loaded_profiles = reload_provider_profiles(str(Path(args.providers_config)))
    validation_policy = load_validation_policy(args.providers_config)
    if loaded_profiles:
        print(f"[bilgi] {loaded_profiles} harici provider profili yuklendi.")

    allowed_hints = get_allowed_host_hints()
    if allowed_hints and not is_allowed_url(args.url):
        print("[bilgi] Baslangic sayfasi allowlist disinda, analiz devam edecek.")
        print("[bilgi] Sadece allowlist ile eslesen kaynak URL'ler dikkate alinacak.")

    if is_youtube(args.url):
        playlist_mode = args.playlist or is_playlist_url(args.url)
        if playlist_mode:
            print("[bilgi] YouTube playlist modu aktif. Videolar sirali indirilecek.")

        download_youtube(
            args.url,
            args.output,
            args.quality,
            args.no_download,
            playlist_mode,
            args.playlist_start,
            args.playlist_end,
        )
    else:
        asyncio.run(intercept_and_download(
            args.url,
            args.output,
            args.timeout,
            not args.visible,
            args.debug,
            args.no_download,
            max(args.min_duration_minutes, 0) * 60,
            max(args.ad_finalize_seconds, 0),
            max(args.ad_stuck_seconds, 0),
            validation_policy,
        ))

if __name__ == "__main__":
    main()