import json

import pytest

from broker_collector.tr_api import (
    TRClient,
    TRProtocolError,
    TRSubscriptionError,
    apply_delta,
    build_connect,
    build_sub,
    extract_documents,
    parse_message,
)


class FakeTRServer:
    """Simuliert die Antworten des Trade-Republic-WebSockets (Mockdaten, keine echte Verbindung)."""

    def __init__(self, pages, details, delta_for=None, error_for=()):
        self.pages = pages  # {cursor or None: {"items": [...], "cursors": {...}}}
        self.details = details
        self.delta_for = delta_for or {}
        self.error_for = set(error_for)
        self.inbox: list[str] = []
        self.sent: list[str] = []
        self.opened = False

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def send(self, message: str):
        self.sent.append(message)
        if message.startswith("connect "):
            self.inbox.append("connected")
            return
        if message.startswith("unsub "):
            sub_id = message.split()[1]
            self.inbox.append(f"{sub_id} C")
            return
        _, sub_id, payload = message.split(" ", 2)
        data = json.loads(payload)
        if data["type"] in ("timelineTransactions", "timelineActivityLog"):
            page = self.pages[data["type"]].get(data.get("after"))
            self.inbox.append(f"{sub_id} A {json.dumps(page)}")
        elif data["type"] == "timelineDetailV2":
            if data["id"] in self.error_for:
                self.inbox.append(f'{sub_id} E {{"errors":[{{"errorCode":"NOT_FOUND"}}]}}')
            elif data["id"] in self.delta_for:
                self.inbox.append(f"{sub_id} D {self.delta_for[data['id']]}")
            else:
                self.inbox.append(f"{sub_id} A {json.dumps(self.details[data['id']])}")

    def recv(self, timeout_s):
        return self.inbox.pop(0) if self.inbox else None


def detail(doc_url, title="Abrechnung", detail_text="12.03.2024"):
    return {"id": "x", "sections": [
        {"type": "header", "title": "Kauf"},
        {"type": "documents", "title": "Dokumente", "data": [
            {"id": "doc-1", "title": title, "detail": detail_text, "postboxType": "SECURITIES_SETTLEMENT",
             "action": {"type": "browserModal", "payload": doc_url}},
            {"id": "doc-2", "title": "Unbekannt", "action": {"type": "x", "payload": {"path": "a"}}},
        ]},
    ]}


def test_messages():
    assert build_connect().startswith("connect 31 {")
    assert parse_message("connected") == (None, "connected", "")
    assert parse_message('7 A {"a":1}') == (7, "A", '{"a":1}')
    assert parse_message("7 C") == (7, "C", "")
    with pytest.raises(TRProtocolError):
        parse_message("garbage")


def test_only_read_subscriptions_allowed():
    build_sub(1, {"type": "timelineDetailV2", "id": "a"})
    for forbidden in ("simpleCreateOrder", "cancelOrder", "createPriceAlarm", "savingsPlans", "unknown"):
        with pytest.raises(TRProtocolError):
            build_sub(1, {"type": forbidden})


def test_delta():
    prev = '{"a":1,"b":"hello"}'
    # behalte 6 Zeichen ('{"a":1'), überspringe 0, füge ',"c":2' ein, behalte Rest
    delta = "=6\t+%2C%22c%22%3A2\t=13"
    assert apply_delta(prev, delta) == '{"a":1,"c":2,"b":"hello"}'
    assert apply_delta("abcdef", "=2\t-2\t=2") == "abef"


def test_client_pagination_and_details():
    pages = {
        "timelineTransactions": {
            None: {"items": [{"id": "e1", "timestamp": "2024-03-12T10:00:00.000+0000", "title": "Apple"},
                             {"id": "e2", "timestamp": "2024-02-01T10:00:00.000+0000", "title": "Tesla"}],
                   "cursors": {"after": "c1"}},
            "c1": {"items": [{"id": "e3", "timestamp": "2023-12-01T10:00:00.000+0000", "title": "Zinsen"}],
                   "cursors": {}},
        },
        "timelineActivityLog": {None: {"items": [], "cursors": {}}},
    }
    details = {"e1": detail("https://traderepublic-docs.s3.amazonaws.com/a.pdf?sig=1"),
               "e3": detail("https://traderepublic-docs.s3.amazonaws.com/c.pdf", "Zinsabrechnung", "")}
    server = FakeTRServer(pages, details, error_for={"e2"})
    client = TRClient(server, delay_s=0, timeout_s=2)
    client.connect()
    items = list(client.iterate_timeline("timelineTransactions"))
    assert [i["id"] for i in items] == ["e1", "e2", "e3"]
    docs, unusable = extract_documents(client.timeline_detail("e1"), items[0])
    assert len(docs) == 1 and docs[0].title == "Abrechnung" and docs[0].date == "2024-03-12"
    assert docs[0].doc_id == "doc-1" and len(unusable) == 1
    docs3, _ = extract_documents(client.timeline_detail("e3"), items[2])
    assert docs3[0].date == "2023-12-01"  # Fallback: Ereignisdatum
    with pytest.raises(TRSubscriptionError):
        client.timeline_detail("e2")
    # Jedes Abo wird wieder beendet
    subs = [m for m in server.sent if m.startswith("sub ")]
    unsubs = [m for m in server.sent if m.startswith("unsub ")]
    assert len(subs) == len(unsubs)


def test_client_stops_on_repeated_cursor():
    pages = {"timelineTransactions": {None: {"items": [{"id": "a"}], "cursors": {"after": "c"}},
                                      "c": {"items": [{"id": "b"}], "cursors": {"after": "c"}}}}
    client = TRClient(FakeTRServer(pages, {}), delay_s=0, timeout_s=2)
    client.connect()
    assert [i["id"] for i in client.iterate_timeline("timelineTransactions")] == ["a", "b"]


def test_connect_failure():
    class Silent(FakeTRServer):
        def send(self, message):
            self.sent.append(message)

    client = TRClient(Silent({}, {}), timeout_s=0.3, delay_s=0)
    with pytest.raises(TRProtocolError):
        client.connect()
