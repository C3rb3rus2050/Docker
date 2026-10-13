import json
from pathlib import Path

from broker_collector.broker_adapter import DocumentArea, DocumentRef
from broker_collector.reconciliation import reconcile
from broker_collector.reporting import build_report, write_report


def rec(source, title, date=None, url=None, ext=None, sha=None, status="downloaded"):
    return {"source": source, "title": title, "doc_date": date, "url_base": url, "external_id": ext,
            "sha256": sha, "item_status": status}


def test_reconcile_matches_by_hash_url_id_titledate():
    records = [
        rec("ui", "Abrechnung", "2024-03-12", sha="h1"),
        rec("api", "Wertpapierabrechnung", "2024-03-12", sha="h1", ext="doc-1"),
        rec("ui", "Kontoauszug", url="https://x/k.pdf"),
        rec("api", "Kontoauszug Jan", url="https://x/k.pdf"),
        rec("ui", "Dividende Apple", "2024-04-01"),
        rec("api", "Dividende  apple", "2024-04-01"),
        rec("api", "Zinsabrechnung", "2024-05-01", ext="doc-9"),
        rec("ui", "Kosteninformation"),
    ]
    r = reconcile(records)
    assert r.sources == ["api", "ui"]
    assert len(r.groups) == 5 and r.in_all == 3
    assert [g["title"] for g in r.only_in["api"]] == ["Zinsabrechnung"]
    assert [g["title"] for g in r.only_in["ui"]] == ["Kosteninformation"]
    assert "Abweichungen" in r.note


def test_reconcile_single_source():
    r = reconcile([rec("ui", "A")])
    assert "Nur eine Quelle" in r.note


def test_titles_without_date_not_merged():
    r = reconcile([rec("ui", "Kontoauszug"), rec("api", "Kontoauszug")])
    assert len(r.groups) == 2


def test_report_never_claims_full_completeness(db, settings):
    run = db.start_run("trade_republic", "full")
    db.upsert_area(run, "trade_republic", DocumentArea("trade_republic", "Postfach", url="https://a/p",
                                                       status="complete", pages_visited=3, periods=["2024", "2023"]))
    db.upsert_area(run, "trade_republic", DocumentArea("trade_republic", "Steuern", url="https://a/s",
                                                       status="partial", pages_visited=1, note="Limit erreicht"))
    db.upsert_area(run, "trade_republic", DocumentArea("trade_republic", "Archiv", url="https://a/x",
                                                       status="inaccessible"))
    ok = DocumentRef("trade_republic", "Abrechnung", url="https://a/1.pdf", area="Postfach")
    bad = DocumentRef("trade_republic", "Kontoauszug", url="https://a/2.pdf", area="Postfach")
    manual = DocumentRef("trade_republic", "Steuerbescheinigung anfordern", area="Steuern", downloadable=False)
    db.record_item(run, ok, "downloaded")
    db.record_item(run, bad, "failed", error="HTTP 500")
    db.record_item(run, manual, "not_downloadable", error="Nur manuell anforderbar")
    for r in (ok, bad, manual):
        db.record_source(run, r, r.url)
    db.finish_run(run, "finished_with_errors")

    rep = build_report(db, run)
    assert rep["summary"]["downloaded"] == 1 and rep["summary"]["failed"] == 1
    assert rep["summary"]["not_downloadable"] == 1 and rep["summary"]["pages_visited"] == 4
    assert set(rep["areas"]) == {"complete", "partial", "inaccessible"}
    assert rep["periods"] == ["2023", "2024"]
    assert "NICHT als vollständig verifiziert" in rep["verdict"]
    assert any("teilweise" in h for h in rep["hints"])

    paths = write_report(db, run, settings.reports_dir)
    data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert data["broker_name"] == "Trade Republic"
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "Teilweise untersucht" in md and "Nicht zugänglich" in md and "HTTP 500" in md
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "<script" not in html


def test_report_html_escapes_titles(db, settings):
    run = db.start_run("scalable_capital", "sync")
    evil = DocumentRef("scalable_capital", "<script>alert(1)</script>", url="https://a/1.pdf", area="X")
    db.record_item(run, evil, "failed", error="<img src=x onerror=alert(1)>")
    db.finish_run(run, "finished_with_errors")
    html = Path(write_report(db, run, settings.reports_dir)["html"]).read_text(encoding="utf-8")
    assert "<script>alert" not in html and "<img src=x" not in html
