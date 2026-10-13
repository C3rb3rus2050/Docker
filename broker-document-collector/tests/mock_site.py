"""Mockseiten für Integrationstests (über Playwright-Routing ausgeliefert, kein echter Broker).

Enthält bewusst „Fallen“: Kauf-/Abmelde-/Anforderungs-Schaltflächen, deren Betätigung als
Sicherheitsverstoß protokolliert wird.
"""

from __future__ import annotations

import base64
import json

from conftest import make_pdf

PDFS = {
    "kauf-apple-2024.pdf": make_pdf("Wertpapierabrechnung Kauf Apple\nDatum: 12.03.2024"),
    "konto-2024-01.pdf": make_pdf("Kontoauszug Januar 2024\nDatum: 31.01.2024"),
    "dividende-msft-2024.pdf": make_pdf("Dividende Microsoft\nZahltag: 14.03.2024"),
    "zinsen-2024-02.pdf": make_pdf("Zinsabrechnung Februar 2024"),
    "konto-2023-12.pdf": make_pdf("Kontoauszug Dezember 2023"),
    "jsb-2023.pdf": make_pdf("Jahressteuerbescheinigung 2023"),
    "kosten-2024.pdf": make_pdf("Kosteninformation Ex-post 2024"),
    "blob-depot-2024.pdf": make_pdf("Depotauszug 31.12.2024"),
    "apple-tx.pdf": make_pdf("Wertpapierabrechnung Kauf Apple\nDatum: 12.03.2024"),  # gleicher Inhalt? nein:
    "nur-api.pdf": make_pdf("Verkauf Tesla Abrechnung 2024"),
}
PDFS["apple-tx.pdf"] = PDFS["kauf-apple-2024.pdf"]  # identischer Inhalt → Duplikat per SHA-256

STYLE = "<style>li{margin:4px} dialog{display:block}</style>"


def layout(body: str, title: str = "Mock Broker") -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>{STYLE}</head><body>
<header><nav>
 <a href="/postfach">Postfach</a> <a href="/steuern">Steuern</a> <a href="/portfolio">Portfolio</a>
 <a href="/transaktionen">Transaktionen</a> <a href="/logout">Abmelden</a>
</nav></header>
<main>
 <button onclick="fetch('/api/danger?a=buy')">Jetzt kaufen</button>
 {body}
</main></body></html>"""


HOME = layout("<h1>Übersicht</h1><p>Willkommen</p>")
PORTFOLIO = layout("<h1>Portfolio</h1><ul><li>Apple 10 Stück</li></ul><button onclick=\"fetch('/api/danger?a=sell')\">"
                   "Verkaufen</button>")

POSTFACH = layout("""
<h1>Postfach</h1>
<label for="jahr">Jahr</label>
<select id="jahr" onchange="render(this.value, 2)"><option value="2024">2024</option><option value="2023">2023</option></select>
<ul id="list"></ul>
<div id="more"></div>
<button onclick="fetch('/api/danger?a=request')">Steuerbescheinigung anfordern</button>
<script>
const DATA = {
  "2024": [
    {t: "Abrechnung Kauf Apple 12.03.2024", f: "kauf-apple-2024.pdf"},
    {t: "Kontoauszug 31.01.2024", f: "konto-2024-01.pdf"},
    {t: "Dividende Microsoft 14.03.2024", f: "dividende-msft-2024.pdf"},
    {t: "Zinsabrechnung 29.02.2024", f: "zinsen-2024-02.pdf"},
  ],
  "2023": [{t: "Kontoauszug 31.12.2023", f: "konto-2023-12.pdf"}],
};
let shown = 2;
function render(year, n) {
  shown = n;
  const items = DATA[year].slice(0, n);
  document.getElementById('list').innerHTML = items.map(i => `<li><a href="/files/${i.f}">${i.t}</a></li>`).join('')
    + (year === "2024" ? `<li>Depotauszug 31.12.2024 <button onclick="dl()">PDF herunterladen</button></li>
       <li><button onclick="viewer()">Kosteninformation 2024</button></li>` : '');
  document.getElementById('more').innerHTML = n < DATA[year].length
    ? `<button onclick="render(document.getElementById('jahr').value, shown + 2)">Mehr laden</button>` : '';
}
function dl() {
  const bytes = Uint8Array.from(atob("__BLOB__"), c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: 'application/pdf'}));
  const a = document.createElement('a'); a.href = url; a.download = 'Depotauszug_2024.pdf';
  document.body.appendChild(a); a.click(); a.remove();
}
function viewer() {
  const d = document.createElement('div'); d.setAttribute('role', 'dialog'); d.setAttribute('aria-modal', 'true');
  d.innerHTML = '<iframe src="/files/kosten-2024.pdf" width="400" height="300"></iframe>';
  document.body.appendChild(d);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') d.remove(); }, {once: true});
}
render("2024", 2);
fetch('/api/postbox').then(r => r.json());
</script>
""").replace("__BLOB__", base64.b64encode(PDFS["blob-depot-2024.pdf"]).decode())

STEUERN = layout("""
<h1>Steuern</h1>
<ul>
 <li><a href="/files/jsb-2023.pdf">Jahressteuerbescheinigung 2023</a></li>
 <li><a href="/files/broken.pdf">Verlustbescheinigung 2023</a></li>
