from fastapi.testclient import TestClient

from app.login_limiter import LoginLimiter, login_limiter
from app.main import app

KW = dict(max_per_account=3, max_per_ip=6, window=60)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


# ---------------------------------------------------------------- the limiter itself
def test_blocks_after_the_limit_and_reports_a_wait():
    clock = Clock()
    lim = LoginLimiter(clock)
    for _ in range(3):
        assert lim.blocked_for("1.1.1.1", "a@x.com", **KW) == 0
        lim.record_failure("1.1.1.1", "a@x.com", window=60)
    wait = lim.blocked_for("1.1.1.1", "a@x.com", **KW)
    assert 55 <= wait <= 61


def test_lockout_ends_after_the_window():
    clock = Clock()
    lim = LoginLimiter(clock)
    for _ in range(3):
        lim.record_failure("1.1.1.1", "a@x.com", window=60)
    assert lim.blocked_for("1.1.1.1", "a@x.com", **KW) > 0
    clock.t += 61
    assert lim.blocked_for("1.1.1.1", "a@x.com", **KW) == 0


def test_a_stranger_cannot_lock_you_out_from_another_address():
    lim = LoginLimiter(Clock())
    for _ in range(3):
        lim.record_failure("6.6.6.6", "victim@x.com", window=60)
    assert lim.blocked_for("6.6.6.6", "victim@x.com", **KW) > 0
    assert lim.blocked_for("2.2.2.2", "victim@x.com", **KW) == 0  # the real owner, elsewhere


def test_spraying_many_accounts_from_one_address_is_blocked():
    lim = LoginLimiter(Clock())
    for i in range(6):
        lim.record_failure("6.6.6.6", f"user{i}@x.com", window=60)  # one failure each
    assert lim.blocked_for("6.6.6.6", "fresh@x.com", **KW) > 0
    assert lim.blocked_for("7.7.7.7", "fresh@x.com", **KW) == 0


def test_a_correct_password_clears_the_account_counter():
    lim = LoginLimiter(Clock())
    for _ in range(2):
        lim.record_failure("1.1.1.1", "a@x.com", window=60)
    lim.reset("1.1.1.1", "a@x.com")
    lim.record_failure("1.1.1.1", "a@x.com", window=60)
    assert lim.blocked_for("1.1.1.1", "a@x.com", **KW) == 0


def test_memory_is_bounded():
    lim = LoginLimiter(Clock())
    lim.MAX_KEYS = 50
    for i in range(200):
        lim.record_failure("1.1.1.1", f"u{i}@x.com", window=60)
    lim.clock = lambda: 5000.0  # long after the window: everything is stale
    lim.record_failure("1.1.1.1", "last@x.com", window=60)
    assert len(lim._failures) < 10


# ---------------------------------------------------------------------- through the API
def test_login_is_locked_after_repeated_wrong_passwords(client):
    anon = TestClient(app)
    bad = {"email": "alice@example.com", "password": "wrong-password"}
    for _ in range(5):
        assert anon.post("/auth/login", json=bad).status_code == 401
    r = anon.post("/auth/login", json=bad)
    assert r.status_code == 429
    assert "Too many failed sign-in attempts" in r.json()["detail"]
    assert int(r.headers["Retry-After"]) > 0
    # Even the right password has to wait while locked.
    good = {"email": "alice@example.com", "password": "correct-horse-1"}
    assert anon.post("/auth/login", json=good).status_code == 429


def test_login_works_again_after_the_lockout_passes(client):
    anon = TestClient(app)
    clock = Clock()
    login_limiter.clock = clock
    try:
        bad = {"email": "alice@example.com", "password": "wrong-password"}
        for _ in range(5):
            anon.post("/auth/login", json=bad)
        assert anon.post("/auth/login", json=bad).status_code == 429
        clock.t += 15 * 60 + 5
        good = {"email": "alice@example.com", "password": "correct-horse-1"}
        assert anon.post("/auth/login", json=good).status_code == 200
    finally:
        import time

        login_limiter.clock = time.monotonic


def test_a_few_typos_do_not_lock_anyone_out(client):
    anon = TestClient(app)
    for _ in range(3):
        anon.post("/auth/login", json={"email": "alice@example.com", "password": "typo-typo-1"})
    good = {"email": "alice@example.com", "password": "correct-horse-1"}
    assert anon.post("/auth/login", json=good).status_code == 200
    # ...and success clears the counter, so three more typos are fine again.
    for _ in range(3):
        anon.post("/auth/login", json={"email": "alice@example.com", "password": "typo-typo-1"})
    assert anon.post("/auth/login", json=good).status_code == 200
