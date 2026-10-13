"""Abgleich der Dokumentquellen (UI ↔ API ↔ Netzwerk).

Jede Quelle liefert Datensätze (Titel, Datum, URL-Basis, Kennung, ggf. SHA-256 nach dem
Download). Datensätze werden zu Gruppen zusammengeführt, wenn sie

1. denselben SHA-256-Hash haben (stärkstes Kriterium – identischer Inhalt),
2. dieselbe URL-Basis (ohne Signatur-Parameter) haben,
3. dieselbe Brokerkennung haben,
4. denselben normalisierten Titel UND dasselbe Datum haben (schwächstes Kriterium, nur mit Datum).

Ergebnis: Dokumente, die in allen aktiven Quellen gefunden wurden, und Dokumente, die nur in
einer Quelle auftauchen – letztere sind Hinweise auf Lücken der jeweils anderen Quelle.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .broker_adapter import normalize_title

SOURCE_NAMES = {"ui": "Weboberfläche", "api": "WebSocket-Schnittstelle", "network": "Webapp-Datenantworten"}


class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


@dataclass
class ReconciliationResult:
    sources: list[str]
    groups: list[dict[str, Any]] = field(default_factory=list)
    only_in: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    in_all: int = 0
    per_source: dict[str, int] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": self.sources,
            "source_names": {s: SOURCE_NAMES.get(s, s) for s in self.sources},
            "unique_documents": len(self.groups),
            "in_all_sources": self.in_all,
            "per_source": self.per_source,
            "only_in": self.only_in,
            "note": self.note,
        }


def reconcile(records: list[dict[str, Any]]) -> ReconciliationResult:
    """``records``: Zeilen aus ``Database.source_records`` (source, title, doc_date, url_base,
    external_id, sha256, item_status)."""
    sources = sorted({r["source"] for r in records})
    result = ReconciliationResult(sources=sources)
    result.per_source = {s: sum(1 for r in records if r["source"] == s) for s in sources}
    if not records:
        result.note = "Keine Dokumente gefunden – kein Abgleich möglich."
        return result

    uf = _UnionFind(len(records))
    index: dict[tuple[str, str], int] = {}

    def link(kind: str, value: Any, i: int) -> None:
        if not value:
            return
        key = (kind, str(value))
        if key in index:
            uf.union(index[key], i)
        else:
            index[key] = i

    for i, r in enumerate(records):
        link("sha", r.get("sha256"), i)
        link("url", r.get("url_base"), i)
        link("id", r.get("external_id"), i)
        title = normalize_title(r.get("title") or "")
        if title and r.get("doc_date"):
            link("td", f"{title}|{r['doc_date']}", i)

    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, r in enumerate(records):
        grouped[uf.find(i)].append(r)

    for members in grouped.values():
        srcs = sorted({m["source"] for m in members})
        rep = next((m for m in members if m.get("sha256")), members[0])
        group = {
            "title": rep.get("title"), "date": rep.get("doc_date"), "sources": srcs,
            "sha256": rep.get("sha256"), "statuses": sorted({m.get("item_status") or "" for m in members}),
        }
        result.groups.append(group)
        if len(srcs) == len(sources):
            result.in_all += 1
        elif len(srcs) == 1:
            result.only_in.setdefault(srcs[0], []).append(group)
        else:
            for s in sources:
                if s not in srcs:
                    result.only_in.setdefault(f"fehlt_in_{s}", []).append(group)

    if len(sources) < 2:
        result.note = (f"Nur eine Quelle aktiv ({SOURCE_NAMES.get(sources[0], sources[0])}) – "
                       "ein Quellenabgleich war nicht möglich.")
    elif result.in_all == len(result.groups):
        result.note = "Alle gefundenen Dokumente wurden in allen aktiven Quellen übereinstimmend gefunden."
    else:
        result.note = ("Abweichungen zwischen den Quellen gefunden. Dokumente, die nur in einer Quelle "
                       "auftauchen, deuten auf Lücken der anderen Quelle hin und sollten geprüft werden.")
    return result
