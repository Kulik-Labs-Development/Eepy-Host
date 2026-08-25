"""Auth flow: login with username OR email, case-insensitive usernames.

Covers the three login-flow fixes:
- the identifier may be a username or the account email;
- usernames (and emails) match case-insensitively at login;
- signup rejects usernames that clash only by case (and emails case-insensitively).
"""

import random

PASSWORD = "auth-flow-pass-1"


def _rand():
    return random.randint(10000, 99999)


def _signup(client, username, email):
    r = client.post("/auth/signup", json={
        "username": username, "email": email, "password": PASSWORD,
    })
    assert r.status_code == 200, r.text
    return r.json()


def test_login_by_username(client):
    n = _rand()
    _signup(client, f"flowuser{n}", f"flowuser{n}@example.com")
    r = client.post("/auth/login", json={"username": f"flowuser{n}", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == f"flowuser{n}"


def test_login_by_email(client):
    n = _rand()
    username = f"flowmail{n}"
    _signup(client, username, f"flowmail{n}@example.com")
    r = client.post("/auth/login", json={"username": f"flowmail{n}@example.com", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == username


def test_login_by_email_is_case_insensitive(client):
    n = _rand()
    username = f"flowcase{n}"
    _signup(client, username, f"FlowCase{n}@example.com")
    r = client.post("/auth/login", json={"username": f"flowcase{n}@EXAMPLE.COM", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == username


def test_login_by_username_is_case_insensitive(client):
    n = _rand()
    _signup(client, f"FlowUser{n}", f"flowuser{n}@example.com")
    r = client.post("/auth/login", json={"username": f"flowuser{n}", "password": PASSWORD})
    assert r.status_code == 200, r.text
    assert r.json()["user"]["username"] == f"FlowUser{n}"


def test_signup_rejects_username_clash_only_by_case(client):
    n = _rand()
    _signup(client, f"ClashUser{n}", f"clasha{n}@example.com")
    r = client.post("/auth/signup", json={
        "username": f"clashuser{n}", "email": f"clashb{n}@example.com", "password": PASSWORD,
    })
    assert r.status_code == 400, r.text
    assert "case-insensitive" in r.json()["detail"].lower()


def test_signup_rejects_email_clash_only_by_case(client):
    n = _rand()
    _signup(client, f"mailclash{n}", f"MailClash{n}@example.com")
    r = client.post("/auth/signup", json={
        "username": f"mailclash2{n}", "email": f"mailclash{n}@EXAMPLE.com", "password": PASSWORD,
    })
    assert r.status_code == 400, r.text


def test_login_unknown_identifier(client):
    r = client.post("/auth/login", json={"username": f"nosuchuser{_rand()}", "password": PASSWORD})
    assert r.status_code == 401, r.text
    assert "username or email" in r.json()["detail"].lower()


def test_login_wrong_password(client):
    n = _rand()
    _signup(client, f"wrongpass{n}", f"wrongpass{n}@example.com")
    r = client.post("/auth/login", json={"username": f"wrongpass{n}", "password": "wrong-pass-999"})
    assert r.status_code == 401, r.text
    assert "username or email" in r.json()["detail"].lower()
