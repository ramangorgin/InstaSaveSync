#!/usr/bin/env python3
"""
Instagram Saved Posts Downloader – Browser-only Edition (2026-08)
Downloads all media from your saved posts.
- Images & carousels via Playwright
- Videos when available
- Robust against individual post failures
- Incremental & resumable
"""

import json
import logging
import os
import re
import sys
import time
import random
from pathlib import Path
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from tqdm import tqdm

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
DOWNLOADS_DIR = Path("downloads")
DOWNLOADS_DIR.mkdir(exist_ok=True)

ALL_POSTS_FILE = "all_posts.json"
DOWNLOADED_FILE = "downloaded.json"
USER_DATA_DIR = "./browser_data"
COOKIE_FILE = "cookies.txt"

SCROLL_DELAY = 1.5
INITIAL_WAIT = 3.0
STABLE_ROUNDS = 3

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ----------------------------------------------------------------------
# Persistent sets
# ----------------------------------------------------------------------
def load_set(path) -> set:
    if os.path.exists(path):
        try:
            with open(path) as f:
                return set(json.load(f))
        except Exception:
            log.warning(f"Could not load {path}, starting fresh.")
    return set()


def save_set(path, data):
    with open(path, "w") as f:
        json.dump(sorted(data), f, indent=2)


# ----------------------------------------------------------------------
# Cookie export
# ----------------------------------------------------------------------
def export_cookies(context, path):
    cookies = context.cookies()
    with open(path, "w") as f:
        f.write("# Netscape HTTP Cookie File\n")
        for c in cookies:
            expires = c.get("expires", 0)
            exp = str(int(expires)) if expires and expires > 0 else "0"
            f.write(
                f"{c.get('domain', '')}\t"
                f"{'TRUE' if c.get('domain', '').startswith('.') else 'FALSE'}\t"
                f"{c.get('path', '/')}\t"
                f"{'TRUE' if c.get('secure', False) else 'FALSE'}\t"
                f"{exp}\t"
                f"{c['name']}\t"
                f"{c['value']}\n"
            )


# ----------------------------------------------------------------------
# Login / session check
# ----------------------------------------------------------------------
def ensure_logged_in(context, page, username):
    page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
    if "login" in page.url:
        log.info("Login required. Browser will open – log in manually, then press ENTER.")
        page.goto("https://www.instagram.com/accounts/login/")
        input(">>> Press ENTER after you have fully logged in ...")
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        if "login" in page.url:
            raise RuntimeError("Still on login page. Aborting.")

    saved_url = f"https://www.instagram.com/{username}/saved/"
    page.goto(saved_url, wait_until="domcontentloaded")
    if "login" in page.url:
        raise RuntimeError("Session expired – re-run and log in again.")
    log.info("Session valid.")


# ----------------------------------------------------------------------
# Full saved-posts scan
# ----------------------------------------------------------------------
def full_scan_saved(page, username):
    saved_url = f"https://www.instagram.com/{username}/saved/"
    page.goto(saved_url, wait_until="domcontentloaded", timeout=30000)
    time.sleep(INITIAL_WAIT)

    if page.locator('a[href*="/p/"], a[href*="/reel/"], a[href*="/tv/"]').count() == 0:
        try:
            btn = page.get_by_text("All posts", exact=True).first
            if btn.is_visible():
                btn.click()
                time.sleep(INITIAL_WAIT)
        except Exception:
            pass

    shortcode_re = re.compile(r"/(?:p|reel|tv)/([A-Za-z0-9_-]+)")
    all_shortcodes = set()
    stable = 0
    prev_height = 0

    for scroll_idx in range(1000):
        hrefs = page.locator(
            'a[href*="/p/"], a[href*="/reel/"], a[href*="/tv/"]'
        ).evaluate_all("els => els.map(e => e.href)")

        before = len(all_shortcodes)
        for href in hrefs:
            m = shortcode_re.search(href)
            if m:
                all_shortcodes.add(m.group(1))

        added = len(all_shortcodes) - before
        height = page.evaluate(
            "document.documentElement.scrollHeight || document.body.scrollHeight"
        )

        if added == 0 and height == prev_height:
            stable += 1
        else:
            stable = 0
        prev_height = height

        if scroll_idx % 10 == 0:
            log.info(f"Scan scroll {scroll_idx+1}: {len(all_shortcodes)} posts (+{added})")

        if stable >= STABLE_ROUNDS:
            break

        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        time.sleep(SCROLL_DELAY)

    log.info(f"Full scan complete: {len(all_shortcodes)} saved posts found.")
    return all_shortcodes


