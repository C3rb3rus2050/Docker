"""Textlayouts, nachgebildet nach öffentlich dokumentierten Beispielen (keine echten Kundendaten).

Die genaue Formatierung echter Abrechnungen kann abweichen."""

TR_BUY = """TRADE REPUBLIC BANK GMBH BRUNNENSTRASSE 19-21 10119 BERLIN
Max Mustermann DATUM 07.12.2020
WERTPAPIERABRECHNUNG
ÜBERSICHT
Market-Order Kauf am 03.12.2020, um 13:20 Uhr an der Lang & Schwarz Exchange.
POSITION ANZAHL DURCHSCHNITTSKURS BETRAG
Tesla Inc. 1 Stk. 497,40 EUR 497,40 EUR
Registered Shares DL-,001
ISIN: US88160R1014
ABRECHNUNG
POSITION BETRAG
Fremdkostenzuschlag -1,00 EUR
GESAMT -498,40 EUR
BUCHUNG
VERRECHNUNGSKONTO VALUTA BETRAG
DE00000000000000000000 07.12.2020 -498,40 EUR
"""
TR_DIV = """TRADE REPUBLIC BANK GMBH
DATUM 15.02.2024
DIVIDENDE
ÜBERSICHT
Dividende mit dem Ex-Tag 09.02.2024.
POSITION ANZAHL ERTRAG BETRAG
Apple Inc. 3,5 Stk. 0,24 USD 0,84 USD
Registered Shares o.N.
ISIN: US0378331005
ABRECHNUNG
POSITION BETRAG
Quellensteuer für US-Emittent -0,13 USD
Zwischensumme 0,71 USD
Zwischensumme 1,0821 EUR/USD 0,66 EUR
GESAMT 0,66 EUR
"""
BAADER = """Scalable Capital Vermögensverwaltung GmbH
Baader Bank AG
Wertpapierabrechnung: Kauf
Auftragsdatum 04.01.2021
Handelstag 05.01.2021
Handelszeit 09:04:12
Nominale Wertpapierbezeichnung ISIN
STK 2,000 iShares Core MSCI World IE00B4L5Y983
Kurs EUR 63,15
Kurswert EUR 126,30
Provision EUR 0,99
Zu Lasten Konto 1234567 Valuta: 07.01.2021 EUR 127,29
"""
