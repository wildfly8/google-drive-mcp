"""Public WisdomSpringTech page used for processor business-website checks."""

from pathlib import Path

PAGE = Path(__file__).resolve().parents[2] / "docs" / "index.html"
SUBSCRIBE = "https://onto-kb-kxjtmypvfa-uc.a.run.app/subscribe"


def test_business_page_names_wisdomspringtech_and_offer():
    html = PAGE.read_text(encoding="utf-8")
    assert "WisdomSpringTech" in html
    assert "onto-kb" in html
    assert "AI chat app" in html
    assert "$20" in html or "USD 20" in html
    assert html.count(SUBSCRIBE) == 1
    assert "/setup" not in html
    lowered = html.lower()
    assert "only after payment" in lowered
    assert "the same receipt email is not charged again" in lowered
    assert "password" not in lowered
    assert "routing number" not in lowered
    assert "www.example.com" not in lowered
