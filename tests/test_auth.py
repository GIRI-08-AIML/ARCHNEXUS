from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import SAMPLE_RFC, register_user


def _anon():
    return TestClient(app)


def test_register_login_me(client):
    anon = _anon()
    r = anon.post("/auth/login", json={"email": "ALICE@example.com ", "password": "correct-horse-1"})
    assert r.status_code == 200
    token = r.json()["access_token"]
    me = anon.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "alice@example.com"
    assert me.json()["company"] == "Acme"
    assert "password" not in me.text


def test_duplicate_email_rejected(client):
    r = _anon().post(
        "/auth/register",
        json={"name": "X", "email": "Alice@Example.com", "password": "another-pass-1"},
    )
    assert r.status_code == 409


def test_bad_registration_input(client):
    anon = _anon()
    base = {"name": "X", "email": "x@example.com", "password": "longenough1"}
    assert anon.post("/auth/register", json={**base, "password": "short"}).status_code == 422
    assert anon.post("/auth/register", json={**base, "email": "nope"}).status_code == 422


def test_wrong_password_and_unknown_user_look_the_same(client):
    anon = _anon()
    a = anon.post("/auth/login", json={"email": "alice@example.com", "password": "wrong-password"})
    b = anon.post("/auth/login", json={"email": "ghost@example.com", "password": "wrong-password"})
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_endpoints_require_login(client):
    anon = _anon()
    for method, path in [
        ("get", "/projects"),
        ("post", "/projects"),
        ("get", "/reviews"),
        ("get", "/reviews/1"),
        ("get", "/auth/me"),
    ]:
        assert getattr(anon, method)(path).status_code == 401, path
    assert anon.get("/auth/me", headers={"Authorization": "Bearer junk"}).status_code == 401


def test_users_cannot_see_each_others_data(client):
    pid = client.post("/projects", json={"name": "Alice's", "rfc_text": SAMPLE_RFC}).json()["id"]
    rid = client.post(f"/projects/{pid}/reviews").json()["id"]

    bob = _anon()
    bob.headers.update(register_user(bob, "bob@other.com", name="Bob", company="Other Co"))
    assert bob.get("/projects").json() == []
    assert bob.get("/reviews").json() == []
    for path in [
        f"/projects/{pid}",
        f"/projects/{pid}/reviews",
        f"/reviews/{rid}",
        f"/reviews/{rid}/findings",
        f"/reviews/{rid}/debates",
        f"/reviews/{rid}/report",
    ]:
        assert bob.get(path).status_code == 404, path
    assert bob.post(f"/projects/{pid}/reviews").status_code == 404
    assert bob.delete(f"/projects/{pid}").status_code == 404

    # Alice still has everything
    assert len(client.get("/projects").json()) == 1
    assert client.get(f"/reviews/{rid}").status_code == 200
