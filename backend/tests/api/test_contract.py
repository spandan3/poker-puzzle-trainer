"""The response contract: OpenAPI carries every shape, and the transport extras work."""

from poker_trainer.api import schemas

ROUTES = {
    ("/api/puzzles", "post", "201"): "PuzzleView",
    ("/api/puzzles/current", "get", "200"): "PuzzleView",
    ("/api/puzzles/{puzzle_id}", "get", "200"): "PuzzleView",
    ("/api/puzzles/{puzzle_id}/attempts", "post", "201"): "AttemptResult",
    ("/api/attempts/{attempt_id}", "get", "200"): "AttemptResult",
    ("/api/attempts/{attempt_id}/explanation", "get", "200"): "Explanation",
    ("/api/history", "get", "200"): "HistoryPage",
    ("/api/settings", "get", "200"): "SettingsView",
    ("/api/settings", "patch", "200"): "SettingsView",
    ("/api/health", "get", "200"): "Health",
    ("/api/play/sessions", "post", "201"): "PlaySessionView",
    ("/api/play/sessions/current", "get", "200"): "PlaySessionView",
    ("/api/play/sessions/{session_id}/end", "post", "200"): "PlaySessionView",
    ("/api/play/sessions/{session_id}/hands", "post", "201"): "PlaySessionView",
    ("/api/play/hands/{hand_id}/actions", "post", "200"): "PlaySessionView",
    ("/api/play/hands/{hand_id}", "get", "200"): "PlayHandView",
    ("/api/play/hands/{hand_id}/analysis", "get", "200"): "HandAnalysis",
    ("/api/play/hands/{hand_id}/analysis/{n}", "post", "200"): "DecisionReview",
    ("/api/play/hands/{hand_id}/analysis/{n}/explanation", "get", "200"): "Explanation",
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
    for path, name in (
        ("/api/play/sessions", "PlaySessionSummary"),
        ("/api/play/sessions/{session_id}/hands", "PlayHandSummary"),
    ):
        listing = spec["paths"][path]["get"]["responses"]["200"]
        assert _ref(listing["content"]["application/json"]["schema"]["items"]) == name


def test_response_models_forbid_extra_fields():
    """So a key added to a view without its model fails loudly instead of being dropped."""
    for name in (
        "PuzzleView",
        "AttemptResult",
        "AttemptSummary",
        "HistoryPage",
        "SettingsView",
        "Explanation",
        "ExplanationSection",
        "OptionResult",
        "RangeStep",
        "Reveal",
        "PlaySessionView",
        "PlayHandView",
        "PlaySessionSummary",
        "PlayHandSummary",
        "PlayOutcome",
        "TableView",
        "TableFrame",
        "DecisionGrade",
        "DecisionReview",
        "PlayReveal",
        "AnalysisSummary",
        "HandAnalysis",
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


def test_play_responses_match_models_exactly(play_client):
    view = play_client.post("/api/play/sessions").json()
    assert set(view) == set(schemas.PlaySessionView.model_fields)
    assert set(view["profile"]) == set(schemas.ProfileInfo.model_fields)
    hand = view["hand"]
    assert set(hand) == set(schemas.PlayHandView.model_fields)
    assert set(hand["table"]) == set(schemas.TableView.model_fields)
    assert set(hand["frames"][0]) == set(schemas.TableFrame.model_fields)
    if hand["options"]:
        assert set(hand["options"][0]) == set(schemas.OptionBrief.model_fields)
    assert set(hand["custom"]) == set(schemas.CustomSizes.model_fields)
    while hand["status"] == "in_progress":  # play it out to see the outcome's keys
        body = {"expected_actions": hand["action_count"], "option": 0}
        hand = play_client.post(f"/api/play/hands/{hand['id']}/actions", json=body).json()["hand"]
    assert set(hand["outcome"]) == set(schemas.PlayOutcome.model_fields)
    sid = hand["session_id"]
    (item,) = play_client.get("/api/play/sessions").json()
    assert set(item) == set(schemas.PlaySessionSummary.model_fields)
    (row,) = play_client.get(f"/api/play/sessions/{sid}/hands").json()
    assert set(row) == set(schemas.PlayHandSummary.model_fields)


def test_analysis_responses_match_models_exactly(play_client):
    view = play_client.post("/api/play/sessions").json()
    hand = view["hand"]
    while hand["status"] == "in_progress" or hand["decision_count"] == 0:
        if hand["status"] == "complete":
            body = {"expected_hands": view["hands_played"]}
            view = play_client.post(f"/api/play/sessions/{view['id']}/hands", json=body).json()
        else:
            body = {"expected_actions": hand["action_count"], "option": 0}
            view = play_client.post(f"/api/play/hands/{hand['id']}/actions", json=body).json()
        hand = view["hand"]
    base = f"/api/play/hands/{hand['id']}/analysis"
    before = play_client.get(base).json()
    assert set(before) == set(schemas.HandAnalysis.model_fields)
    assert set(before["reveal"]) == set(schemas.PlayReveal.model_fields)
    assert set(before["reveal"]["profile"]) == set(schemas.RevealProfile.model_fields)
    for n in range(hand["decision_count"]):
        review = play_client.post(f"{base}/{n}").json()
        assert set(review) == set(schemas.DecisionReview.model_fields)
        assert set(review["grade"]) == set(schemas.DecisionGrade.model_fields)
        assert set(review["view"]) == set(schemas.TableView.model_fields)
        assert set(review["options"][0]) == set(schemas.OptionResult.model_fields)
    after = play_client.get(base).json()
    assert set(after["summary"]) == set(schemas.AnalysisSummary.model_fields)


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
