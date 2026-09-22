"""Bundle path checks for report artifacts. No MinIO connection."""

from artifacts import decode_bundle_files, safe_bundle_path


def test_safe_bundle_path_allows_report_layout():
    assert safe_bundle_path("report.html") == "report.html"
    assert safe_bundle_path("assets/charts/psnr.svg") == "assets/charts/psnr.svg"
    assert safe_bundle_path("assets/diagrams/outline.svg") == "assets/diagrams/outline.svg"
    assert safe_bundle_path(r"assets\images\a.png") == "assets/images/a.png"


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
