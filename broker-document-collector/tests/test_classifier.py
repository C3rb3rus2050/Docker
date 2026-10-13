import pytest

from broker_collector.classifier import Classifier, parse_date, parse_labeled_date

clf = Classifier()


@pytest.mark.parametrize("title,expected", [
    ("Jahressteuerbescheinigung 2023", "Jahressteuerbescheinigung"),
    ("Steuerbescheinigung für das Jahr 2022", "Jahressteuerbescheinigung"),
    ("Vorabpauschale 2024", "Steuer"),
    ("Kontoauszug März 2024", "Kontoauszug"),
    ("Rechnungsabschluss Q1", "Kontoauszug"),
    ("Depotauszug zum 31.12.2023", "Depotauszug"),
    ("Wertpapierabrechnung Kauf Apple Inc.", "Kaufabrechnung"),
    ("Wertpapierabrechnung Verkauf Tesla", "Verkaufsabrechnung"),
    ("Sparplanausführung MSCI World", "Sparplan"),
    ("Dividende Microsoft Corp.", "Dividende"),
    ("Ausschüttung iShares Core MSCI", "Dividende"),
    ("Zinsabrechnung Oktober", "Zinsen"),
    ("Kosteninformation Ex-post 2023", "Gebühren"),
    ("Einzahlung per Lastschrift", "Einzahlung"),
    ("Auszahlung auf Referenzkonto", "Auszahlung"),
    ("Bestätigung der Kontoeröffnung", "Vertrag"),
    ("Kundenvereinbarung", "Vertrag"),
])
def test_titles(title, expected):
    assert clf.classify(title=title).category == expected


def test_unknown_when_no_evidence():
    c = clf.classify(title="XYZ-123")
    assert c.category == "Unbekannt" and c.confidence == 0.0 and c.folder == "Sonstige"


def test_ambiguous_goes_to_review():
    c = clf.classify(title="Kauf Verkauf")
    assert c.category == "Zu prüfen" and c.folder == "Zu_pruefen"


def test_pdf_text_used(pdf_factory):
    data = pdf_factory("Trade Republic Bank GmbH\nDIVIDENDE\nZahltag: 15.03.2024\nApple Inc.")
    c = clf.classify(title="Dokument", filename="doc_8f2.pdf", data=data)
    assert c.text_extracted
    assert c.category == "Dividende"
    assert c.doc_date == "2024-03-15"


def test_list_date_wins_over_text(pdf_factory):
    data = pdf_factory("Kontoauszug\nDatum: 01.02.2024")
    c = clf.classify(title="Kontoauszug", list_date="2024-01-31", data=data)
    assert c.doc_date == "2024-01-31"


def test_no_invented_date():
    c = clf.classify(title="Kontoauszug")
    assert c.doc_date == "" and c.year == ""
    c2 = clf.classify(title="Jahressteuerbescheinigung 2023")
    assert c2.doc_date == "" and c2.year == "2023"


def test_corrupt_pdf_does_not_crash():
    c = clf.classify(title="Abrechnung Kauf", data=b"%PDF-1.4 garbage %%EOF")
    assert c.category == "Kaufabrechnung"


def test_ocr_disabled_by_default():
    assert Classifier().ocr_enabled is False


@pytest.mark.parametrize("text,iso", [
    ("am 12.03.2024", "2024-03-12"),
    ("2023-12-31", "2023-12-31"),
    ("Datei_20240105.pdf", "2024-01-05"),
    ("5. März 2024", "2024-03-05"),
    ("31.02.2024", ""),
    ("ohne datum", ""),
])
def test_parse_date(text, iso):
    assert parse_date(text) == iso


def test_labeled_date_only():
    assert parse_labeled_date("ISIN DE000 Betrag 12.03.2024 xyz") == ""
    assert parse_labeled_date("Valuta: 12.03.2024") == "2024-03-12"
