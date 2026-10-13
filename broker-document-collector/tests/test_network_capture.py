from broker_collector.network_capture import NetworkDocumentExtractor
from broker_collector.security import UrlPolicy

policy = UrlPolicy(("scalable.capital",))


def test_rest_document_list():
    payload = {"documents": [
        {"id": "d1", "title": "Wertpapierabrechnung Kauf", "createdAt": "2024-03-12T09:00:00Z",
         "downloadUrl": "https://de.scalable.capital/api/documents/d1/download"},
        {"id": "d2", "title": "Kontoauszug", "date": 1706659200000,
         "links": {"href": "https://de.scalable.capital/files/d2.pdf"}},
        {"id": "d3", "title": "Fremd", "downloadUrl": "https://evil.example.com/x.pdf"},
    ]}
    docs = NetworkDocumentExtractor(policy).extract(payload, "https://de.scalable.capital/api/x")
    by_id = {d.external_id: d for d in docs}
    assert by_id["d1"].url.endswith("/download") and by_id["d1"].date == "2024-03-12"
    assert by_id["d2"].date == "2024-01-31" and by_id["d2"].url.endswith("d2.pdf")
    # Fremder Host wird nicht als Download übernommen, Metadaten bleiben für den Abgleich
    assert by_id["d3"].url == ""


def test_graphql_like_metadata_without_url():
    payload = {"data": {"account": {"postbox": {"items": [
        {"__typename": "PostboxDocument", "id": "p1", "subject": "Steuerbescheinigung 2023",
         "publishedAt": "2024-02-15"},
        {"__typename": "PostboxDocument", "id": "p2", "subject": "Depotauszug", "publishedAt": "2024-01-02"},
    ]}}}}
    docs = NetworkDocumentExtractor(policy).extract(payload)
    assert {(d.external_id, d.title, d.date) for d in docs} == {
        ("p1", "Steuerbescheinigung 2023", "2024-02-15"), ("p2", "Depotauszug", "2024-01-02")}
    assert not any(d.downloadable for d in docs)


def test_ignores_unrelated_json():
    payload = {"portfolio": {"positions": [{"id": 1, "name": "Apple", "url": "https://de.scalable.capital/p/1"}]}}
    assert NetworkDocumentExtractor(policy).extract(payload) == []


def test_depth_and_size_limits():
    node = {"x": 1}
    for _ in range(50):
        node = {"child": node}
    assert NetworkDocumentExtractor(policy).extract(node) == []
