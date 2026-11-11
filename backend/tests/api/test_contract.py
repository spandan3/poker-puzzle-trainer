"""The response contract: OpenAPI carries every shape, and the transport extras work."""

from poker_trainer.api import schemas

ROUTES = {
    ("/api/puzzles", "post", "201"): "PuzzleView",
    ("/api/puzzles/current", "get", "200"): "PuzzleView",
    ("/api/puzzles/{puzzle_id}", "get", "200"): "PuzzleView",
    ("/api/puzzles/{puzzle_id}/attempts", "post", "201"): "AttemptResult",
    ("/api/attempts/{attempt_id}", "get", "200"): "AttemptResult",
    ("/api/history", "get", "200"): "HistoryPage",
    ("/api/settings", "get", "200"): "SettingsView",
    ("/api/settings", "patch", "200"): "SettingsView",
    ("/api/health", "get", "200"): "Health",
}


def _ref(schema):
    return schema.get("$ref", "").rsplit("/", 1)[-1]


def test_openapi_has_response_schemas(client):
    spec = client.get("/openapi.json").json()
    for (path, method, status), name in ROUTES.items():
        content = spec["paths"][path][method]["responses"][status]["content"]
        assert _ref(content["application/json"]["schema"]) == name, (path, method)
        assert name in spec["components"]["schemas"]
    attempts = spec["paths"]["/api/puzzles/{puzzle_id}/attempts"]["get"]["responses"]["200"]
    items = attempts["content"]["application/json"]["schema"]["items"]
    assert _ref(items) == "AttemptSummary"


def test_response_models_forbid_extra_fields():
    """So a key added to a view without its model fails loudly instead of being dropped."""
    for name in (
        "PuzzleView",
        "AttemptResult",
        "AttemptSummary",
        "HistoryPage",
        "SettingsView",
        "OptionResult",
        "RangeStep",
        "Reveal",
    ):
        assert getattr(schemas, name).model_config.get("extra") == "forbid", name


def test_responses_match_models_exactly(client):
    """Every key the views build survives the response model (nothing silently dropped)."""
    view = client.post("/api/puzzles", json={"street": "flop"}).json()
    assert set(view) == set(schemas.PuzzleView.model_fields)
    res = client.post(
        f"/api/puzzles/{view['id']}/attempts", json={"option": 1, "equity_guess": 0.4}
    ).json()
    assert set(res) == set(schemas.AttemptResult.model_fields)
    assert set(res["grade"]) == set(schemas.GradeView.model_fields)
    assert set(res["options"][0]) == set(schemas.OptionResult.model_fields)
    assert set(res["reveal"]["profile"]) == set(schemas.RevealProfile.model_fields)
    item = client.get("/api/history").json()["items"][0]
    assert set(item) == set(schemas.AttemptSummary.model_fields)
    assert set(client.get("/api/settings").json()) == set(schemas.SettingsView.model_fields)


def test_large_responses_gzipped(client):
    view = client.post("/api/puzzles", json={"street": "flop"}).json()
    r = client.post(
        f"/api/puzzles/{view['id']}/attempts",
        json={"option": 1, "equity_guess": 0.4},
        headers={"accept-encoding": "gzip"},
    )
    assert r.status_code == 201
    assert r.headers["content-encoding"] == "gzip"
    assert int(r.headers.get("content-length", 0)) < len(r.content) / 4
    # httpx decodes it transparently; the body is still the JSON result
    assert r.json()["attempt"]["puzzle_id"] == view["id"]


def test_health_head(client):
    assert client.head("/api/health").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"