</ul>""")

TRANSAKTIONEN = layout("""
<h1>Transaktionen</h1>
<ul id="tx">
 <li role="button" tabindex="0" onclick="openTx()">Apple Inc. Kauf 12.03.2024 −1.234,00 €</li>
</ul>
<script>
function openTx() {
  const d = document.createElement('div'); d.setAttribute('role', 'dialog');
  d.innerHTML = '<h2>Apple Inc.</h2><a href="/files/apple-tx.pdf">Abrechnung</a>' +
                '<button onclick="fetch(\\'/api/danger?a=repeat\\')">Erneut kaufen</button>';
  document.body.appendChild(d);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') d.remove(); }, {once: true});
}
</script>""")

POSTBOX_JSON = {"documents": [
    {"id": "n1", "title": "Abrechnung Kauf Apple", "createdAt": "2024-03-12",
     "downloadUrl": "https://app.broker.test/files/kauf-apple-2024.pdf"},
    {"id": "n2", "title": "Verkauf Tesla", "createdAt": "2024-06-01",
     "downloadUrl": "https://app.broker.test/files/nur-api.pdf"},
]}

LOGIN_HTML = "<!doctype html><html><body><h1>Anmelden</h1><input type='password'></body></html>"


class MockSite:
    def __init__(self, host: str = "app.broker.test"):
        self.host = host
        self.danger: list[str] = []
        self.requests: list[str] = []

    def handler(self, route, request):
        url = request.url
        self.requests.append(url)
        path = url.split(self.host, 1)[-1].split("?")[0] or "/"
        if path.startswith("/api/danger") or path in ("/logout", "/buy"):
            self.danger.append(url)
            return route.fulfill(status=200, body="{}", content_type="application/json")
        pages = {"/": HOME, "/postfach": POSTFACH, "/steuern": STEUERN, "/portfolio": PORTFOLIO,
                 "/transaktionen": TRANSAKTIONEN}
        if path in pages:
            return route.fulfill(status=200, body=pages[path], content_type="text/html; charset=utf-8")
        if path == "/api/postbox":
            return route.fulfill(status=200, body=json.dumps(POSTBOX_JSON), content_type="application/json")
        if path == "/files/broken.pdf":
            return route.fulfill(status=200, body=LOGIN_HTML, content_type="text/html")
        if path.startswith("/files/") and path[7:] in PDFS:
            return route.fulfill(status=200, body=PDFS[path[7:]], content_type="application/pdf",
                                 headers={"Access-Control-Allow-Origin": "*"})
        return route.fulfill(status=404, body="not found")
