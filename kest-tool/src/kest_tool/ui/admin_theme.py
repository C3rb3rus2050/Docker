"""Shared Snipe-IT-inspired administration shell for every KESt page.

CSS is intentionally scoped to Streamlit's public test-id hooks wherever possible.
The shell changes presentation only, not tax calculations or data persistence.
"""
from __future__ import annotations

from html import escape

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
    """Consistent page header and breadcrumb on all navigation destinations."""
    section, title, description = SECTIONS[key]
    st.markdown(
        '<div class="kest-page-heading">'
        f'<div class="kest-breadcrumb">KESt Manager <span>›</span> {escape(section)} '
        f'<span>›</span> {escape(title)}</div>'
        f'<div class="kest-page-heading-row"><div>'
        f'<div class="kest-page-title">{escape(title)}</div>'
        f'<div class="kest-page-subtitle">{escape(description)}</div>'
        f'</div><span class="kest-page-indicator">KESt · Lokal</span></div>'
        '</div>',
        unsafe_allow_html=True,
    )


def apply_admin_theme() -> None:
    st.markdown(
        """
<style>
:root {
  --kest-navy: #222d32;
  --kest-navy-2: #1a2226;
  --kest-blue: #3c8dbc;
  --kest-blue-hover: #367fa9;
  --kest-bg: #ecf0f5;
  --kest-border: #d2d6de;
  --kest-text: #333;
  --kest-muted: #66727d;
}
[data-testid="stAppViewContainer"], .stApp {
  background: var(--kest-bg);
  color: var(--kest-text);
}
[data-testid="stHeader"] {
  background: #fff;
  border-bottom: 1px solid #d9dfe6;
  box-shadow: 0 1px 3px rgba(0,0,0,.035);
}
[data-testid="stSidebar"] {
  background: var(--kest-navy);
  border-right: 1px solid #151d20;
}
[data-testid="stSidebar"] > div:first-child { background: var(--kest-navy); }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top: .25rem; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] [data-testid="stPageLink"] a {
  border-radius: 0;
  margin: 1px 0;
  min-height: 35px;
  color: #b8c7ce !important;
  transition: background-color 120ms ease;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
  background: #1e282c;
  color: #fff !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="true"],
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
  background: var(--kest-navy-2) !important;
  border-left: 3px solid var(--kest-blue);
  color: #fff !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] span,
[data-testid="stSidebar"] [data-testid="stPageLink"] span,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] p { color: #d0d9de; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] [data-testid="stNavSectionHeader"],
[data-testid="stSidebar"] [data-testid="stSidebarNav"] [role="heading"] {
  color: #7c919c !important;
  font-size: .67rem;
  font-weight: 700;
  letter-spacing: .09em;
  text-transform: uppercase;
}
.kest-admin-brand {
  font-size: 1.22rem;
  font-weight: 750;
  letter-spacing: .02em;
  color: #fff;
  padding: .35rem .25rem .65rem;
  border-bottom: 1px solid #344249;
  margin-bottom: .5rem;
}
.kest-admin-brand span { color: #5db6e6; }
.kest-sidebar-caption {
  font-size: .72rem;
  color: #9daeb6;
  padding: .65rem .3rem .15rem;
}
.block-container {
  max-width: 1640px;
  padding: 1.25rem 2rem 3rem;
}
.kest-page-heading {
  margin: -.1rem 0 1.15rem;
  padding: .1rem 0 .9rem;
  border-bottom: 1px solid #d6dde4;
}
.kest-breadcrumb { color: #72818b; font-size: .77rem; margin-bottom: .35rem; }
.kest-breadcrumb span { padding: 0 .3rem; color: #a1aeb7; }
.kest-page-title {
  font-size: 1.65rem;
  font-weight: 650;
  line-height: 1.3;
  color: #303b42;
}
.kest-page-subtitle { font-size: .87rem; color: #75828b; margin-top: .2rem; }
.kest-admin-context {
  background: #fff;
  border-left: 3px solid var(--kest-blue);
  border-top: 1px solid #e0e5e9;
  border-right: 1px solid #e0e5e9;
  border-bottom: 1px solid #e0e5e9;
  padding: .55rem .85rem;
  margin-bottom: 1.05rem;
  font-size: .79rem;
  color: #697a84;
}
h1 { font-size: 1.52rem !important; font-weight: 650 !important; color: #333 !important; }
h2 { font-size: 1.22rem !important; font-weight: 650 !important; color: #333 !important; }
h3 { font-size: 1.07rem !important; font-weight: 650 !important; color: #333 !important; }
[data-testid="stMetric"] {
  background: #fff;
  border: 1px solid #e0e5e9;
  border-top: 3px solid var(--kest-blue);
  border-radius: 2px;
  padding: .9rem 1rem;
  box-shadow: 0 1px 1px rgba(0,0,0,.04);
}
[data-testid="stMetricLabel"] { color: #687780; }
[data-testid="stMetricValue"] { font-size: 1.55rem; color: #29343a; }
[data-testid="stDataFrame"], [data-testid="stTable"] {
  background: #fff;
  border: 1px solid var(--kest-border);
  border-radius: 2px;
  overflow: hidden;
}
[data-testid="stForm"], [data-testid="stExpander"] {
  background: #fff;
  border: 1px solid #dce2e6;
  border-radius: 2px;
  box-shadow: 0 1px 1px rgba(0,0,0,.035);
}
[data-testid="stForm"] { padding: 1rem; }
[data-testid="stVerticalBlockBorderWrapper"] { border-radius: 2px; }
[data-testid="stAlert"] { border-radius: 2px; }
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  background: #fff;
  border-bottom: 2px solid #dce3e8;
  gap: .3rem;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
  font-size: .86rem;
  font-weight: 600;
  color: #52616c;
}
[data-testid="stTabs"] [aria-selected="true"] { color: var(--kest-blue); }
.stButton button, [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
  border-radius: 3px !important;
  font-weight: 550;
  min-height: 34px;
}
.stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
  background: var(--kest-blue);
  border-color: var(--kest-blue);
  color: #fff;
}
.stButton button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] button[kind="primary"]:hover {
  background: var(--kest-blue-hover);
  border-color: var(--kest-blue-hover);
}
[data-baseweb="select"] > div, [data-baseweb="input"] > div,
[data-baseweb="textarea"] > div { border-radius: 3px; }
[data-testid="stFileUploader"] {
  background: #fff;
  border: 1px solid #dce2e6;
  padding: .5rem;
}
[data-testid="stFileUploaderDropzone"] { border-radius: 3px; }
@media (max-width: 900px) {
  .block-container { padding: 1rem 1rem 2rem; }
  .kest-page-title { font-size: 1.4rem; }
}
@media (max-width: 600px) {
  .block-container { padding: .75rem .6rem 1.5rem; }
  .kest-page-heading { margin-bottom: .7rem; }
  .kest-page-title { font-size: 1.25rem; }
  .kest-page-subtitle { font-size: .78rem; }
}

/* Shared design tokens copied from the GrocyMealPlanner admin shell.
   Source: C3rb3rus2050/GrocyMealPlanner frontend/src/styles.css (main).
   Streamlit-specific selectors preserve its navigation and accessibility. */
:root {
  --meal-bg: #f4f6f9;
  --meal-surface: #ffffff;
  --meal-surface-2: #f7f9fc;
  --meal-text: #273746;
  --meal-muted: #64748b;
  --meal-border: #dce3ea;
  --meal-primary: #367fa9;
  --meal-nav: #222d32;
  --meal-nav-hover: #1e282c;
  --meal-radius: 4px;
  --meal-shadow: none;
}
[data-testid="stAppViewContainer"], .stApp {
  background: var(--meal-bg);
  color: var(--meal-text);
  font-size: 14px;
}
[data-testid="stHeader"] { background: var(--meal-surface); border-bottom: 1px solid var(--meal-border); box-shadow: none; }
[data-testid="stSidebar"], [data-testid="stSidebar"] > div:first-child {
  background: var(--meal-nav);
  border-color: #172127;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] { padding-top: .6rem; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] [data-testid="stPageLink"] a {
  font-size: .89rem;
  font-weight: 500;
  min-height: 39px;
  padding: .5rem .75rem;
  border-left: 3px solid transparent;
  color: #cbd5db !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
  background: var(--meal-nav-hover);
  color: #fff !important;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="true"],
[data-testid="stSidebar"] [data-testid="stPageLink"] a[aria-current="page"] {
  background: var(--meal-nav-hover) !important;
  border-left-color: #3c8dbc;
  color: #fff !important;
  font-weight: 600;
}
.kest-admin-brand {
  background: #367fa9;
  color: white;
  padding: 1rem 1.1rem;
  margin: -1rem -1rem .65rem;
  border: none;
  min-height: 60px;
  font-size: 1.05rem;
  letter-spacing: .01em;
}
.kest-admin-brand span { color: white; }
.kest-sidebar-caption { color: #90a0aa; border-top: 1px solid #344047; margin-top: .7rem; padding-top: .9rem; }
.block-container { max-width: none; padding: .9rem 1.35rem 4rem; }
.kest-page-heading {
  background: var(--meal-surface);
  border-bottom: 1px solid var(--meal-border);
  margin: -.9rem -1.35rem 1.25rem;
  padding: .8rem 1.35rem 1rem;
}
.kest-breadcrumb { color: var(--meal-muted); font-size: .75rem; margin-bottom: .45rem; }
.kest-page-heading-row { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.kest-page-title { color: var(--meal-text); font-size: 1.42rem; line-height: 1.25; font-weight: 600; }
.kest-page-subtitle { color: var(--meal-muted); font-size: .78rem; margin-top: .15rem; }
.kest-page-indicator {
  border: 1px solid var(--meal-border);
  border-radius: var(--meal-radius);
  background: var(--meal-surface-2);
  color: var(--meal-muted);
  font-size: .74rem;
  padding: .28rem .6rem;
  white-space: nowrap;
}
.kest-admin-context {
  background: var(--meal-surface);
  color: var(--meal-muted);
  border: 1px solid var(--meal-border);
  border-radius: var(--meal-radius);
  font-size: .78rem;
  padding: .55rem .8rem;
}
h1 { font-size: 1.3rem !important; color: var(--meal-text) !important; }
h2 { font-size: 1.08rem !important; color: var(--meal-text) !important; }
h3 { font-size: 1rem !important; color: var(--meal-text) !important; }
[data-testid="stMetric"], [data-testid="stForm"], [data-testid="stExpander"],
[data-testid="stDataFrame"], [data-testid="stTable"] {
  background: var(--meal-surface);
  border: 1px solid var(--meal-border);
  border-radius: var(--meal-radius);
  box-shadow: var(--meal-shadow);
}
[data-testid="stMetric"] { border-top: 1px solid var(--meal-border); padding: .85rem 1rem; }
[data-testid="stMetricValue"] { color: var(--meal-text); }
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  background: transparent;
  border-bottom: 1px solid var(--meal-border);
}
[data-testid="stTabs"] [data-baseweb="tab"] { font-size: .88rem; }
[data-testid="stTabs"] [aria-selected="true"] { color: var(--meal-primary); }
.stButton button, [data-testid="stFormSubmitButton"] button,
[data-testid="stDownloadButton"] button {
  min-height: 36px;
  padding: .45rem .85rem;
  border-radius: var(--meal-radius) !important;
  font-size: .875rem;
  font-weight: 600;
}
.stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
  background: var(--meal-primary);
  border-color: var(--meal-primary);
}
[data-baseweb="select"] > div, [data-baseweb="input"] > div,
[data-baseweb="textarea"] > div { border-radius: var(--meal-radius); }
[data-testid="stAlert"] { border-radius: var(--meal-radius); }
[data-testid="stFileUploader"] { border: 1px solid var(--meal-border); background: var(--meal-surface); }
@media (max-width: 820px) {
  .block-container { padding: .7rem 12px 4.5rem; }
  .kest-page-heading { margin: -.7rem -12px 1rem; padding: .75rem 12px; }
  .kest-page-title { font-size: 1.1rem; }
  .kest-page-subtitle { font-size: .75rem; }
  .kest-page-indicator { font-size: .7rem; }
}

</style>
""",
        unsafe_allow_html=True,
    )
