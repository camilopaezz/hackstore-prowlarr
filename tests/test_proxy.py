import time

from bs4 import BeautifulSoup

import proxy
from proxy import (
    _detail_cache,
    _is_listing_page,
    build_enriched_title,
    enrich_listing_page,
    extract_tiers,
    filter_detail_page,
    get_english_title,
    parse_heading,
    rewrite_html,
    translate_query,
)


def test_parse_heading_extracts_metadata():
    assert parse_heading("WEB-DL 1080p Latino AAC 5.1") == {
        "source": "WEB-DL",
        "quality": "1080p",
        "audio": "Latino AAC 5.1",
    }


def test_build_enriched_title_keeps_year_and_tier():
    assert (
        build_enriched_title(
            "Movie Name (2026)", {"source": "WEB-DL", "quality": "1080p"}
        )
        == "Movie Name.2026.WEB-DL.1080p.Latino"
    )


def test_extract_tiers_deduplicates_matching_entries():
    html = """
    <div class="accordion__heading accordion">WEB-DL 1080p Latino AAC 5.1</div>
    <div class="panel"><td class="fuente-td">1.2 GB</td></div>
    <div class="accordion__heading accordion">WEB-DL 1080p Latino AAC 5.1</div>
    <div class="panel"><td class="fuente-td">1.2 GB</td></div>
    <div class="accordion__heading accordion">WEBRip 720p Latino AAC 2.0</div>
    <div class="panel"><td class="fuente-td">800 MB</td></div>
    """

    tiers = extract_tiers(html)

    assert tiers == [
        {
            "source": "WEB-DL",
            "quality": "1080p",
            "audio": "Latino AAC 5.1",
            "_heading_idx": 0,
            "size": "1.2 GB",
        },
        {
            "source": "WEBRip",
            "quality": "720p",
            "audio": "Latino AAC 2.0",
            "_heading_idx": 2,
            "size": "800 MB",
        },
    ]


def test_filter_detail_page_keeps_only_selected_tier():
    html = """
    <div class="accordion__heading accordion">One</div><div class="panel">A</div>
    <div class="accordion__heading accordion">Two</div><div class="panel">B</div>
    <div class="accordion__heading accordion">Three</div><div class="panel">C</div>
    """

    filtered = filter_detail_page(html, 1)

    assert "Two" in filtered
    assert "One" not in filtered
    assert "Three" not in filtered


def test_is_listing_page_matches_expected_paths():
    assert _is_listing_page("peliculas", "") is True
    assert _is_listing_page("foo", "s=test") is True
    assert _is_listing_page("foo", "") is False


def test_rewrite_html_rewrites_proxy_links_and_decrypts_acortalink(monkeypatch):
    monkeypatch.setattr(  # noqa: E501
        "proxy.decrypt_acortalink", lambda encoded: "magnet:?xt=urn:btih:xyz"
    )

    html = (
        '<a href="https://acortalink.net/s.php?i=abc">dl</a>'
        '<a href="/peliculas/test">relative</a>'
        '<img src="https://www.hackstore.fo/media/x.png">'
        '<a href="#anchor">anchor</a>'
    )

    rewritten = rewrite_html(html, base_url="http://proxy.local:8080")

    assert 'href="magnet:?xt=urn:btih:xyz"' in rewritten
    assert 'href="http://proxy.local:8080/peliculas/test"' in rewritten
    assert 'src="http://proxy.local:8080/media/x.png"' in rewritten
    assert 'href="#anchor"' in rewritten