# ----------------------------------------------------------------------
# Media extraction (reliable version)
# ----------------------------------------------------------------------
def extract_media_via_browser(page, shortcode):
    """
    Collect all reasonably large images from the page + any videos.
    """
    urls_to_try = [
        f"https://www.instagram.com/p/{shortcode}/",
        f"https://www.instagram.com/reel/{shortcode}/",
    ]

    media_items = []
    collected = set()

    for post_url in urls_to_try:
        try:
            page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"Failed to open {post_url}: {e}")
            continue

        # Unavailable checks
        try:
            if page.locator("text=Sorry, this page isn't available").count() > 0:
                return []
            if page.locator("text=Page not found").count() > 0:
                return []
        except Exception:
            pass

        time.sleep(3.5)

        # ---------- Collect images ----------
        try:
            imgs = page.evaluate("""() => {
                return [...document.querySelectorAll('img')].map(img => ({
                    src: img.src || '',
                    srcset: img.srcset || '',
                    width: img.naturalWidth || 0,
                    height: img.naturalHeight || 0
                }));
            }""")
        except Exception:
            imgs = []

        for img in imgs:
            src = img.get("src", "")
            width = img.get("width", 0)
            height = img.get("height", 0)

            if width < 300 and height < 300:
                continue

            best = src
            best_w = width
            srcset = img.get("srcset", "")
            if srcset:
                for part in srcset.split(","):
                    parts = part.strip().split()
                    if len(parts) >= 2 and parts[1].endswith("w"):
                        try:
                            w = int(parts[1][:-1])
                            if w > best_w:
                                best_w = w
                                best = parts[0]
                        except ValueError:
                            pass

            if not best or best in collected:
                continue
            if "cdninstagram" not in best and "fbcdn" not in best and "scontent" not in best:
                continue

            collected.add(best)
            media_items.append((best, False))

        # ---------- Collect videos ----------
        try:
            videos = page.evaluate("""() => {
                return [...document.querySelectorAll('video')].map(v => ({
                    src: v.src || v.currentSrc || '',
                    sources: [...v.querySelectorAll('source')].map(s => s.src)
                }));
            }""")
        except Exception:
            videos = []

        for v in videos:
            candidates = [v.get("src", "")] + v.get("sources", [])
            for src in candidates:
                if src and src not in collected and not src.startswith("blob:"):
                    collected.add(src)
                    media_items.append((src, True))

        # Navigate carousel
        for _ in range(12):
            try:
                page.keyboard.press("ArrowRight")
                time.sleep(1.0)

                imgs = page.evaluate("""() => {
                    return [...document.querySelectorAll('img')].map(img => ({
                        src: img.src || '',
                        width: img.naturalWidth || 0,
                        height: img.naturalHeight || 0
                    }));
                }""")
            except Exception:
                break

            for img in imgs:
                src = img.get("src", "")
                width = img.get("width", 0)
                height = img.get("height", 0)
                if width < 300 and height < 300:
                    continue
                if not src or src in collected:
                    continue
                if "cdninstagram" not in src and "fbcdn" not in src and "scontent" not in src:
                    continue
                collected.add(src)
                media_items.append((src, False))

        if media_items:
            break

    # Deduplicate
    seen = set()
    final = []
    for url, is_vid in media_items:
        if url not in seen:
            seen.add(url)
            final.append((url, is_vid))
    return final


# ----------------------------------------------------------------------
# Download helper
# ----------------------------------------------------------------------
def download_media(page, url: str, filepath: Path) -> bool:
    if not url.startswith("blob:"):
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.instagram.com/",
        }
        for attempt in range(1, 4):
            try:
                resp = requests.get(url, headers=headers, stream=True, timeout=60)
                resp.raise_for_status()
                with open(filepath, "wb") as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                return True
            except Exception as e:
                log.warning(f"Download attempt {attempt} failed: {e}")
                time.sleep(2 * attempt)
        return False

    # blob: fallback
    try:
        try:
            resp = page.request.get(url)
            if resp.ok:
                with open(filepath, "wb") as f:
                    f.write(resp.body())
                return True
        except Exception:
            pass

        data = page.evaluate(
            """async (blobUrl) => {
                try {
                    const r = await fetch(blobUrl);
                    const buf = await r.arrayBuffer();
                    return Array.from(new Uint8Array(buf));
                } catch (e) {
                    return null;
                }
            }""",
            url,
        )
        if data:
            with open(filepath, "wb") as f:
                f.write(bytes(data))
            return True
        return False
    except Exception as e:
        log.error(f"Failed to download blob: {e}")
        return False


