"""Automatische, sichere Dokumentensuche in der angemeldeten Weboberfläche.

Zwei Ebenen:

1. **Reine Regeln** (ohne Browser testbar): Erkennen von Dokumentbezug, gefährlichen
   Aktionen, Paginierung, Zeitraumfiltern, direkten Downloadlinks.
2. **DomDiscovery**: wendet die Regeln auf eine Playwright-Seite an (Snapshot der
   interaktiven Elemente, kontrollierte Navigation, „Mehr laden“, Seitenwechsel,
   Infinite Scroll, Jahresfilter, aufklappbare Einträge).

Sicherheitsprinzip: Es wird nur auf Elemente geklickt, deren Bedeutung anhand ihres
zugänglichen Namens eindeutig als Navigation zu Dokumenten, Dokument-Download,
Paginierung oder Zeitraumfilter erkannt wurde. Alles, was nach Kontoaktion aussieht
(Kaufen, Verkaufen, Überweisen, Sparplan ändern, Bestätigen, Abmelden …), wird
grundsätzlich blockiert – auch wenn es gleichzeitig Dokument-Schlüsselwörter enthält.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from .broker_adapter import SafetyViolation
from .classifier import parse_date

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Regeln
# --------------------------------------------------------------------------- #

DANGEROUS = re.compile(
    r"(\bjetzt\s+(kaufen|verkaufen|investieren|handeln|traden|anlegen)"
    r"|\b(kaufen|verkaufen|handeln|traden|investieren|nachkaufen|zeichnen)\b"
    r"|\border\s+(aufgeben|platzieren|senden|ändern|bearbeiten|stornieren|prüfen)|\bstornieren\b"
    r"|\büberweisen\b|\büberweisung\s+(starten|senden|ausführen|tätigen|erstellen)"
    r"|\bgeld\s+(senden|anfordern|einzahlen|auszahlen|überweisen)|\b(auszahlen|einzahlen|aufladen)\b"
    r"|\bsparplan\s+(anlegen|erstellen|einrichten|ändern|pausieren|löschen|bearbeiten|starten|aussetzen)"
    r"|\b(löschen|entfernen|kündigen|bestätigen|absenden|senden|abschicken|speichern|übernehmen|zustimmen"
    r"|akzeptieren|aktivieren|deaktivieren|freigeben|sperren|entsperren|einlösen|beantragen|anfordern|verknüpfen)\b"
    r"|\b(abmelden|ausloggen|logout|log\s*out|sign\s*out|abmeldung)\b"
    r"|\b(buy|sell|trade|invest|withdraw|deposit|transfer|delete|remove|confirm|submit|send|cancel\s+order"
    r"|place\s+order|unsubscribe)\b"
    r"|passwort|kennwort|\bpin\b|einstellung|limit\s+setzen|kurswecker|preisalarm|watchlist|merkliste"
    r"|hinzufügen|\bteilen\b|\bshare\b|einladen|freunde\s+werben|\bkarte\b"
    r"|chat|support\s+kontaktieren|kontakt\s+aufnehmen)",
    re.IGNORECASE,
)

NAV_KEYWORDS = re.compile(
    r"(dokument|postfach|post\s*box|mailbox|inbox|nachrichten|steuer|\btax|auszug|abrechnung|bericht|report"
    r"|archiv|historie|verlauf|aktivit|activity|transaktion|transaction|umsätze|umsatz|belege|unterlagen"
    r"|documents|statement|profil|mein\s+konto|kontoinformation|depot)",
    re.IGNORECASE,
)

DOC_TITLE = re.compile(
    r"(abrechnung|auszug|bescheinigung|beleg|bericht|report|dokument|statement|rechnung|mitteilung"
    r"|information|steuer|dividend|ausschüttung|ertrag|zins|gebühr|kosten|vertrag|vereinbarung|bestätigung"
    r"|übersicht|pdf|\.pdf|csv|export|herunterladen|download|invoice|confirmation|tax|jahres)",
    re.IGNORECASE,
)

GENERIC_DOWNLOAD_LABEL = re.compile(
    r"^\s*(pdf|csv|zip|download|herunterladen|pdf\s+herunterladen|dokument\s+(öffnen|anzeigen|herunterladen)"
    r"|öffnen|anzeigen|ansehen|speichern\s+als\s+pdf|export(ieren)?|datei|als\s+pdf)\s*$",
    re.IGNORECASE,
)

LOAD_MORE = re.compile(
    r"(mehr\s+(laden|anzeigen|einträge|dokumente)|weitere\s+(laden|anzeigen|einträge|dokumente)|ältere"
    r"|frühere|alle\s+anzeigen|load\s+more|show\s+more|older|view\s+more|see\s+more)",
    re.IGNORECASE,
)
NEXT_PAGE = re.compile(r"^\s*(nächste(\s+seite)?|weiter|next(\s+page)?|›|»|>|→)\s*$", re.IGNORECASE)
NEXT_PAGE_EXPLICIT = re.compile(r"(nächste\s+seite|next\s+page|seite\s+vor|go\s+to\s+next)", re.IGNORECASE)

DIRECT_DOC_HREF = re.compile(
    r"(\.(pdf|csv|zip)(\?|#|$)|/download|/documents?/|/dokumente?/|/postbox|/mailbox/.+|/files?/|/attachments?/"
    r"|[?&](format|type)=(pdf|csv))",
    re.IGNORECASE,
)
MANUAL_REQUEST = re.compile(r"\b(anfordern|beantragen|auf\s+anfrage|request)\b", re.IGNORECASE)
YEAR_LABEL = re.compile(r"^\s*((?:19|20)\d{2})\s*$")
FORBIDDEN_HREF = re.compile(r"^(mailto:|tel:|sms:|javascript:(?!void)|data:)", re.IGNORECASE)


def is_dangerous(label: str) -> bool:
    return bool(DANGEROUS.search(label or ""))


def is_navigation_candidate(label: str) -> bool:
    label = (label or "").strip()
    if not label or len(label) > 80:
        return False
    return bool(NAV_KEYWORDS.search(label)) and not is_dangerous(label)


def is_document_label(label: str) -> bool:
    label = (label or "").strip()
    if not label or len(label) > 250:
        return False
    return bool(DOC_TITLE.search(label)) and not is_dangerous(label)


def is_load_more(label: str) -> bool:
    label = (label or "").strip()
    return bool(label) and len(label) <= 60 and bool(LOAD_MORE.search(label)) and not is_dangerous(label)


def is_next_page(label: str, in_pagination: bool) -> bool:
    label = (label or "").strip()
    if not label or len(label) > 40 or is_dangerous(label):
        return False
    if NEXT_PAGE_EXPLICIT.search(label):
        return True
    # "Weiter" ist mehrdeutig (Assistenten, Orderstrecken) → nur in Paginierungscontainern
    return in_pagination and bool(NEXT_PAGE.match(label))


def is_direct_document_href(href: str) -> bool:
    if not href or FORBIDDEN_HREF.match(href):
        return False
    return bool(DIRECT_DOC_HREF.search(href)) or href.startswith("blob:")


def year_options(options: list[dict[str, str]] | None) -> list[dict[str, str]]:
    """Optionen einer Auswahlliste, die Jahreszahlen darstellen."""
    years = []
    for opt in options or []:
        m = YEAR_LABEL.match(opt.get("label", "")) or YEAR_LABEL.match(opt.get("value", ""))
        if m:
            years.append({"value": opt.get("value", ""), "label": m.group(1)})
    return years if len(years) >= 1 else []


@dataclass
class Element:
    """Ein interaktives Element aus dem DOM-Snapshot."""

    id: str
    tag: str
    label: str
    role: str = ""
    text: str = ""
    href: str = ""
    download: str = ""
    type: str = ""
    context: str = ""
    in_form: bool = False
    form_has_inputs: bool = False
    in_nav: bool = False
    in_pagination: bool = False
    in_dialog: bool = False
    has_clickable_child: bool = False
    disabled: bool = False
    options: list[dict[str, str]] | None = None

    @classmethod
    def from_js(cls, d: dict[str, Any]) -> "Element":
        return cls(
            id=d.get("id", ""), tag=d.get("tag", ""), label=d.get("label", ""), role=d.get("role", ""),
            text=d.get("text", ""), href=d.get("href", ""), download=d.get("download", ""), type=d.get("type", ""),
            context=d.get("context", ""), in_form=bool(d.get("inForm")), form_has_inputs=bool(d.get("formHasInputs")),
            in_nav=bool(d.get("inNav")), in_pagination=bool(d.get("inPagination")),
            in_dialog=bool(d.get("inDialog")), has_clickable_child=bool(d.get("hasClickableChild")),
            disabled=bool(d.get("disabled")), options=d.get("options"),
        )

    @property
    def selector(self) -> str:
        return f'[data-bdc-id="{self.id}"]'

    def safe_to_click(self) -> bool:
        """Grundprüfung für JEDEN Klick."""
        if self.disabled or is_dangerous(self.label):
            return False
        if GENERIC_DOWNLOAD_LABEL.match(self.label or "") and is_dangerous(self.context[:200]):
            return False
        if self.href and FORBIDDEN_HREF.match(self.href):
            return False
        if self.type.lower() == "submit" and self.form_has_inputs:
            return False
        if self.form_has_inputs and self.tag not in ("select",):
            return False
        return True


def assert_safe(el: Element) -> None:
    if not el.safe_to_click():
        raise SafetyViolation(f"Klick blockiert (mögliche Kontoaktion): {el.label[:80]!r}")


@dataclass
class DocCandidate:
    title: str
    href: str = ""
    element: Element | None = None
    date: str = ""

    @property
    def is_click(self) -> bool:
        return not self.href


def document_candidates(elements: list[Element], exclude_nav: bool = True) -> list[DocCandidate]:
    """Wählt aus einem Snapshot die Dokumenteinträge aus (direkte Links + eindeutige Download-Klicks)."""
    found: list[DocCandidate] = []
    seen_titles: set[str] = set()
    seen_hrefs: set[str] = set()
    for el in elements:
        if exclude_nav and el.in_nav and not el.in_dialog:
            continue
        if el.tag == "select":
            continue
        title = el.label
        if GENERIC_DOWNLOAD_LABEL.match(title or "") and el.context:
            title = el.context
        title = re.sub(r"\s+", " ", title or "").strip()[:200]
        # Direkter Dokumentlink: wird per GET geladen, nicht angeklickt
        if el.href and is_direct_document_href(el.href):
            if el.href in seen_hrefs:
                continue
            seen_hrefs.add(el.href)
            found.append(DocCandidate(title or el.href.rsplit("/", 1)[-1], href=el.href, element=el,
                                      date=parse_date(f"{title} {el.context}")))
            seen_titles.add(title)
            continue
        # Klick-Kandidat: innerstes Element, Bedeutung eindeutig "Dokument"
        if el.has_clickable_child or not el.safe_to_click():
            continue
        if el.tag not in ("button", "a", "li") and el.role not in ("button", "link", "row", "listitem", "menuitem"):
            continue
        if el.href and not el.href.startswith(("#", "javascript:void")) and not el.href.endswith("#"):
            # normaler Navigationslink ohne Dokument-Muster → kein Download
            continue
        if not (is_document_label(el.label) or (GENERIC_DOWNLOAD_LABEL.match(el.label or "") and el.context)):
            continue
        if title in seen_titles:
            continue
        seen_titles.add(title)
        found.append(DocCandidate(title, element=el, date=parse_date(f"{el.label} {el.context}")))
    return found


def manual_request_candidates(elements: list[Element]) -> list[Element]:
    """Dokumente, die nur manuell angefordert werden können (werden NICHT angeklickt, nur gemeldet)."""
    return [el for el in elements
            if el.tag != "select" and MANUAL_REQUEST.search(el.label or "") and DOC_TITLE.search(
                f"{el.label} {el.context}") and len(el.label) <= 200]


def navigation_candidates(elements: list[Element]) -> list[Element]:
    out, seen = [], set()
    for el in elements:
        if el.tag == "select" or not el.safe_to_click():
            continue
        if not (el.in_nav or el.role in ("tab", "menuitem", "link") or el.tag == "a"):
            continue
        if not is_navigation_candidate(el.label):
            continue
        if el.href and is_direct_document_href(el.href) and el.href.lower().split("?")[0].endswith(
                (".pdf", ".csv", ".zip")):
            continue
        label_key = "l:" + el.label.lower()
        href_key = "h:" + el.href.split("#")[0] if el.href and not el.href.endswith("#") else ""
        if label_key in seen or (href_key and href_key in seen):
            continue
        seen.update(k for k in (label_key, href_key) if k)
        out.append(el)
    return out


def expandable_entries(elements: list[Element], entry_pattern: re.Pattern[str] | None = None) -> list[Element]:
    """Listeneinträge (z. B. Transaktionen), die eine Detailansicht mit Dokumenten öffnen."""
    out = []
    for el in elements:
        if el.in_nav or el.in_dialog or not el.safe_to_click() or el.tag == "select":
            continue
        if el.role not in ("row", "listitem", "button", "link") and el.tag not in ("li", "button", "a"):
            continue
        if el.has_clickable_child and el.tag in ("li",):
            continue
        if el.href and not el.href.endswith("#") and not el.href.startswith("#"):
            # Detail per Link → als Navigation behandelbar, aber nur innerhalb des Brokers (prüft Adapter)
            pass
        label = el.label or ""
        if not label or len(label) > 250 or is_load_more(label) or NEXT_PAGE.match(label):
            continue
        if entry_pattern and not entry_pattern.search(label):
            continue
        out.append(el)
    return out


# --------------------------------------------------------------------------- #
# JavaScript für den DOM-Snapshot (läuft in der Brokerseite, liest nur)
# --------------------------------------------------------------------------- #

SNAPSHOT_JS = r"""
(opts) => {
  const sel = 'a[href], button, [role=button], [role=link], [role=tab], [role=menuitem], [role=option],' +
              '[role=row], [role=listitem], li, select, summary, [tabindex]:not([tabindex="-1"])';
  const nodes = Array.from(document.querySelectorAll(sel)).slice(0, opts.max || 4000);
  const out = [];
  let i = 0;
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  for (const el of nodes) {
    const r = el.getBoundingClientRect();
    const st = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none';
    if (!visible) continue;
    const text = clean(el.innerText || el.textContent).slice(0, 400);
    let label = clean(el.getAttribute('aria-label'));
    if (!label && el.getAttribute('aria-labelledby')) {
      label = clean(el.getAttribute('aria-labelledby').split(' ')
        .map(id => (document.getElementById(id) || {}).textContent || '').join(' '));
    }
    if (!label) label = text;
    if (!label) label = clean(el.getAttribute('title'));
    if (!label && el.tagName === 'SELECT') {
      const lab = el.id ? document.querySelector('label[for="' + el.id + '"]') : null;
      label = clean(lab ? lab.textContent : (el.name || el.id || 'Auswahl'));
    }
    const ctxEl = el.closest('li, tr, [role=row], [role=listitem], article');
    const context = ctxEl && ctxEl !== el ? clean(ctxEl.innerText).slice(0, 300) : '';
    const form = el.closest('form');
    const formHasInputs = !!(form && form.querySelector(
      'input:not([type=hidden]):not([type=search]):not([type=checkbox]):not([type=radio]), textarea'));
    const id = 'bdc-' + (opts.prefix || '') + (i++);
    el.setAttribute('data-bdc-id', id);
    out.push({
      id, tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', label: label.slice(0, 300), text,
      href: el.tagName === 'A' ? (el.href || '') : (el.getAttribute('href') || ''),
      download: el.hasAttribute('download') ? (el.getAttribute('download') || '1') : '',
      type: el.getAttribute('type') || '', context, inForm: !!form, formHasInputs,
      inNav: !!el.closest('nav, [role=navigation], header, aside, [role=menubar], [role=tablist]'),
      inPagination: !!el.closest('[class*=pagin i], [aria-label*=pagin i], [aria-label*=seite i], [data-testid*=pagin i]'),
      inDialog: !!el.closest('dialog, [role=dialog], [aria-modal=true]'),
      hasClickableChild: !!el.querySelector('a[href], button, [role=button], [role=link]'),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      options: el.tagName === 'SELECT' ? Array.from(el.options).map(o => ({value: o.value, label: clean(o.text)})) : null,
    });
  }
  return out;
}
"""

SCROLL_JS = r"""
() => {
  let total = document.documentElement.scrollHeight;
  window.scrollTo(0, document.documentElement.scrollHeight);
  for (const el of document.querySelectorAll('main, [role=main], div, section, ul')) {
    const st = getComputedStyle(el);
    if ((st.overflowY === 'auto' || st.overflowY === 'scroll') && el.scrollHeight > el.clientHeight + 40) {
      el.scrollTop = el.scrollHeight;
      total += el.scrollHeight;
    }
  }
  return total;
}
"""

FIND_EMBEDDED_DOC_JS = r"""
() => {
  const urls = [];
  for (const el of document.querySelectorAll('iframe[src], embed[src], object[data], a[href^="blob:"]')) {
    const u = el.src || el.data || el.href || '';
    if (u && (u.startsWith('blob:') || /\.pdf(\?|#|$)/i.test(u) || el.type === 'application/pdf')) urls.push(u);
  }
  return urls;
}
"""


# --------------------------------------------------------------------------- #
# DomDiscovery – wendet die Regeln auf eine Playwright-Seite an
# --------------------------------------------------------------------------- #


@dataclass
class DiscoveryLimits:
    max_pages: int = 200
    max_load_more: int = 500
    max_items: int = 5000
    max_areas: int = 60
    action_delay_ms: int = 600
    settle_timeout_ms: int = 8000


@dataclass
class PageScanState:
    pages: int = 0
    exhausted: bool = False  # True = Ende der Liste sicher erreicht
    limit_hit: bool = False
    seen: set[str] = field(default_factory=set)
    pagination_steps: int = 0


class DomDiscovery:
    def __init__(self, page: Any, limits: DiscoveryLimits, checkpoint: Callable[[], None] = lambda: None):
        self.page = page
        self.limits = limits
        self.checkpoint = checkpoint
        self._snap_counter = 0

    # ------------------------------------------------------------------ #
    def settle(self) -> None:
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=self.limits.settle_timeout_ms)
            self.page.wait_for_load_state("networkidle", timeout=self.limits.settle_timeout_ms)
        except Exception:
            pass  # SPAs erreichen networkidle oft nie (WebSockets) – kein Fehler
        self.page.wait_for_timeout(self.limits.action_delay_ms)

    def snapshot(self) -> list[Element]:
        self._snap_counter += 1
        raw = self.page.evaluate(SNAPSHOT_JS, {"max": 4000, "prefix": f"{self._snap_counter}-"})
        return [Element.from_js(d) for d in raw]

    def click(self, el: Element, timeout_ms: int = 10000) -> None:
        assert_safe(el)
        log.debug("Klick: %s", el.label[:80])
        self.page.locator(el.selector).first.click(timeout=timeout_ms)

    def find_by_label(self, label: str, predicate: Callable[[Element], bool] | None = None) -> Element | None:
        for el in self.snapshot():
            if el.label == label and (predicate is None or predicate(el)):
                return el
        return None

    def close_overlays(self) -> None:
        """Schließt modale Dialoge/Viewer (Escape) – löst keine Aktion aus."""
        try:
            if self.page.locator("dialog[open], [role=dialog], [aria-modal=true]").count():
                self.page.keyboard.press("Escape")
                self.page.wait_for_timeout(300)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Zeiträume
    # ------------------------------------------------------------------ #
    def detect_periods(self, elements: list[Element] | None = None) -> list[dict[str, str]]:
        """Erkennt Jahresfilter: <select> mit Jahresoptionen oder Tabs/Buttons mit Jahreszahl."""
        elements = elements if elements is not None else self.snapshot()
        periods: list[dict[str, str]] = []
        for el in elements:
            if el.tag == "select" and not el.form_has_inputs:
                for opt in year_options(el.options):
                    periods.append({"kind": "select", "select_label": el.label, "value": opt["value"],
                                    "label": opt["label"]})
        if not periods:
            for el in elements:
                m = YEAR_LABEL.match(el.label or "")
                if m and el.safe_to_click() and (el.role in ("tab", "button", "option", "menuitem")
                                                 or el.tag in ("button", "a", "li")):
                    periods.append({"kind": "click", "label": m.group(1), "value": m.group(1)})
        uniq, seen = [], set()
        for p in periods:
            if p["label"] not in seen:
                seen.add(p["label"])
                uniq.append(p)
        return uniq

    def apply_period(self, period: dict[str, str]) -> bool:
        self.checkpoint()
        elements = self.snapshot()
        if period["kind"] == "select":
            for el in elements:
                if el.tag == "select" and any(o.get("value") == period["value"] for o in (el.options or [])):
                    assert_safe(el)
                    self.page.locator(el.selector).first.select_option(period["value"])
                    self.settle()
                    return True
            return False
        for el in elements:
            if (el.label or "").strip() == period["label"] and el.safe_to_click():
                self.click(el)
                self.settle()
                return True
        return False

    # ------------------------------------------------------------------ #
    # Paginierung
    # ------------------------------------------------------------------ #
    def pagination_step(self, state: PageScanState) -> bool:
        """Führt EINEN Paginierungsschritt aus. True, wenn eine Aktion möglich war."""
        self.checkpoint()
        if state.pagination_steps >= self.limits.max_load_more or state.pages >= self.limits.max_pages:
            state.limit_hit = True
            return False
        elements = self.snapshot()
        for el in elements:
            if el.tag != "select" and is_load_more(el.label) and el.safe_to_click() and not el.in_nav:
                self.click(el)
                state.pagination_steps += 1
                state.pages += 1
                self.settle()
                return True
        for el in elements:
            if el.tag != "select" and is_next_page(el.label, el.in_pagination) and el.safe_to_click():
                self.click(el)
                state.pagination_steps += 1
                state.pages += 1
                self.settle()
                return True
        # Infinite Scroll
        before = self.page.evaluate(SCROLL_JS)
        self.page.wait_for_timeout(max(800, self.limits.action_delay_ms))
        after = self.page.evaluate("() => document.documentElement.scrollHeight + Array.from("
                                   "document.querySelectorAll('main, [role=main], div, section, ul')).filter(e => {"
                                   "const s = getComputedStyle(e); return (s.overflowY==='auto'||s.overflowY==='scroll')"
                                   " && e.scrollHeight > e.clientHeight + 40}).reduce((a, e) => a + e.scrollHeight, 0)")
        if after > before:
            state.pagination_steps += 1
            state.pages += 1
            return True
        return False

    def iterate_pages(self, state: PageScanState) -> Iterator[list[Element]]:
        """Liefert Snapshots: aktuelle Seite, dann nach jedem Paginierungsschritt.
        Bricht ab, wenn nichts mehr nachgeladen wird oder zwei Schritte ohne neue Einträge bleiben."""
        state.pages = max(state.pages, 1)
        yield self.snapshot()
        stale = 0
        while True:
            seen_before = len(state.seen)
            if not self.pagination_step(state):
                state.exhausted = not state.limit_hit
                return
            yield self.snapshot()
            if len(state.seen) == seen_before:
                stale += 1
                if stale >= 2:
                    state.exhausted = True
                    return
            else:
                stale = 0
            if len(state.seen) >= self.limits.max_items:
                state.limit_hit = True
                return
