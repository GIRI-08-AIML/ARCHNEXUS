def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "ArchNexus" in r.text


def test_static_assets_served(client):
    assert client.get("/ui/app.js").status_code == 200
    assert client.get("/ui/styles.css").status_code == 200


def test_reviews_list(client):
    from tests.conftest import SAMPLE_RFC

    pid = client.post("/projects", json={"name": "Demo", "rfc_text": SAMPLE_RFC}).json()["id"]
    client.post(f"/projects/{pid}/reviews")
    rows = client.get("/reviews?limit=5").json()
    assert rows and rows[0]["project_name"] == "Demo"
    assert {"status", "decision", "score"} <= rows[0].keys()
