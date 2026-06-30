from urllib.parse import urlparse

from bs4 import BeautifulSoup

from proxy import app


def test_hackstore_proxy_listing_and_detail_e2e():
    client = app.test_client()

    listing = client.get("/peliculas/")
    assert listing.status_code == 200
    listing_soup = BeautifulSoup(listing.data, "html.parser")

    thumb = listing_soup.select_one("#movies-block-main .movie-thumbnail")
    assert thumb is not None

    link = listing_soup.select_one(
        "#movies-block-main .movie-thumbnail h3 a.movie-title"
    )
    assert link is not None
    href = link.get("href", "")
    assert href.startswith("http://localhost")

    parsed = urlparse(href)
    detail_path = parsed.path
    if parsed.query:
        detail_path += f"?{parsed.query}"

    detail = client.get(detail_path)
    assert detail.status_code == 200
    detail_soup = BeautifulSoup(detail.data, "html.parser")

    assert detail_soup.select_one(".accordion__heading.accordion") is not None
    assert detail_soup.select_one("table.newtab a.btn-slide") is not None
    assert b"magnet:" in detail.data
