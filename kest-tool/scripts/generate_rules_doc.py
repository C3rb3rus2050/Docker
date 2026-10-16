"""Erzeugt docs/STEUERREGELN.md aus src/kest_tool/data/tax_rules.yaml (python scripts/generate_rules_doc.py)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kest_tool.tax.rules import STATUS_LABELS, load_rules  # noqa: E402


def main() -> None:
    r = load_rules()
    out = ["# Steuerregeln des KESt-Tools", "",
           "> Automatisch erzeugt aus `src/kest_tool/data/tax_rules.yaml` – nicht von Hand bearbeiten.", "",
           f"Letzte Überprüfung: **{r.last_review}**", f"Hinweis: {r.data['meta']['access_note']}", "",
           "## Verifikationsstatus", "",
           "| Status | Bedeutung | Wirkung in der Berechnung |", "|---|---|---|",
           f"| {STATUS_LABELS['offiziell_auszug']} | durch Auszug einer offiziellen Quelle bestätigt | berechnet |",
           f"| {STATUS_LABELS['sekundaer']} | nur Sekundärquellen | berechnet, als **vorläufig** markiert |",
           f"| {STATUS_LABELS['nicht_verifiziert']} | keine belastbare Grundlage | **kein Betrag**, Position „manuell steuerlich zu prüfen“ |",
           "", "Steuerjahre ohne Eintrag in der Regeldatei werden vollständig abgelehnt (keine Berechnung).", "",
           "## Regeln", ""]
    for rid, rule in r.rules.items():
        out += [f"### {rid} – {rule['title']}", "",
                f"- **Rechtsgrundlage:** {rule.get('legal_basis', '')}"]
        if "rate" in rule:
            out.append(f"- **Satz:** {rule['rate']:.1%}".replace(".", ","))
        status = ", ".join(f"{y}: {STATUS_LABELS[s]}" for y, s in sorted((rule.get('status') or {}).items()))
        out += [f"- **Gültigkeit / Status je Steuerjahr:** {status}",
                f"- **Implementierte Logik:** {rule.get('logic', '')}",
                f"- **Bekannte Einschränkungen:** {rule.get('limitations') or '–'}",
                f"- **Quellen:** {r.source_text(rule.get('sources')) or 'keine'}",
                f"- **Tests:** {', '.join(f'`{t}`' for t in rule.get('tests', []) or []) or '–'}",
                f"- **Letzte Prüfung:** {r.last_review}", ""]
    out += ["## Quellen", "", "| ID | Titel | Art | URL |", "|---|---|---|---|"]
    out += [f"| {sid} | {s['title']} | {s['kind']} | <{s['url']}> |" for sid, s in r.sources.items()]
    out += ["", "## DBA-Quellensteuersätze (Dividenden)", "", "| Land | Satz | verifiziert | Hinweis |",
            "|---|---|---|---|"]
    for c, d in r.data["dba_dividend_rates"].items():
        rate = f"{d['rate']:.0%}" if d.get("rate") is not None else "–"
        out.append(f"| {c} | {rate} | {'ja' if d['verified'] else 'nein'} | {d['note']} |")
    out += ["", "## E 1kv-Kennzahlen", ""]
    for y in sorted(r.data["e1kv"]):
        spec = r.e1kv(y)
        out += [f"### {y} – {spec['form']}", ""]
        if spec.get("fields"):
            out += ["| Schlüssel | KZ | Bezeichnung | Status |", "|---|---|---|---|"]
            out += [f"| {k} | {f['kz']} | {f['label']} | {STATUS_LABELS.get(f['status'], f['status'])} |"
                    for k, f in spec["fields"].items()]
        out += [f"- {n}" for n in spec.get("notes", [])] + [""]
    (ROOT / "docs" / "STEUERREGELN.md").write_text("\n".join(out), encoding="utf-8")
    print("docs/STEUERREGELN.md geschrieben")


if __name__ == "__main__":
    main()
