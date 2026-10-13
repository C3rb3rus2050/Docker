import pytest

from broker_collector.broker_adapter import SafetyViolation
from broker_collector.discovery import (
    Element,
    assert_safe,
    document_candidates,
    expandable_entries,
    is_dangerous,
    is_direct_document_href,
    is_document_label,
    is_load_more,
    is_navigation_candidate,
    is_next_page,
    manual_request_candidates,
    navigation_candidates,
    year_options,
)


@pytest.mark.parametrize("label", [
    "Kaufen", "Jetzt kaufen", "Verkaufen", "Order aufgeben", "Überweisen", "Geld senden", "Auszahlen",
    "Sparplan anlegen", "Sparplan ändern", "Löschen", "Bestätigen", "Abmelden", "Logout", "Buy", "Sell",
    "Konto kündigen", "Karte sperren", "Einstellungen", "PIN ändern", "Dokument anfordern", "Handeln",
])
def test_dangerous(label):
    assert is_dangerous(label)


@pytest.mark.parametrize("label", [
    "Kaufabrechnung Apple", "Wertpapierabrechnung Verkauf", "Dividendenabrechnung", "Kontoauszug März",
    "Jahressteuerbescheinigung 2023", "PDF herunterladen", "Postfach", "Kosteninformation",
    "Bestätigung der Kontoeröffnung", "Mitteilung zur Kapitalmaßnahme",
])
def test_not_dangerous(label):
    assert not is_dangerous(label)


def test_label_rules():
    assert is_navigation_candidate("Dokumente")
    assert is_navigation_candidate("Postfach")
    assert not is_navigation_candidate("Einstellungen")
    assert not is_navigation_candidate("Aktien kaufen")
    assert is_document_label("Wertpapierabrechnung Kauf 12.03.2024")
    assert not is_document_label("Apple Inc.")
    assert is_load_more("Mehr laden") and is_load_more("Ältere Einträge anzeigen")
    assert not is_load_more("Jetzt mehr kaufen")
    assert is_next_page("Nächste Seite", False)
    assert is_next_page("Weiter", True)
    assert not is_next_page("Weiter", False)  # mehrdeutig außerhalb von Paginierung


def test_hrefs():
    assert is_direct_document_href("https://x.com/a/b.pdf?sig=1")
    assert is_direct_document_href("https://x.com/api/documents/123")
    assert is_direct_document_href("blob:https://x.com/1")
    assert not is_direct_document_href("mailto:a@b.c")
    assert not is_direct_document_href("https://x.com/portfolio")


def test_year_options():
    opts = [{"value": "all", "label": "Alle"}, {"value": "2024", "label": "2024"}, {"value": "y23", "label": "2023"}]
    assert [o["label"] for o in year_options(opts)] == ["2024", "2023"]


def el(id_, tag, label, **kw):
    return Element(id=id_, tag=tag, label=label, **kw)


def test_document_candidates():
    elements = [
        el("1", "a", "Dokumente", href="https://x.com/docs", in_nav=True),
        el("2", "a", "Abrechnung Kauf 12.03.2024", href="https://x.com/files/a.pdf"),
        el("3", "li", "Abrechnung Kauf 12.03.2024 PDF", has_clickable_child=True),
        el("4", "button", "PDF herunterladen", context="Kontoauszug Februar 2024 PDF herunterladen"),
        el("5", "button", "Kaufen"),
        el("6", "button", "Dividende Apple 01.04.2024"),
        el("7", "a", "Portfolio", href="https://x.com/portfolio"),
        el("8", "button", "Dokument senden", context="Kontoauszug"),
        el("9", "input", "Bestätigen", type="submit", form_has_inputs=True),
    ]
    cands = document_candidates(elements)
    titles = [c.title for c in cands]
    assert titles == ["Abrechnung Kauf 12.03.2024", "Kontoauszug Februar 2024 PDF herunterladen",
                      "Dividende Apple 01.04.2024"]
    assert cands[0].href and cands[0].date == "2024-03-12"
    assert cands[1].is_click and cands[1].date == ""
    assert cands[2].date == "2024-04-01"


def test_navigation_candidates():
    elements = [
        el("1", "a", "Dokumente", href="https://x.com/docs", in_nav=True),
        el("2", "a", "Dokumente", href="https://x.com/docs#", in_nav=True),
        el("3", "button", "Postfach", role="tab"),
        el("4", "a", "Aktien kaufen", href="https://x.com/buy", in_nav=True),
        el("5", "a", "Abmelden", href="https://x.com/logout", in_nav=True),
        el("6", "a", "Steuern", href="mailto:x@y.z", in_nav=True),
    ]
    assert [e.label for e in navigation_candidates(elements)] == ["Dokumente", "Postfach"]


def test_safety_assertion():
    with pytest.raises(SafetyViolation):
        assert_safe(el("1", "button", "Jetzt kaufen"))
    with pytest.raises(SafetyViolation):
        assert_safe(el("1", "button", "Weiter", form_has_inputs=True))
    with pytest.raises(SafetyViolation):
        assert_safe(el("1", "button", "PDF", context="Jetzt kaufen"))
    assert_safe(el("1", "button", "Mehr laden"))


def test_manual_and_expandable():
    elements = [
        el("1", "button", "Steuerbescheinigung anfordern"),
        el("2", "li", "Apple Inc. Kauf 12,00 €"),
        el("3", "li", "Mehr laden"),
        el("4", "li", "Tesla Verkaufen"),
    ]
    assert [e.label for e in manual_request_candidates(elements)] == ["Steuerbescheinigung anfordern"]
    assert [e.label for e in expandable_entries(elements)] == ["Apple Inc. Kauf 12,00 €"]
