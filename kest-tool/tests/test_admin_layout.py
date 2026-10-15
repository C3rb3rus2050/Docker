"""Ensure all KESt navigation destinations use the same admin layout."""
from __future__ import annotations

from kest_tool.ui.admin_theme import SECTIONS, render_page_header


def test_all_navigation_destinations_have_header():
    assert set(SECTIONS) == {
        "dashboard", "import", "dokumente", "transaktionen", "wertpapiere",
        "fonds", "depots", "steuer", "exporte", "einstellungen",
    }


def test_page_header_is_html_escaped(monkeypatch):
    import kest_tool.ui.admin_theme as theme
    received = []
    monkeypatch.setattr(theme.st, "markdown", lambda html, **kw: received.append(html))
    monkeypatch.setitem(theme.SECTIONS, "test", ("<section>", "<title>", "A & B"))
    render_page_header("test")
    assert "&lt;section&gt;" in received[0]
    assert "&lt;title&gt;" in received[0]
    assert "A &amp; B" in received[0]
    assert "<title>" not in received[0]
