"""Laden und Abfragen der versionierten Steuerregeln (``data/tax_rules.yaml``)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).resolve().parents[1] / "data" / "tax_rules.yaml"

OFFICIAL = "offiziell_auszug"
SECONDARY = "sekundaer"
UNVERIFIED = "nicht_verifiziert"
STATUS_LABELS = {
    OFFICIAL: "offiziell belegt (Auszug)",
    SECONDARY: "nur Sekundärquelle – vorläufig",
    UNVERIFIED: "nicht verifiziert – keine Berechnung",
}


class YearNotSupported(ValueError):
    pass


@dataclass(frozen=True)
class RuleInfo:
    rule_id: str
    title: str
    legal_basis: str
    status: str
    sources: tuple[str, ...]
    logic: str
    limitations: str

    @property
    def computable(self) -> bool:
        return self.status in (OFFICIAL, SECONDARY)

    @property
    def provisional(self) -> bool:
        return self.status != OFFICIAL

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)


class TaxRules:
    def __init__(self, data: dict):
        self.data = data
        self.rules: dict = data.get("rules", {})
        self.sources: dict = data.get("sources", {})

    @property
    def last_review(self) -> str:
        return str(self.data.get("meta", {}).get("last_review", ""))

    def supported_years(self) -> list[int]:
        years: set[int] = set()
        for r in self.rules.values():
            years |= {int(y) for y in (r.get("status") or {})}
        return sorted(years)

    def check_year(self, year: int) -> None:
        if int(year) not in self.supported_years():
            raise YearNotSupported(
                f"Für das Steuerjahr {year} sind keine Steuerregeln hinterlegt. Es wird nichts berechnet. "
                "Bitte Regeln in tax_rules.yaml nach Prüfung der Rechtsgrundlagen ergänzen.")

    def rule(self, rule_id: str, year: int) -> RuleInfo:
        r = self.rules[rule_id]
        status = (r.get("status") or {}).get(int(year), UNVERIFIED)
        return RuleInfo(rule_id, r.get("title", rule_id), r.get("legal_basis", ""), status,
                        tuple(r.get("sources", []) or []), r.get("logic", ""), r.get("limitations", "") or "")

    def param(self, rule_id: str, key: str, default=None):
        return self.rules.get(rule_id, {}).get(key, default)

    def rate(self, rule_id: str) -> float:
        return float(self.rules[rule_id]["rate"])

    def source_text(self, ids) -> str:
        out = []
        for sid in ids or []:
            s = self.sources.get(sid)
            out.append(f"{s['title']} <{s['url']}>" if s else sid)
        return "; ".join(out)

    def dba_rate(self, country: str | None) -> dict | None:
        if not country:
            return None
        return (self.data.get("dba_dividend_rates") or {}).get(country.upper())

    def e1kv(self, year: int) -> dict:
        return (self.data.get("e1kv") or {}).get(int(year)) or {"form": "nicht hinterlegt", "fields": {}, "notes": []}

    def catalog(self) -> list[dict]:
        rows = []
        for rid, r in self.rules.items():
            for y, st in sorted((r.get("status") or {}).items()):
                rows.append({
                    "Regel-ID": rid, "Titel": r.get("title"), "Rechtsgrundlage": r.get("legal_basis"),
                    "Steuerjahr": int(y), "Status": STATUS_LABELS.get(st, st),
                    "Quellen": self.source_text(r.get("sources")), "Logik": r.get("logic"),
                    "Einschränkungen": r.get("limitations"), "Tests": ", ".join(r.get("tests", []) or []),
                    "Letzte Prüfung": self.last_review,
                })
        return rows


@lru_cache(maxsize=4)
def _load(path: str, mtime: float) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def load_rules(path: Path | None = None) -> TaxRules:
    p = Path(path or RULES_FILE)
    return TaxRules(_load(str(p), p.stat().st_mtime))
