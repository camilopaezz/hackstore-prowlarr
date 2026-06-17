#!/usr/bin/env python3
"""Reverse proxy for hackstore.fo — decrypts acortalink URLs and rewrites HTML."""

import copy
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, request

from decrypt_url import decrypt_acortalink

app = Flask(__name__)

UPSTREAM = "https://www.hackstore.fo"
PROXY_HOST = os.environ.get("PROXY_HOST", "http://192.168.1.91:8080")
CACHE_TTL = int(os.environ.get("DETAIL_CACHE_TTL", "3600"))
MAX_TIERS = int(os.environ.get("MAX_TIERS", "4"))
TMDB_API_KEY = os.environ.get("TMDB_API_KEY", "")
TMDB_LANGUAGES = os.environ.get("TMDB_LANGUAGES", "es-MX,es")
TMDB_TITLE_CACHE_TTL = int(os.environ.get("TMDB_TITLE_CACHE_TTL", "86400"))

_detail_cache = {}
_cache_lock = threading.Lock()
_tmdb_cache = {}

ACORTALINK_RE = re.compile(
    r'(<a\b[^>]*\shref=")https://acortalink\.net/s\.php\?i=([^"&]*)(")',
    re.IGNORECASE,
)

HEADING_SOURCE_RE = re.compile(r"\b(WEB-DL|BDRip|BluRay|BRRip|DVDRip|HDRip|WEBRip)\b", re.I)
HEADING_QUALITY_RE = re.compile(r"\b(4K|2160p|1080p|720p)\b", re.I)
HEADING_AUDIO_RE = re.compile(r"(Latino|Espa.ol).*?((?:E?-?AC3|AAC|DTS)\s*\d+\.\d+)", re.I)
MOVIE_TITLE_YEAR_RE = re.compile(r"^(.*?)\s*\((\d{4})\)$")


def parse_heading(heading_text):
    source = ""
    sm = HEADING_SOURCE_RE.search(heading_text)
    if sm:
        source = sm.group(1)

    quality = ""
    qm = HEADING_QUALITY_RE.search(heading_text)
    if qm:
        q = qm.group(1)
        if q.upper() == "2160P":
            q = "4K"
        elif q.upper() == "4K":
            q = "4K"
        quality = q

    audio = "Latino"
    am = HEADING_AUDIO_RE.search(heading_text)
    if am:
        audio = f"{am.group(1)} {am.group(2)}"

    return {"source": source, "quality": quality, "audio": audio}


