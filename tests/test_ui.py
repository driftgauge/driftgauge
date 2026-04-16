from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_index_page_loads() -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert "Driftgauge" in res.text
    assert "Public monitoring overview" in res.text
    assert "Evaluation inputs" in res.text
