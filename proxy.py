#!/usr/bin/env python3
"""Reverse proxy for hackstore.fo — decrypts acortalink URLs and rewrites HTML."""

import re
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import requests
from flask import Flask, Response, request

from decrypt_url import decrypt_acortalink

app = Flask(__name__)

UPSTREAM = "https://www.hackstore.fo"
PROXY_HOST = "http://localhost:8080"

ACORTALINK_RE = re.compile(
    r'(<a\b[^>]*\shref=")https://acortalink\.net/s\.php\?i=([^"&]*)(")',
    re.IGNORECASE,
)


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

    return html_text


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "HEAD", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "HEAD", "OPTIONS"])
def proxy(path):
    target_url = UPSTREAM.rstrip("/") + "/" + path
    if request.query_string:
        target_url += "?" + request.query_string.decode("utf-8")

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
