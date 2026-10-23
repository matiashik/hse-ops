import logging

import app_final
import pytest
from app_final import app
from fastapi.testclient import TestClient

client = TestClient(app)
KEY = "test-admin-key"
AUTH = {"X-Admin-Key": KEY}


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    app_final.records.clear()
    monkeypatch.setattr(app_final, "ADMIN_KEY", KEY)


def create(name="example.com", ip="192.0.2.10", headers=AUTH):
    return client.post("/records", json={"name": name, "ip": ip}, headers=headers)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_version():
    response = client.get("/version")
    assert response.status_code == 200
    assert response.json() == {"version": app_final.APP_VERSION}


def test_root():
    assert client.get("/").json()["message"] == "DNS-сервис работает"


def test_create_and_query_record():
    created = create()
    assert created.status_code == 201
    assert created.json() == {"name": "example.com", "type": "A", "ip": "192.0.2.10"}

    response = client.get("/records/example.com")
    assert response.status_code == 200
    assert response.json()["ip"] == "192.0.2.10"


def test_domain_is_case_insensitive():
    create(name="WWW.Example.COM.")
    response = client.get("/records/www.example.com")
    assert response.status_code == 200
    assert response.json()["name"] == "www.example.com"


def test_list_records():
    create(name="b.example.com")
    create(name="a.example.com", ip="198.51.100.1")
    response = client.get("/records")
    assert response.status_code == 200
    assert [r["name"] for r in response.json()] == ["a.example.com", "b.example.com"]


def test_duplicate_returns_409():
    assert create().status_code == 201
    assert create(ip="192.0.2.20").status_code == 409


def test_missing_record_returns_404():
    assert client.get("/records/missing.example.com").status_code == 404
    assert (
        client.delete("/records/missing.example.com", headers=AUTH).status_code == 404
    )


@pytest.mark.parametrize(
    "ip", ["256.1.1.1", "1.2.3", "1.2.3.4.5", "abc", "01.2.3.4", "::1", ""]
)
def test_invalid_ip_returns_422(ip):
    assert create(ip=ip).status_code == 422


@pytest.mark.parametrize(
    "name",
    [
        "localhost",
        "-bad.com",
        "bad-.com",
        "a..com",
        "bad_name.com",
        "1.2.3.4",
        "a" * 64 + ".com",
        "",
    ],
)
def test_invalid_domain_returns_422(name):
    assert create(name=name).status_code == 422


def test_invalid_domain_in_path_returns_422():
    assert client.get("/records/bad_name.com").status_code == 422


def test_delete_record():
    create()
    assert client.delete("/records/example.com", headers=AUTH).status_code == 204
    assert client.get("/records/example.com").status_code == 404


def test_patch_updates_ip():
    create()
    response = client.patch(
        "/records/example.com", json={"ip": "198.51.100.7"}, headers=AUTH
    )
    assert response.status_code == 200
    assert response.json() == {
        "name": "example.com",
        "type": "A",
        "ip": "198.51.100.7",
    }
    assert client.get("/records/example.com").json()["ip"] == "198.51.100.7"


def test_patch_missing_returns_404():
    assert (
        client.patch(
            "/records/missing.example.com",
            json={"ip": "198.51.100.7"},
            headers=AUTH,
        ).status_code
        == 404
    )


def test_patch_invalid_ip_returns_422():
    create()
    assert (
        client.patch(
            "/records/example.com", json={"ip": "999.1.1.1"}, headers=AUTH
        ).status_code
        == 422
    )


def test_patch_invalid_name_returns_422():
    assert (
        client.patch(
            "/records/bad_name.com", json={"ip": "198.51.100.7"}, headers=AUTH
        ).status_code
        == 422
    )


def test_patch_requires_key():
    create()
    assert (
        client.patch("/records/example.com", json={"ip": "198.51.100.7"}).status_code
        == 401
    )
    assert (
        client.patch(
            "/records/example.com",
            json={"ip": "198.51.100.7"},
            headers={"X-Admin-Key": "wrong"},
        ).status_code
        == 403
    )
    assert client.get("/records/example.com").json()["ip"] == "192.0.2.10"


def test_create_without_key_returns_401():
    assert create(headers=None).status_code == 401
    assert app_final.records == {}


def test_create_with_wrong_key_returns_403():
    assert create(headers={"X-Admin-Key": "wrong"}).status_code == 403


def test_delete_requires_key():
    create()
    assert client.delete("/records/example.com").status_code == 401
    response = client.delete("/records/example.com", headers={"X-Admin-Key": "wrong"})
    assert response.status_code == 403
    assert client.get("/records/example.com").status_code == 200


def test_writes_locked_without_admin_key(monkeypatch):
    monkeypatch.setattr(app_final, "ADMIN_KEY", "")
    assert create(headers={"X-Admin-Key": "anything"}).status_code == 403


def test_key_is_never_logged(caplog):
    with caplog.at_level(logging.INFO, logger="dns_service"):
        create(headers={"X-Admin-Key": "secret-guess"})
        create()
    assert "secret-guess" not in caplog.text
    assert KEY not in caplog.text
    assert "Отказ" in caplog.text
