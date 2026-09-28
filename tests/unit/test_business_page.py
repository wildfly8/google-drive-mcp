"""Public WisdomSpringTech page used for processor business-website checks."""

from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "docs" / "index.html"
SETUP = "https://onto-kb-kxjtmypvfa-uc.a.run.app/setup"


def test_business_page_names_wisdomspringtech_and_offer():
    html = PAGE.read_text(encoding="utf-8")
    assert "WisdomSpringTech" in html
    assert "onto-kb" in html
    assert "$20" in html or "USD 20" in html
    assert SETUP in html
    lowered = html.lower()
    assert "password" not in lowered
    assert "routing number" not in lowered
    assert "www.example.com" not in lowered
