from proxy import (
    _is_listing_page,
    build_enriched_title,
    extract_tiers,
    filter_detail_page,
    parse_heading,
    rewrite_html,
    tag_quality_tables,
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


def test_tag_quality_tables_adds_metadata_attributes():
    html = (
        '<div class="accordion__heading accordion">WEB-DL 1080p Latino AAC 5.1</div>'
        '<div class="panel"><table class="newtab"><tr><td>x</td></tr></table></div>'
    )

    tagged = tag_quality_tables(html)

    assert 'data-quality="1080p"' in tagged
    assert 'data-source="WEB-DL"' in tagged
    assert 'data-audio="Latino AAC 5.1"' in tagged
