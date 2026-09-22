"""Bundle path checks for report artifacts. No MinIO connection."""

from artifacts import decode_bundle_files, safe_bundle_path


def test_safe_bundle_path_allows_report_layout():
    assert safe_bundle_path("report.html") == "report.html"
    assert safe_bundle_path("assets/charts/psnr.svg") == "assets/charts/psnr.svg"
    assert safe_bundle_path("assets/diagrams/outline.svg") == "assets/diagrams/outline.svg"
    assert safe_bundle_path(r"assets\images\a.png") == "assets/images/a.png"
    assert safe_bundle_path("deck.pptx") == "deck.pptx"
    assert safe_bundle_path("report.pptx") == "report.pptx"


def test_safe_bundle_path_rejects_escape():
    assert safe_bundle_path("../secret.txt") is None
    assert safe_bundle_path("assets/charts/../../report.html") is None
    assert safe_bundle_path("/etc/passwd") is None
    assert safe_bundle_path("notes.md") is None


def test_decode_bundle_files_skips_unsafe_entries():
    decoded = decode_bundle_files(
        {
            "report.html": "<html></html>",
            "../x": "nope",
            "report.pdf": {"encoding": "base64", "content": "YQ==", "mime": "application/pdf"},
        }
    )
    names = [item[0] for item in decoded]
    assert names == ["report.html", "report.pdf"]
    assert decoded[1][1] == b"a"


def test_decode_deck_pptx_base64():
    decoded = decode_bundle_files(
        {
            "deck.pptx": {
                "encoding": "base64",
                "content": "UEsDBBQAAAA=",  # minimal base64 (PK..)
                "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }
        }
    )
    assert len(decoded) == 1
    assert decoded[0][0] == "deck.pptx"
    assert decoded[0][2].startswith("application/vnd.openxmlformats")
    assert decoded[0][1][:2] == b"PK"


def test_safe_bundle_path_allows_pptx():
    assert safe_bundle_path("deck.pptx") == "deck.pptx"
    assert safe_bundle_path("report.pptx") == "report.pptx"


def test_decode_bundle_files_pptx_base64():
    decoded = decode_bundle_files(
        {
            "deck.pptx": {
                "encoding": "base64",
                "content": "UEsDBAoAAAAA",  # PK zip prefix padded
                "mime": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            }
        }
    )
    assert len(decoded) == 1
    assert decoded[0][0] == "deck.pptx"
    assert "presentationml" in decoded[0][2]
