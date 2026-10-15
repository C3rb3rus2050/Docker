"""Gemeinsame, responsive Oberfläche für die KESt-Verwaltung."""
from __future__ import annotations

from html import escape
from pathlib import Path

import streamlit as st

SECTIONS = {
    "dashboard": ("Übersicht", "Dashboard", "Alle wichtigen Kennzahlen und Aufgaben auf einen Blick"),
    "import": ("Dokumente & Buchungen", "Import", "PDF-, ZIP- und Tabellendateien sicher einlesen"),
    "dokumente": ("Dokumente & Buchungen", "Dokumente", "Belege prüfen, klassifizieren und verwalten"),
    "transaktionen": ("Dokumente & Buchungen", "Transaktionen", "Buchungen kontrollieren und bearbeiten"),
    "wertpapiere": ("Stammdaten", "Wertpapiere", "Wertpapier-Stammdaten und Zuordnungen verwalten"),
    "fonds": ("Stammdaten", "Fonds & OeKB", "Fondsdaten und steuerliche Meldungen verwalten"),
    "depots": ("Stammdaten", "Broker & Depots", "Brokerkonten und Depots organisieren"),
    "steuer": ("Steuern & Berichte", "Steuerberechnung", "Steuerliche Ergebnisse berechnen und überprüfen"),
    "exporte": ("Steuern & Berichte", "Exporte", "Berichte und Auswertungen herunterladen"),
    "einstellungen": ("System", "Einstellungen", "Konfiguration, Diagnose und Wartung"),
}


def render_page_header(key: str) -> None:
    section, title, description = SECTIONS[key]
    st.markdown(
        '<div class="kest-page-heading">'
        '<div class="kest-page-heading-row">'
        f'<nav aria-label="Seitenpfad" class="kest-breadcrumb">KESt Manager <span>/</span> {escape(section)} '
        f'<span>/</span> {escape(title)}</nav>'
        '<span class="kest-page-indicator">Private Steuerverwaltung</span></div>'
        f'<p class="kest-page-subtitle">{escape(description)}</p></div>',
        unsafe_allow_html=True,
    )


def apply_admin_theme() -> None:
    css = Path(__file__).with_name("admin_theme.css").read_text(encoding="utf-8")
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
