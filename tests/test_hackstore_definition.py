from pathlib import Path


def test_hackstore_definition_keeps_required_download_contract():
    definition = Path("hackstore.yml").read_text()

    assert "download:" in definition
    assert 'text: "{{ .Result.details }}"' in definition
    assert "selectors:" in definition
    assert 'selector: "table.newtab a.btn-slide"' in definition
    assert "categories: [2000]" in definition
    assert "categories: [5000]" in definition
    assert "categories: [5070]" in definition