# ----------------------------------------------------------------------
# Process one post
# ----------------------------------------------------------------------
def process_post(shortcode, page, context, downloaded_set):
    if shortcode in downloaded_set:
        return True

    export_cookies(context, COOKIE_FILE)

    log.info(f"Extracting {shortcode} via browser...")
    media_items = extract_media_via_browser(page, shortcode)

    if not media_items:
        log.warning(f"No media found for {shortcode}. Skipping.")
        return False

    downloaded_any = False
    for idx, (media_url, is_video) in enumerate(media_items):
        if is_video:
            ext = "mp4"
        else:
            path = urlparse(media_url).path
            ext = Path(path).suffix.lstrip(".").lower()
            if ext not in {"jpg", "jpeg", "png", "webp", "avif", "mp4"}:
                ext = "jpg"

        if len(media_items) > 1:
            filename = f"{shortcode}_{idx+1}.{ext}"
        else:
            filename = f"{shortcode}.{ext}"

        filepath = DOWNLOADS_DIR / filename
        log.info(f"  → {filename}")

        if download_media(page, media_url, filepath):
            downloaded_any = True
        else:
            log.error(f"Failed to download: {media_url}")

    if downloaded_any:
        downloaded_set.add(shortcode)
        save_set(DOWNLOADED_FILE, downloaded_set)
        return True
    return False


# ----------------------------------------------------------------------
# Completeness check helper
# ----------------------------------------------------------------------
def print_completeness():
    all_posts = load_set(ALL_POSTS_FILE)
    downloaded = load_set(DOWNLOADED_FILE)
    remaining = sorted(all_posts - downloaded)

    print("\n" + "=" * 60)
    print("ARCHIVE STATUS")
    print("=" * 60)
    print(f"Total known posts     : {len(all_posts)}")
    print(f"Marked as downloaded  : {len(downloaded)}")
    print(f"Remaining             : {len(remaining)}")
    print(f"Files on disk         : {len(list(DOWNLOADS_DIR.glob('*')))}")
    if remaining:
        print("\nFirst 15 remaining shortcodes:")
        for sc in remaining[:15]:
            print(f"  - {sc}")
        if len(remaining) > 15:
            print(f"  ... and {len(remaining)-15} more")
    else:
        print("\n✓ Archive appears complete!")
    print("=" * 60 + "\n")


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    log.info("=== Instagram Saved Posts Downloader (Browser-only) ===")

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            USER_DATA_DIR,
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()

        page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
        time.sleep(2)

        username = page.evaluate("() => window._sharedData?.config?.viewer?.username")
        if not username:
            username = input("Could not detect username. Please enter: ").strip()
        log.info(f"Instagram username: {username}")

        ensure_logged_in(context, page, username)

        all_posts = load_set(ALL_POSTS_FILE)
        downloaded = load_set(DOWNLOADED_FILE)

        if not all_posts:
            log.info("First run – performing full saved-posts scan...")
            all_posts = full_scan_saved(page, username)
            save_set(ALL_POSTS_FILE, all_posts)
        else:
            log.info(f"Using cached {len(all_posts)} posts from all_posts.json.")

        to_download = sorted(all_posts - downloaded)
        log.info(f"Already downloaded: {len(downloaded)}, remaining: {len(to_download)}")

        if not to_download:
            log.info("All posts already downloaded.")
            print_completeness()
            context.close()
            return

        export_cookies(context, COOKIE_FILE)

        failed = []
        for shortcode in tqdm(to_download, desc="Downloading", unit="post"):
            try:
                success = process_post(shortcode, page, context, downloaded)
                if not success:
                    failed.append(shortcode)
            except Exception as e:
                log.error(f"Unexpected error on {shortcode}: {e}")
                failed.append(shortcode)
            time.sleep(0.8 + random.random() * 1.8)

        log.info("=" * 50)
        log.info(f"Attempted this run : {len(to_download)}")
        log.info(f"Total downloaded   : {len(downloaded)}")
        if failed:
            log.warning(f"Failed / skipped this run ({len(failed)}):")
            for sc in failed[:20]:
                log.warning(f"  - {sc}")
            if len(failed) > 20:
                log.warning(f"  ... and {len(failed)-20} more")

        print_completeness()
        context.close()


if __name__ == "__main__":
    main()