def translate_query(query, post_type):
    """Translate an English query to Latin-American Spanish via TMDB API.

    Two-step approach to avoid skewed search results when using non-English
    languages for content with sparse translations (e.g. anime):
      1. Search TMDB without language param → get the correct TMDB ID
      2. Fetch /movie/{id} or /tv/{id} with language={es-MX} → get title

    Cached at two levels:
      - TMDB ID lookup: per (query, post_type) — shared across languages
      - Translated title: per (query, post_type, lang)
    Falls back to the original query on any error or if no match is found.
    """
    if not TMDB_API_KEY or not query:
        return query

    languages = [lang.strip() for lang in TMDB_LANGUAGES.split(",") if lang.strip()]
    if not languages:
        return query

    if post_type in ("tvshows", "animes"):
        search_endpoint = "/search/tv"
        detail_endpoint = "/tv"
        result_key = "name"
    else:
        search_endpoint = "/search/movie"
        detail_endpoint = "/movie"
        result_key = "title"

    id_cache_key = f"__id__{query}|{post_type}"
    tmdb_id = None
    id_expired = True

    for lang in languages:
        title_cache_key = f"{query}|{post_type}|{lang}"
        with _cache_lock:
            cached = _tmdb_cache.get(title_cache_key)
            if cached and time.time() < cached["expires"]:
                title = cached["title"]
                if title and title.lower() != query.lower():
                    return title
                continue

        try:
            # Step 1: resolve TMDB ID (once, shared across language chain)
            if tmdb_id is None:
                with _cache_lock:
                    id_entry = _tmdb_cache.get(id_cache_key)
                    if id_entry and time.time() < id_entry.get("expires", 0):
                        tmdb_id = id_entry["tmdb_id"]
                        id_expired = False

                if tmdb_id is None or id_expired:
                    resp = requests.get(
                        f"https://api.themoviedb.org/3{search_endpoint}",
                        params={"api_key": TMDB_API_KEY, "query": query},
                        timeout=10,
                    )
                    resp.raise_for_status()
                    results = resp.json().get("results", [])

                    if not results:
                        # Nothing found — bubble-empty cache for all languages
                        for l in languages:
                            with _cache_lock:
                                _tmdb_cache[f"{query}|{post_type}|{l}"] = {
                                    "expires": time.time() + TMDB_TITLE_CACHE_TTL,
                                    "title": "",
                                }
                        return query

                    tmdb_id = results[0]["id"]
                    with _cache_lock:
                        _tmdb_cache[id_cache_key] = {
                            "expires": time.time() + TMDB_TITLE_CACHE_TTL,
                            "tmdb_id": tmdb_id,
                        }

            # Step 2: fetch localized title
            resp = requests.get(
                f"https://api.themoviedb.org/3{detail_endpoint}/{tmdb_id}",
                params={"api_key": TMDB_API_KEY, "language": lang},
                timeout=10,
            )
            resp.raise_for_status()
            title = resp.json().get(result_key, "")

            with _cache_lock:
                _tmdb_cache[title_cache_key] = {
                    "expires": time.time() + TMDB_TITLE_CACHE_TTL,
                    "title": title,
                }

            if title and title.lower() != query.lower():
                return title
        except Exception:
            continue

    return query


def extract_tiers(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    headings = soup.select(".accordion__heading.accordion")
    tiers = []
    seen = set()
    for heading in headings:
        text = heading.get_text(" ", strip=True)
        if not text:
            continue
        tier = parse_heading(text)
        key = (tier["source"], tier["quality"], tier["audio"])
        if key in seen:
            continue
        seen.add(key)
        panel = heading.find_next_sibling("div", class_="panel")
        size_td = panel.select_one("td.fuente-td") if panel else None
        tier["size"] = size_td.get_text(strip=True) if size_td else ""
        tiers.append(tier)
    return tiers


def build_enriched_title(raw_title, tier):
    m = MOVIE_TITLE_YEAR_RE.match(raw_title.strip())
    if not m:
        return raw_title
    name = m.group(1).replace(":", "").replace("  ", " ").strip()
    year = m.group(2)
    parts = [name, year]
    src = tier.get("source", "")
    q = tier.get("quality", "")
    if src:
        parts.append(src)
    if q:
        parts.append(q)
    parts.append("Latino")
    return ".".join(parts)


def _prefetch_details(urls):
    def _fetch_one(url):
        with _cache_lock:
            cached = _detail_cache.get(url)
            if cached and time.time() < cached["expires"]:
                return
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept-Encoding": "gzip, deflate",
                },
                timeout=20,
            )
            if "text/html" in resp.headers.get("Content-Type", "").lower():
                tiers = extract_tiers(resp.text)
            else:
                tiers = []
        except Exception:
            tiers = []
        with _cache_lock:
            _detail_cache[url] = {
                "expires": time.time() + CACHE_TTL,
                "tiers": tiers,
            }

    urls = list(set(urls))
    if not urls:
        return
    with ThreadPoolExecutor(max_workers=min(len(urls), 10)) as executor:
        futures = {executor.submit(_fetch_one, u): u for u in urls}
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                pass


