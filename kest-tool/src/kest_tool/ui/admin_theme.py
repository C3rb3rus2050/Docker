"""Snipe-IT-inspired administrative styling for the Streamlit interface.

Selectors use Streamlit test IDs where available. Cosmetic only: no data processing.
"""
from __future__ import annotations

import streamlit as st


def apply_admin_theme() -> None:
    st.markdown(
        """
<style>
:root {
  --kest-navy: #172a3b;
  --kest-navy-hover: #263e52;
  --kest-blue: #2876b8;
  --kest-border: #dce3eb;
  --kest-text: #243647;
}
[data-testid="stAppViewContainer"] {
  background: #f3f6f9;
  color: var(--kest-text);
}
[data-testid="stHeader"] {
  background: #ffffff;
  border-bottom: 1px solid var(--kest-border);
}
[data-testid="stSidebar"] {
  background: var(--kest-navy);
  border-right: 1px solid #12212f;
}
[data-testid="stSidebar"] * { color: #edf3f8; }
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] [data-testid="stPageLink"] a {
  border-radius: 6px;
  transition: background-color 120ms ease;
}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebar"] [data-testid="stPageLink"] a:hover {
  background: var(--kest-navy-hover);
}
[data-testid="stSidebar"] [aria-current="page"] {
  background: #245f8f !important;
  border-left: 3px solid #6cc0ff;
}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
  color: #cbd7e3;
}
.block-container {
  max-width: 1560px;
  padding-top: 1.35rem;
  padding-bottom: 3rem;
}
h1 { font-size: 1.75rem !important; font-weight: 700 !important; color: #203347 !important; }
h2 { font-size: 1.32rem !important; color: #203347 !important; }
h3 { font-size: 1.12rem !important; }
[data-testid="stVerticalBlockBorderWrapper"] > div[data-testid="stVerticalBlock"] {
  border-radius: 8px;
}
[data-testid="stMetric"] {
  background: #fff;
  border: 1px solid var(--kest-border);
  border-radius: 8px;
  padding: 0.8rem 1rem;
}
[data-testid="stMetricValue"] { font-size: 1.55rem; }
[data-testid="stDataFrame"], [data-testid="stTable"] {
  border: 1px solid var(--kest-border);
  border-radius: 7px;
  overflow: hidden;
  background: white;
}
[data-testid="stForm"] {
  border: 1px solid var(--kest-border);
  background: white;
  border-radius: 8px;
  padding: 1rem;
}
[data-testid="stExpander"] {
  border: 1px solid var(--kest-border);
  border-radius: 7px;
  background: white;
}
.stButton button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] {
  background: var(--kest-blue);
  border-color: var(--kest-blue);
  border-radius: 5px;
}
.stButton button, [data-testid="stFormSubmitButton"] button {
  border-radius: 5px;
}
[data-baseweb="select"] > div, [data-baseweb="input"] > div {
  border-radius: 5px;
}
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  border-bottom: 1px solid var(--kest-border);
}
[data-testid="stTabs"] [data-baseweb="tab"] { font-weight: 600; }
.kest-admin-brand {
  font-size: 1.15rem;
  font-weight: 750;
  letter-spacing: .025em;
  color: white;
  padding: .45rem 0 .9rem;
}
.kest-admin-brand span { color: #73c3fa; }
.kest-admin-context {
  background: #fff;
  border: 1px solid var(--kest-border);
  border-radius: 7px;
  padding: .65rem 1rem;
  margin: 0 0 1.1rem;
  color: #536578;
  font-size: .85rem;
}
@media (max-width: 768px) {
  .block-container { padding: 1rem .75rem 2rem; }
  h1 { font-size: 1.45rem !important; }
}
</style>
""",
        unsafe_allow_html=True,
    )
