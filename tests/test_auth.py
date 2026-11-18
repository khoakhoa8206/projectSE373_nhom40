"""Đăng ký / đăng nhập thật: mật khẩu băm, phiên theo cookie, người dùng hư cấu không vào được từ PWA."""

import pytest
from fastapi.testclient import TestClient

from agent.db import repo
from agent.src.api.server import app

ACCOUNT = {"display_name": "Lan", "email": "Lan@Example.com", "password": "matkhau-dai-8", "preferred_lang": "vi"}


@pytest.fixture
def client(db):
    return TestClient(app)


def test_register_logs_in_and_never_stores_plain_password(client):
    r = client.post("/api/auth/register", json=ACCOUNT)
    assert r.status_code == 201
    user = r.json()
    assert user["display_name"] == "Lan" and client.get("/api/auth/me").json() == user
    stored = repo.query("SELECT email, password_hash FROM credentials")[0]
    assert stored["email"] == "lan@example.com"
    assert ACCOUNT["password"] not in stored["password_hash"] and stored["password_hash"].startswith("scrypt$")


def test_login_logout_and_wrong_password(client):
    client.post("/api/auth/register", json=ACCOUNT)
    client.cookies.clear()  # = đăng xuất: mất cookie phiên
    assert client.get("/api/auth/me").json() is None
    assert client.post("/api/trips", json={}).status_code == 401

    wrong = client.post("/api/auth/login", json={"email": "lan@example.com", "password": "sai-mat-khau"})
    unknown = client.post("/api/auth/login", json={"email": "ai@example.com", "password": "sai-mat-khau"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()  # không lộ email nào đã đăng ký

    ok = client.post("/api/auth/login", json={"email": " LAN@example.com ", "password": ACCOUNT["password"]})
    assert ok.status_code == 200 and client.get("/api/auth/me").json()["user_id"] == ok.json()["user_id"]


def test_register_rejects_duplicate_email_and_short_password(client):
    assert client.post("/api/auth/register", json=ACCOUNT).status_code == 201
    assert client.post("/api/auth/register", json=ACCOUNT | {"email": "lan@example.com"}).status_code == 409
    assert client.post("/api/auth/register", json=ACCOUNT | {"email": "b@example.com", "password": "ngan"}).status_code == 422
    assert client.post("/api/auth/register", json=ACCOUNT | {"email": "khong-phai-email"}).status_code == 422


def test_fictional_session_closed_outside_tests(client, monkeypatch):
    assert client.post("/api/session", json={"user_id": "u-ha"}).status_code == 200  # cookie cũ của u-ha
    monkeypatch.setenv("ALLOW_FICTIONAL_LOGIN", "0")
    assert client.get("/api/auth/me").json() is None  # cookie cũ không còn dùng được
    assert client.post("/api/trips", json={}).status_code == 401
    assert client.post("/api/session", json={"user_id": "u-ha"}).status_code == 404
