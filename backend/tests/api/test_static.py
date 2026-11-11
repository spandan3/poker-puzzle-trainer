import pytest
from fastapi.testclient import TestClient

from poker_trainer.api.app import _frontend_route, create_app
from poker_trainer.settings import AppSettings


def _client(tmp_path, dist):
    settings = AppSettings(
        _env_file=None,
        database_url=f"sqlite:///{(tmp_path / 's.db').as_posix()}",
        frontend_dist=dist,
    )
    return TestClient(create_app(settings))


@pytest.fixture
def built(tmp_path):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
    (dist / "favicon.ico").write_text("ICON", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("TOP-SECRET", encoding="utf-8")
    return tmp_path, dist


def test_static_serves_index_and_assets(built):
    tmp_path, dist = built
    with _client(tmp_path, dist) as c:
        for path in ("/", "/progress", "/puzzle/3"):
            r = c.get(path)
            assert r.status_code == 200 and "INDEX" in r.text, path
        assert c.get("/assets/app.js").text == "console.log('app')"
        assert c.get("/favicon.ico").text == "ICON"
        r = c.get("/api/nope")
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/api/puzzles/current").status_code == 404  # not index.html


def test_static_no_traversal(built):
    tmp_path, dist = built
    (tmp_path / "pyproject.toml").write_text("TOP-SECRET", encoding="utf-8")
    with _client(tmp_path, dist) as c:
        for path in (
            "/..%2f..%2fpyproject.toml",
            "/..%2fsecret.txt",
            "/assets/../../secret.txt",
            "/assets/..%2f..%2fsecret.txt",
            "/%2e%2e/secret.txt",
            "/%2e%2e%2fsecret.txt",
            "/assets/%2e%2e/%2e%2e/secret.txt",
            "/..\\secret.txt",
        ):
            r = c.get(path)
            assert "TOP-SECRET" not in r.text, path


def test_static_absent(tmp_path):
    with _client(tmp_path, tmp_path / "missing") as c:
        r = c.get("/")
        assert r.status_code == 404 and r.json() == {"detail": "frontend not built"}
        assert c.get("/progress").status_code == 404
        assert c.get("/api/health").status_code == 200


def test_static_dir_without_index(tmp_path):
    (tmp_path / "dist").mkdir()
    with _client(tmp_path, tmp_path / "dist") as c:
        assert c.get("/").json() == {"detail": "frontend not built"}


def test_static_head_and_odd_paths(built):
    tmp_path, dist = built
    with _client(tmp_path, dist) as c:
        r = c.head("/assets/app.js")
        assert r.status_code == 200 and r.content == b""
        assert r.headers["content-type"].startswith("text/javascript")
        assert c.head("/progress").status_code == 200
        # a real server passes "//api/nope" through (TestClient would read "api" as a host)
        assert _frontend_route(dist)("/api/nope").status_code == 404
        for path in ("/" + "a" * 5000, "/a/" * 3000, "/%00"):  # OSError / ValueError -> index
            r = c.get(path)
            assert r.status_code == 200 and "INDEX" in r.text
