"""``frontend/openapi.json`` is the committed snapshot the frontend types are generated from."""

import json
from pathlib import Path

from poker_trainer.api.app import create_app, dump_openapi
from poker_trainer.settings import AppSettings

SNAPSHOT = Path(__file__).resolve().parents[3] / "frontend" / "openapi.json"


def test_openapi_snapshot_fresh(tmp_path, llm_off):
    out = tmp_path / "openapi.json"
    dump_openapi([str(out)])
    dumped = json.loads(out.read_text(encoding="utf-8"))
    assert dumped == create_app(AppSettings(_env_file=None, **llm_off)).openapi()
    assert SNAPSHOT.is_file(), "run: npm run gen:openapi (in frontend/)"
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == dumped, "frontend/openapi.json is stale: run npm run gen:openapi"
    assert b"\r\n" not in out.read_bytes()


def test_openapi_has_realisation_fields(llm_off):
    """M9: options and branches carry the equity realisation factor used in their value."""
    schemas = create_app(AppSettings(_env_file=None, **llm_off)).openapi()["components"]["schemas"]
    for name in ("OptionResult", "Branch"):
        assert schemas[name]["properties"]["realisation"]["type"] == "number"
        assert "realisation" in schemas[name]["required"]
