"""Wiring smoke tests: app.py mounts /static and includes the web router,
while the JSON ingest API and /healthz remain intact."""

from fastapi.testclient import TestClient


def _client(db_session):
    from tokensurf_server.app import create_app
    from tokensurf_server.db import get_session

    def _override():
        yield db_session

    app = create_app()
    app.dependency_overrides[get_session] = _override
    return app


def test_login_page_served(db_session):
    app = _client(db_session)
    with TestClient(app) as client:
        resp = client.get("/login")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]
    app.dependency_overrides.clear()


def test_static_css_served(db_session):
    app = _client(db_session)
    with TestClient(app) as client:
        resp = client.get("/static/app.css")
        assert resp.status_code == 200
    app.dependency_overrides.clear()


def test_ingest_api_untouched(db_session):
    app = _client(db_session)
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/runs",
            json={"report": {"results": []}},
            headers={"Authorization": "Bearer tsk_definitely_wrong"},
        )
        assert resp.status_code == 401  # API key auth unchanged
        assert client.get("/healthz").status_code == 200
    app.dependency_overrides.clear()
