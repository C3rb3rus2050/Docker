from broker_collector.broker_adapter import DocumentArea, DocumentRef
from broker_collector.database import Database


def ref(title="Abrechnung", url="https://app.traderepublic.com/doc.pdf?X-Amz-Signature=SECRETSIG", **kw):
    return DocumentRef(broker="trade_republic", title=title, url=url, area="Postfach",
                       page_url="https://app.traderepublic.com/profile?token=PAGETOKEN", **kw)


def test_persistence_across_reopen(settings):
    db = Database(settings.database_path)
    run = db.start_run("trade_republic", "sync")
    r = ref()
    db.record_item(run, r, "failed", error="HTTP 503", count_attempt=True)
    db.close()

    db2 = Database(settings.database_path)
    item = db2.get_item("trade_republic", r.key)
    assert item["status"] == "failed" and item["attempts"] == 1 and item["error_message"] == "HTTP 503"
    assert db2.get_run(run)["status"] == "running"
    db2.close()


def test_status_transitions_and_skipped_known(db):
    r = ref()
    run1 = db.start_run("trade_republic", "sync")
    db.record_item(run1, r, "failed", error="x", count_attempt=True)
    db.record_item(run1, r, "downloaded", document_id=None, count_attempt=True)
    run2 = db.start_run("trade_republic", "sync")
    db.record_item(run2, r, "skipped_known")
    item = db.get_item("trade_republic", r.key)
    assert item["status"] == "downloaded"  # bleibt erhalten
    assert item["attempts"] == 2
    assert [x["status"] for x in db.run_results(run2)] == ["skipped_known"]
    counters = db.recompute_run_counters(run2)
    assert counters["skipped_known"] == 1 and counters["documents_found"] == 1


def test_no_secrets_in_database(db, settings):
    r = ref()
    run = db.start_run("trade_republic", "sync")
    db.record_source(run, r, r.url.split("?")[0])
    db.record_item(run, r, "failed", error="GET https://x.com/a?token=ABCDEF failed, cookie: s=COOKIEVAL",
                   count_attempt=True)
    db.upsert_failed_document("trade_republic", r.key, r.title, "failed", "Authorization: Bearer XYZXYZXYZXYZ",
                              r.url, r.page_url)
    db.update_run(run, message="session=SESSIONVAL")
    db.close()
    raw = settings.database_path.read_bytes()
    wal = settings.database_path.with_name(settings.database_path.name + "-wal")
    if wal.exists():
        raw += wal.read_bytes()
    for secret in (b"SECRETSIG", b"PAGETOKEN", b"ABCDEF", b"COOKIEVAL", b"XYZXYZXYZXYZ", b"SESSIONVAL"):
        assert secret not in raw, secret


def test_resume_helpers(db):
    run = db.start_run("scalable_capital", "full")
    a1 = DocumentArea("scalable_capital", "Postfach", url="https://de.scalable.capital/postbox", status="complete")
    a2 = DocumentArea("scalable_capital", "Steuern", url="https://de.scalable.capital/tax", status="partial")
    db.upsert_area(run, "scalable_capital", a1)
    db.upsert_area(run, "scalable_capital", a2)
    assert db.mark_stale_runs_interrupted() == 1
    interrupted = db.interrupted_run("scalable_capital")
    assert interrupted["id"] == run and interrupted["status"] == "interrupted"
    assert db.completed_area_keys(run) == {a1.key}


def test_markers(db):
    db.add_markers("trade_republic", "tr_event", ["a", "b"])
    db.add_markers("trade_republic", "tr_event", ["b", "c"])
    assert db.markers("trade_republic", "tr_event") == {"a", "b", "c"}
    assert db.markers("scalable_capital", "tr_event") == set()


def test_failed_document_replaced_by_success(db):
    r = ref()
    db.upsert_failed_document("trade_republic", r.key, r.title, "failed", "x")
    doc_id = db.insert_document(broker="trade_republic", doc_key=r.key, original_name="a.pdf", local_path="/x",
                                sha256="ab" * 32, file_size=1, download_status="downloaded")
    rows = db.query("SELECT * FROM documents WHERE doc_key = ?", (r.key,))
    assert len(rows) == 1 and rows[0]["id"] == doc_id and rows[0]["download_status"] == "downloaded"
    # Ein späterer Fehler überschreibt einen erfolgreichen Eintrag nicht
    db.upsert_failed_document("trade_republic", r.key, r.title, "failed", "y")
    assert db.query_one("SELECT download_status FROM documents WHERE id = ?", (doc_id,))["download_status"] == \
        "downloaded"
