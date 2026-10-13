"""Scalable-Capital-Adapter.

Recherchestand (siehe README „API-Verfügbarkeit“):
- Scalable Capital bietet mit der *Scalable CLI* (``sc``, OAuth-Device-Flow, Beta) eine offizielle
  Schnittstelle an. Laut README umfasst sie Depot-, Transaktions- und Handelsfunktionen, aber
  **keine Dokumenten-/Postfach-Befehle** und keine Windows-Binärdatei. Sie ist daher keine
  Grundlage für den Dokumentenabruf und wird nicht verwendet (insbesondere keine Handelsbefehle).
- Eine öffentlich dokumentierte inoffizielle Dokumenten-API ist nicht bekannt. Es werden
  deshalb KEINE internen Endpunkte erfunden oder direkt angesprochen.

Quellen dieses Adapters:
1. **UI** (Hauptquelle): sichtbare Weboberfläche (Postfach/Dokumente/Steuern …), automatisch erkannt.
2. **Netzwerk** (passiv, zweite Quelle): Dokumentlisten, die die Webapp während der Navigation
   selbst lädt (JSON/GraphQL), werden lokal mitgelesen und mit der UI abgeglichen.

Ältere Kontomodelle/Bankpartner (z. B. frühere Depotbanken) können eigene Dokumentenbereiche
haben, die über das aktuelle Konto nicht erreichbar sind. Das wird im Bericht ausgewiesen.
"""

from __future__ import annotations

import re

from .security import UrlPolicy
from .web_adapter import WebBrokerAdapter


class ScalableCapitalAdapter(WebBrokerAdapter):
    broker_id = "scalable_capital"
    display_name = "Scalable Capital"
    start_url = "https://de.scalable.capital/"
    app_hosts = ("de.scalable.capital", "scalable.capital", "secure.scalable.capital", "app.scalable.capital")
    url_policy = UrlPolicy(allowed_suffixes=("scalable.capital",))
    login_path_pattern = re.compile(r"(login|signin|sign-in|anmelden|/u/|/auth)", re.I)
    expand_area_pattern = None  # Postfach-Einträge sind i. d. R. selbst Dokumente

    LEGACY_NOTE = ("Hinweis: Dokumente früherer Kontomodelle oder Bankpartner sind nur enthalten, wenn sie im "
                   "aktuellen Kundenkonto angezeigt werden. Nicht angezeigte Altbestände müssen ggf. beim "
                   "früheren Partner angefordert werden.")
