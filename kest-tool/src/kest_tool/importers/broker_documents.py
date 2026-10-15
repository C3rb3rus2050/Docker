"""Document families identified from public Trade Republic/Scalable layouts.

Only document headings classify summaries or special events. Security names and
legal footnotes must not turn a trade into a dividend, transfer or tax report.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentProfile:
    doc_type: str
    policy: str  # info | review | transaction
    explanation: str
    action: str = ''


def document_profile(text: str) -> DocumentProfile | None:
    # Public extractor fixtures prepend version metadata; real PDFs have addresses.
    flags = re.I | re.M
    header = re.split(r'(?im)^\s*(?:ÜBERSICHT|OVERVIEW|BUCHUNGEN|ABRECHNUNG|'
                      r'Typ Wertpapier Anzahl Kurs Betrag|POSITION ANZAHL KURS BETRAG)\s*$', text, maxsplit=1)[0]
    singular = re.search(r'(?im)^\s*(?:Wertpapierabrechnung(?:\s*[:–-]\s*(?:Kauf|Verkauf|Buy|Sell))?|'
                         r'Dividendenabrechnung[^\n]*|Dividende|Ausschüttung|Ertragsabrechnung[^\n]*|Ausschüttungsabrechnung[^\n]*)\s*$', header)
    if singular:
        header = header[:singular.end()]
    header = re.split(r'(?im)^\s*(?:Nominale\b|Berechtigtes Wertpapier\b|ISIN\b)', header, maxsplit=1)[0]
    def heading(pattern):
        return re.search(r'^\s*(?:' + pattern + r')(?:\s.*)?$', header, flags)
    if heading(r'(?:storno|stornierung|cancellation)(?:[- :].*)?|stornoabrechnung') or re.search(
            r'(?im)^.*(?:STORNO DER ABRECHNUNG|CANCELLATION OF (?:TRADE|DIVIDEND)).*$', text):
        return DocumentProfile('Storno', 'review', 'Storno hebt eine frühere Abrechnung auf.',
                               'Ursprüngliche Buchung und Stornobeleg gemeinsam vergleichen und berichtigen.')
    if heading(r'(?:Jahres)?steuerbescheinigung|Jahressteuerbericht|Steuerreport(?: für Österreich)?|'
               r'Erträgnisaufstellung|Verlustbescheinigung|Annual tax (?:statement|report)|Tax certificate'):
        return DocumentProfile('Jahressteuerbescheinigung', 'review',
            'Steuerübersicht mit mehreren Vorgängen; keine zusätzliche Einzelbuchung.',
            'Mit den bereits erfassten Einzelabrechnungen vergleichen; keine Summen doppelt buchen.')
    if heading(r'(?:EX[- ]ANTE|EX[- ]POST).*|Kosteninformation.*|Kostenausweis.*|'
               r'(?:Pre[- ]trade|Ex[- ]ante|Ex[- ]post) cost.*|Basisinformationsblatt|Key information document'):
        return DocumentProfile('Kosteninformation', 'info',
                               'Kostenübersicht oder Prognose; belegt keine ausgeführte Buchung.')
    if heading(r'(?:Perioden[- ]|Tages[- ])?Kontoauszug.*|Kontoübersicht.*|Cash Account Statement.*|Account statement.*|'
               r'Statement of account.*|AccountStatementSummary.*|KONTOAUSZUG ZUSAMMENFASSUNG|'
               r'RELEVÉ DE COMPTE.*|RELEVE DE COMPTE.*|EXTRACTO DE (?:CUENTA|EFECTIVO).*|'
               r'ESTRATTO CONTO.*|SYNTHÈSE DU COMPTE.*|RESUMEN DE ESTADO DE CUENTA.*'):
        return DocumentProfile('Kontoauszug', 'info',
            'Kontoübersicht; Nettobewegungen werden nicht als zusätzliche Bruttobuchungen übernommen.',
            'Für Wertpapiererträge die zugehörigen Einzelabrechnungen verwenden.')
    if heading(r'Depotauszug.*|Depotübersicht.*|Vermögensübersicht.*|Securities statement.*|Portfolio statement.*'):
        return DocumentProfile('Depotauszug', 'info', 'Bestandsübersicht ohne Kaufhistorie und Anschaffungskosten.')
    if heading(r'.*Vorabpauschale.*|Preliminary lump sum.*|Advance tax.*'):
        return DocumentProfile('Vorabpauschale (DE)', 'info',
                               'Deutsche Vorabpauschale als separater Beleg erkannt; keine österreichische Ertragsbuchung.')
    if heading(r'Steuer(?:abrechnung|optimierung|korrektur|neuberechnung|ausgleichsrechnung|erstattung).*|Steuerliche Optimierung.*|'
               r'Reklassifizierung.*|Tax (?:correction|refund|recalculation|optimization).*') or re.search(
               r'(?im)^Steuerkorrektur für Rechnung', text):
        return DocumentProfile('Steuerkorrektur', 'review',
            'Steuerkorrektur oder Reklassifizierung betrifft frühere Abrechnungen.',
            'Mit der ursprünglichen Buchung abgleichen; deutsche Steuer nicht als österreichische KESt übernehmen.')
    if heading(r'(?:Depotübertrag|Depoteinlieferung|Depotauslieferung|Einbuchung|Ausbuchung).*|'
               r'(?:Eingehender|Ausgehender) Depotübertrag.*|Securities transfer.*|Portfolio transfer.*'):
        return DocumentProfile('Depotübertrag', 'review',
            'Depotübertrag verändert den Bestand; Anschaffungsdaten und Gegenbuchung sind erforderlich.',
            'Ein- und Ausgang sowie ursprüngliches Kaufdatum und Anschaffungskosten prüfen.')
    if heading(r'(?:Aktien)?split.*|Reverse split.*|Spin[- ]?off.*|Fusion.*|Verschmelzung.*|'
               r'(?:Steuerlicher )?(?:Titel)?umtausch.*|Kapital(?:erhöhung|reduktion|herabsetzung|maßnahme).*|'
               r'Tilgung.*|Gesamtrückzahlung.*|Repayment.*|Zwangsübernahme.*|Squeeze[- ]?out.*|Vergleichsverfahren.*|Knock Out|Laufzeitende|Zeichnung|Reinvestierung|Ausübung von Optionsscheinen'):
        return DocumentProfile('Kapitalmaßnahme', 'review',
            'Kapitalmaßnahme oder Tilgung mit möglichen Bestands- und Kostenänderungen.',
            'Verhältnis, Gegenleistung und ursprüngliche Anschaffungskosten im Original prüfen.')
    if heading(r'ABRECHNUNG CRYPTO.*|CRYPTO(?:CURRENCY)? (?:TRADE|TRANSACTION).*'):
        return DocumentProfile('Kryptoabrechnung', 'review',
            'Kryptogeschäft erkannt; nicht als Wertpapiergeschäft mit erfundener ISIN übernehmen.',
            'Kryptoabrechnung gesondert prüfen.')
    interest = heading(r'ABRECHNUNG(?:\s*[-–])? ZINSEN|ZINSABRECHNUNG|ZINSZAHLUNG|INTEREST INVOICE|INTEREST STATEMENT')
    closing = heading(r'Rechnungsabschluss.*|Statement of interest and charges.*')
    if interest and re.search(r'(?im)^(?:ABRECHNUNG\s*[-–]\s*DIVIDENDE|Geldmarkt\s+Dividende)', text):
        return DocumentProfile('Sammelabrechnung', 'review',
            'Zinsen und Geldmarkterträge stehen gemeinsam im Dokument.',
            'Die getrennt erkannten Ertragsbestandteile prüfen; keine Gesamtsumme als einzelne Dividende buchen.')
    if interest or (closing and re.search(r'(?im)^(?:Habenzinsen|Credit Interest)\s', text)):
        return DocumentProfile('Zinsabrechnung', 'transaction', 'Abrechnung von Guthabenzinsen erkannt.')
    if closing:
        return DocumentProfile('Kontoauszug', 'info', 'Rechnungsabschluss ohne eindeutig ausgewiesene Guthabenzinsen.')
    if heading(r'ABRECHNUNG EINZAHLUNG|ÜBERWEISUNGSDETAILS|TRANSFER DETAILS|PAYMENT CONFIRMATION'):
        return DocumentProfile('Zahlungsbeleg', 'info', 'Einzahlung oder Überweisung; kein steuerlicher Wertpapierertrag.')
    if heading(r'Rechnung(?:\s+Nr.*)?|FACTURE.*|KARTENABRECHNUNG|CARD INVOICE'):
        return DocumentProfile('Gebührenabrechnung', 'review', 'Gebühren- oder Kartenrechnung erkannt.',
                               'Tatsächliche Belastung und steuerliche Zuordnung vor der Übernahme prüfen.')
    if heading(r"NOTE DE CONTRAT|NOTA CONTRATTUALE|TRANSACTIEBEVESTIGING|CONFIRMATION DE.*|"
               r"CONFIRMATION D.*|RELEV[ÉE] DE TRANSACTION.*|REGOLAMENTO TITOLI.*|DISTRIBUZIONE|R[ÈE]GLEMENT DU VERSEMENT|"
               r"D[ÉE]COMPTE.*|LIQUIDACI[ÓO]N.*|CONFERMA.*|RAPPORT D.INT[ÉE]R[ÊE]TS|"
               r"INFORME DE INTERESES|RESOCONTO.*|PIANO D.INVESTIMENTO.*"):
        return DocumentProfile('Fremdsprachige Abrechnung', 'review',
            'Fremdsprachiges Brokerlayout erkannt; vollständige Feldzuordnung noch nicht verifiziert.',
            'Buchungsart, Datum und Beträge anhand des Originals prüfen.')
    return None