def enrich_listing_page(html_text):
    soup = BeautifulSoup(html_text, "html.parser")
    thumbs = soup.select("#movies-block-main .movie-thumbnail")
    if not thumbs:
        return html_text

    detail_urls = []
    for thumb in thumbs:
        a_tag = thumb.select_one("h3 a.movie-title")
        if a_tag and a_tag.get("href"):
            detail_urls.append(a_tag["href"])
        else:
            detail_urls.append(None)

    _prefetch_details([u for u in detail_urls if u])

    for i, thumb in enumerate(thumbs):
        detail_url = detail_urls[i]
        if not detail_url:
            continue
        a_tag = thumb.select_one("h3 a.movie-title")
        if not a_tag:
            continue
        raw_title = a_tag.get("title", "") or a_tag.get_text(strip=True)
        if not raw_title:
            continue

        with _cache_lock:
            cached = _detail_cache.get(detail_url, {})
        tiers = cached.get("tiers", []) if time.time() < cached.get("expires", 0) else []
        tiers = tiers[:MAX_TIERS]

        if not tiers:
            parts = raw_title.replace(":", "").replace("(", ".").replace(")", "").split(".")
            parts = [p.strip() for p in parts if p.strip()]
            enriched = ".".join(parts + ["Latino"])
            a_tag["title"] = enriched
            continue

        clones = []
        for j, tier in enumerate(tiers):
            clone = copy.copy(thumb)
            clone_a = clone.select_one("h3 a.movie-title")
            if clone_a:
                enriched = build_enriched_title(raw_title, tier)
                clone_a["title"] = enriched
                clone_a["data-size"] = tier.get("size", "")
                parsed = urlparse(detail_url)
                clone_a["href"] = parsed.path + f"?_tier={j}" + (("&" + parsed.query) if parsed.query else "")
            clones.append(clone)

        parent = thumb.parent
        if parent:
            idx = list(parent.children).index(thumb)
            thumb.decompose()
            for j, clone in enumerate(clones):
                parent.insert(idx + j, clone)

    return str(soup)


def filter_detail_page(html_text, tier_index):
    soup = BeautifulSoup(html_text, "html.parser")
    headings = soup.select(".accordion__heading.accordion")
    for i, heading in enumerate(headings):
        if i != tier_index:
            panel = heading.find_next_sibling("div", class_="panel")
            if panel:
                panel.decompose()
            heading.decompose()
    return str(soup)


def _is_listing_page(path, query_string):
    if path.rstrip("/") in ("peliculas", "series", "animes"):
        return True
    if "s=" in query_string:
        return True
    return False


def rewrite_html(html_text):
    def replace_acortalink(m):
        encoded = m.group(2)
        try:
            real_url = decrypt_acortalink(encoded)
        except Exception:
            return m.group(0)
        return f"{m.group(1)}{real_url}{m.group(3)}"

    html_text = ACORTALINK_RE.sub(replace_acortalink, html_text)

    def rewrite_url(m):
        attr = m.group(1)
        url = m.group(2)

        if url.startswith("data:") or url.startswith("#"):
            return m.group(0)
        if "acortalink.net" in url:
            return m.group(0)

        parsed = urlparse(url)
        if parsed.netloc in (
            "www.hackstore.fo",
            "hackstore.fo",
            "",
        ) and not parsed.scheme in ("", "http", "https"):
            pass

        if parsed.netloc in ("www.hackstore.fo", "hackstore.fo"):
            new_url = PROXY_HOST + (parsed.path or "/")
            if parsed.query:
                new_url += "?" + parsed.query
            return f"{attr}{new_url}"

        if url.startswith("/"):
            new_url = PROXY_HOST + url
            return f"{attr}{new_url}"

        return m.group(0)

    ATTR_RE = re.compile(r"""(\b(?:src|href|action)=["'])([^"']*)""", re.IGNORECASE)
    html_text = ATTR_RE.sub(rewrite_url, html_text)

    html_text = tag_quality_tables(html_text)

    return html_text


QUALITY_TABLE_RE = re.compile(
    r'(<div\s+class="[^"]*\baccordion__heading\b[^"]*"[^>]*>(.*?)</div>\s*'
    r'<div\s+class="[^"]*\bpanel\b[^"]*"[^>]*>.*?)'
    r'(<table\s+[^>]*class="[^"]*\bnewtab\b[^"]*"[^>]*>)',
    re.DOTALL | re.IGNORECASE,
)