def test_enrich_listing_page_clones_result_per_cached_tier(monkeypatch):
    monkeypatch.setattr("proxy._prefetch_details", lambda urls: None)
    monkeypatch.setattr("proxy.MAX_TIERS", 4)

    detail_url = "/peliculas/movie-name-2026/"
    _detail_cache.clear()
    _detail_cache[detail_url] = {
        "expires": time.time() + 60,
        "tiers": [
            {
                "source": "WEB-DL",
                "quality": "4K",
                "audio": "Latino E-AC3 5.1",
                "_heading_idx": 0,
                "size": "8 GB",
            },
            {
                "source": "WEBRip",
                "quality": "1080p",
                "audio": "Latino AAC 2.0",
                "_heading_idx": 2,
                "size": "2 GB",
            },
        ],
    }
    html = f"""
    <div id="movies-block-main">
      <article class="movie-thumbnail">
        <h3>
          <a class="movie-title" href="{detail_url}" title="Movie Name (2026)">
            Movie Name (2026)
          </a>
        </h3>
      </article>
    </div>
    """

    enriched = enrich_listing_page(html)
    soup = BeautifulSoup(enriched, "html.parser")
    links = soup.select("#movies-block-main .movie-thumbnail h3 a.movie-title")

    assert [link["title"] for link in links] == [
        "Movie Name.2026.WEB-DL.4K.Latino",
        "Movie Name.2026.WEBRip.1080p.Latino",
    ]
    assert [link["href"] for link in links] == [
        "/peliculas/movie-name-2026/?_tier=0",
        "/peliculas/movie-name-2026/?_tier=2",
    ]
    assert [link["data-size"] for link in links] == ["8 GB", "2 GB"]


def test_enrich_listing_page_uses_english_title_when_translation_was_used(monkeypatch):
    monkeypatch.setattr("proxy._prefetch_details", lambda urls: None)

    detail_url = "/peliculas/una-pelicula-2026/"
    _detail_cache.clear()
    _detail_cache[detail_url] = {
        "expires": time.time() + 60,
        "tiers": [
            {
                "source": "WEB-DL",
                "quality": "720p",
                "audio": "Latino AAC 2.0",
                "_heading_idx": 0,
                "size": "900 MB",
            }
        ],
    }
    html = f"""
    <div id="movies-block-main">
      <article class="movie-thumbnail">
        <h3>
          <a class="movie-title" href="{detail_url}" title="Una Pelicula (2026)">
            Una Pelicula (2026)
          </a>
        </h3>
      </article>
    </div>
    """

    enriched = enrich_listing_page(html, english_title="Original Movie")
    title = BeautifulSoup(enriched, "html.parser").select_one("a.movie-title")["title"]

    assert title == "Original Movie.2026.WEB-DL.720p.Latino"


class _FakeResponse:
    def __init__(
        self,
        *,
        text="",
        content=None,
        status_code=200,
        headers=None,
        json_data=None,
    ):
        self.text = text
        self.content = content if content is not None else text.encode()
        self.status_code = status_code
        self.headers = headers or {}
        self._json_data = json_data or {}

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_proxy_route_strips_tier_before_upstream_and_filters_detail(monkeypatch):
    captured = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        return _FakeResponse(
            text="""
            <div class="accordion__heading accordion">One</div>
            <div class="panel">A</div>
            <div class="accordion__heading accordion">Two</div>
            <div class="panel">B</div>
            """,
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    monkeypatch.setattr("proxy.requests.request", fake_request)

    response = proxy.app.test_client().get("/peliculas/example/?_tier=1&foo=bar")

    assert response.status_code == 200
    assert captured["url"] == "https://www.hackstore.fo/peliculas/example/?foo=bar"
    assert b"Two" in response.data
    assert b"One" not in response.data


def test_proxy_route_rejects_invalid_tier_before_upstream(monkeypatch):
    def fake_request(**kwargs):
        raise AssertionError("upstream should not be called for invalid _tier")

    monkeypatch.setattr("proxy.requests.request", fake_request)

    response = proxy.app.test_client().get("/peliculas/example/?_tier=bad")

    assert response.status_code == 400
    assert response.data == b"Invalid tier"


def test_translate_query_uses_tmdb_detail_title_and_caches_english_title(monkeypatch):
    proxy._tmdb_cache.clear()
    monkeypatch.setattr("proxy.TMDB_API_KEY", "test-key")
    monkeypatch.setattr("proxy.TMDB_LANGUAGES", "es-MX,es")
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        if url.endswith("/search/movie"):
            return _FakeResponse(
                json_data={"results": [{"id": 123, "title": "Original Movie"}]}
            )
        if url.endswith("/movie/123") and params["language"] == "es-MX":
            return _FakeResponse(json_data={"title": "Pelicula Original"})
        raise AssertionError(f"unexpected TMDB request: {url} {params}")

    monkeypatch.setattr("proxy.requests.get", fake_get)

    assert translate_query("Original Movie", "movies") == "Pelicula Original"
    assert get_english_title("Original Movie", "movies") == "Original Movie"
    assert translate_query("Original Movie", "movies") == "Pelicula Original"
    assert len(calls) == 2