def tag_quality_tables(html_text):
    def replacer(m):
        heading_html = m.group(1)
        heading_text = m.group(2)
        table_tag = m.group(3)

        heading_visible = re.sub(r"<[^>]*>", " ", heading_text)
        heading_visible = re.sub(r"\s+", " ", heading_visible).strip()
        tier = parse_heading(heading_visible)

        quality = tier["quality"] or "other"
        source = tier["source"] or ""
        audio = tier["audio"] or "Latino"

        new_table = table_tag.replace(
            "<table", f'<table data-quality="{quality}"', 1
        )
        if source:
            new_table = new_table.replace(
                "<table", f'<table data-source="{source}"', 1
            )
        new_table = new_table.replace(
            "<table", f'<table data-audio="{audio}"', 1
        )
        return heading_html + new_table

    return QUALITY_TABLE_RE.sub(replacer, html_text)


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "HEAD", "OPTIONS"])
def proxy(path):
    qs = request.query_string.decode("utf-8")
    parsed_qs = parse_qs(qs, keep_blank_values=True)
    tier_index = None
    if "_tier" in parsed_qs:
        tier_index = int(parsed_qs.pop("_tier")[0])

    if "s" in parsed_qs:
        original = parsed_qs["s"][0]
        post_type = parsed_qs.get("post_type", ["movies"])[0]
        translated = translate_query(original, post_type)
        if translated != original:
            parsed_qs["s"] = [translated]

    flat_qs = urlencode(parsed_qs, doseq=True) if parsed_qs else ""

    target_url = UPSTREAM.rstrip("/") + "/" + path
    if flat_qs:
        target_url += "?" + flat_qs

    headers = {
        k: v
        for k, v in request.headers
        if k.lower() not in ("host", "connection", "accept-encoding")
    }
    headers["Host"] = "www.hackstore.fo"
    headers["Accept-Encoding"] = "gzip, deflate"
    headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    )

    upstream_resp = requests.request(
        method=request.method,
        url=target_url,
        headers=headers,
        data=request.get_data() if request.method in ("POST",) else None,
        cookies=request.cookies,
        allow_redirects=False,
        stream=True,
    )

    if upstream_resp.status_code in (301, 302, 303, 307, 308):
        location = upstream_resp.headers.get("Location", "")
        if location:
            parsed = urlparse(location)
            if parsed.netloc in ("www.hackstore.fo", "hackstore.fo"):
                location = PROXY_HOST + (parsed.path or "/")
                if parsed.query:
                    location += "?" + parsed.query
            elif location.startswith("/"):
                location = PROXY_HOST + location
        excluded = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
        ]
        resp_headers = [
            (k, v)
            for k, v in upstream_resp.headers.items()
            if k.lower() not in excluded
        ]
        return Response(
            status=upstream_resp.status_code, headers={"Location": location}
        )

    content_type = upstream_resp.headers.get("Content-Type", "").lower()
    excluded = ["content-encoding", "content-length", "transfer-encoding", "connection"]
    resp_headers = [
        (k, v) for k, v in upstream_resp.headers.items() if k.lower() not in excluded
    ]

    if upstream_resp.status_code >= 400:
        return Response(
            upstream_resp.content,
            status=upstream_resp.status_code,
            headers=resp_headers,
        )

    if "text/html" in content_type:
        html_text = upstream_resp.text
        if tier_index is not None:
            html_text = filter_detail_page(html_text, tier_index)
        elif _is_listing_page(path, qs):
            html_text = enrich_listing_page(html_text)
        html_text = rewrite_html(html_text)
        return Response(
            html_text, status=upstream_resp.status_code, headers=resp_headers
        )

    return Response(
        upstream_resp.content,
        status=upstream_resp.status_code,
        headers=resp_headers,
    )


if __name__ == "__main__":
    print(f"Proxy running at {PROXY_HOST} -> {UPSTREAM}")
    app.run(host="0.0.0.0", port=8080, debug=False)
