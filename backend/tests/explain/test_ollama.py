"""The Ollama client against a fake server (``http.server`` on 127.0.0.1, port 0), the prompt
and the reply parsing. No test needs a real Ollama."""

from __future__ import annotations

import json
import socket
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import URLError

import pytest
from explain_cases import facts, puzzle, result

from poker_trainer.explain import guardrail, ollama
from poker_trainer.explain.template import render

# (status, body bytes, delay in seconds); None closes the connection without a reply
Reply = tuple[int, bytes, float] | None
Route = Callable[[dict[str, Any] | None], Reply]


class FakeOllama:
    """A fake Ollama: ``routes[(method, path)]`` answers; ``requests`` records the JSON bodies."""

    def __init__(self) -> None:
        self.routes: dict[tuple[str, str], Route] = {}
        self.requests: list[tuple[str, str, Any]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _serve(self, method: str) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                body = json.loads(raw) if raw else None
                fake.requests.append((method, self.path, body))
                route = fake.routes.get((method, self.path))
                reply = route(body) if route else (404, b'{"error":"not found"}', 0.0)
                if reply is None:
                    self.close_connection = True
                    return
                status, data, delay = reply
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._serve("GET")

            def do_POST(self) -> None:
                self._serve("POST")

            def log_message(self, *_args: Any) -> None:
                pass

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, *_args: Any) -> None:  # a client that gave up: not our business
                pass

        self.server = Server(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
        )

    def chat(self, content: str, status: int = 200, delay: float = 0.0) -> None:
        data = json.dumps({"message": {"role": "assistant", "content": content}, "done": True})
        self.routes[("POST", "/api/chat")] = lambda _b: (status, data.encode(), delay)

    def tags(self, *names: str) -> None:
        data = json.dumps({"models": [{"name": n, "model": n} for n in names]}).encode()
        self.routes[("GET", "/api/tags")] = lambda _b: (200, data, 0.0)


@pytest.fixture
def fake() -> Iterator[FakeOllama]:
    f = FakeOllama()
    f.thread.start()
    try:
        yield f
    finally:
        f.server.shutdown()
        f.server.server_close()


def _closed_port_url() -> str:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return f"http://127.0.0.1:{port}"


GOOD = json.dumps({"headline": "Bet was best.", "hand": "You bet.", "verdict": "It was best."})


def _generate(fake: FakeOllama, timeout: float = 5.0) -> str:
    return ollama.generate(fake.url, "llama3.2:3b", "SYSTEM", "PROMPT", ollama.SCHEMA, timeout)


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------


def test_generate_success_and_request_body(fake):
    fake.chat(GOOD)
    assert _generate(fake) == GOOD
    [(method, path, body)] = fake.requests
    assert (method, path) == ("POST", "/api/chat")
    assert body["model"] == "llama3.2:3b"
    assert body["stream"] is False
    assert body["format"] == ollama.SCHEMA
    assert body["format"]["required"] == ["headline", "hand", "verdict"]
    assert body["options"] == {"temperature": 0.2}
    assert body["keep_alive"] == "10m"
    assert body["messages"] == [
        {"role": "system", "content": "SYSTEM"},
        {"role": "user", "content": "PROMPT"},
    ]


def test_generate_trailing_slash_in_url(fake):
    fake.chat(GOOD)
    assert ollama.generate(fake.url + "/", "m", "s", "p", ollama.SCHEMA, 5.0) == GOOD
    assert fake.requests[0][1] == "/api/chat"


def test_model_not_found_is_unavailable(fake):
    fake.routes[("POST", "/api/chat")] = lambda _b: (404, b'{"error":"model not found"}', 0.0)
    with pytest.raises(ollama.LlmUnavailable):
        _generate(fake)


def test_server_error_is_error(fake):
    fake.chat("boom", status=500)
    with pytest.raises(ollama.LlmError) as e:
        _generate(fake)
    assert e.value.reason == "error"


def test_bad_request_mentions_the_version(fake):
    fake.chat("", status=400)
    with pytest.raises(ollama.LlmError, match="0.5"):
        _generate(fake)


def test_slow_reply_is_timeout(fake):
    fake.chat(GOOD, delay=1.0)
    with pytest.raises(ollama.LlmTimeout) as e:
        _generate(fake, timeout=0.2)
    assert e.value.reason == "timeout"


def test_connection_refused_is_unavailable():
    with pytest.raises(ollama.LlmUnavailable) as e:
        ollama.generate(_closed_port_url(), "m", "s", "p", ollama.SCHEMA, 2.0)
    assert e.value.reason == "unavailable"


def test_dropped_connection_is_error(fake):
    fake.routes[("POST", "/api/chat")] = lambda _b: None  # RemoteDisconnected
    with pytest.raises(ollama.LlmError):
        _generate(fake)


def test_bad_json_body_is_error(fake):
    fake.routes[("POST", "/api/chat")] = lambda _b: (200, b"<html>not json</html>", 0.0)
    with pytest.raises(ollama.LlmError):
        _generate(fake)
    fake.routes[("POST", "/api/chat")] = lambda _b: (200, b'{"message": {}}', 0.0)
    with pytest.raises(ollama.LlmError):
        _generate(fake)


class _Opener:
    def __init__(self, exc: BaseException) -> None:
        self.exc = exc

    def open(self, *_a: Any, **_k: Any) -> Any:
        raise self.exc


@pytest.mark.parametrize(
    ("exc", "kind"),
    [
        (URLError(TimeoutError("timed out")), ollama.LlmTimeout),  # on connect
        (TimeoutError("timed out"), ollama.LlmTimeout),  # on read
        (URLError(ConnectionRefusedError()), ollama.LlmUnavailable),
        (URLError(socket.gaierror("no such host")), ollama.LlmUnavailable),
        (ConnectionResetError(), ollama.LlmError),
        (URLError(ConnectionResetError()), ollama.LlmError),
        (OSError("other"), ollama.LlmError),
    ],
)
def test_exception_mapping(monkeypatch, exc, kind):
    monkeypatch.setattr(ollama, "_opener", lambda: _Opener(exc))
    with pytest.raises(kind):
        ollama.generate("http://127.0.0.1:1", "m", "s", "p", ollama.SCHEMA, 1.0)


def test_opener_ignores_proxies(monkeypatch, fake):
    """A system or environment proxy must never see the local model's traffic: with a dead
    proxy configured, the local server still answers."""
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.setenv(name, _closed_port_url())
    fake.chat(GOOD)
    assert _generate(fake) == GOOD
    fake.tags("llama3.2:3b")
    assert ollama.probe(fake.url, "llama3.2:3b") == ("ready", None)


# ---------------------------------------------------------------------------
# probe
# ---------------------------------------------------------------------------


def test_probe_ready(fake):
    fake.tags("llama3.2:3b", "mistral:latest")
    assert ollama.probe(fake.url, "llama3.2:3b") == ("ready", None)
    assert ollama.probe(fake.url, "mistral") == ("ready", None)  # no tag: ":latest"
    assert fake.requests[0][:2] == ("GET", "/api/tags")


def test_probe_model_missing(fake):
    fake.tags("mistral:latest")
    status, detail = ollama.probe(fake.url, "llama3.2:3b")
    assert status == "unavailable"
    assert detail == (
        "Ollama is running but the model llama3.2:3b isn't pulled: run `ollama pull llama3.2:3b`."
    )
    assert ollama.probe(fake.url, "llama3.2")[0] == "unavailable"  # ":latest" isn't ":3b"


def test_probe_server_down():
    url = _closed_port_url()
    assert ollama.probe(url, "llama3.2:3b") == ("unavailable", f"Ollama isn't answering at {url}.")


def test_probe_not_ollama(fake):
    fake.routes[("GET", "/api/tags")] = lambda _b: (200, b"<html></html>", 0.0)
    status, detail = ollama.probe(fake.url, "llama3.2:3b")
    assert status == "unavailable" and "Ollama 0.5" in detail
    fake.routes[("GET", "/api/tags")] = lambda _b: (500, b"{}", 0.0)
    status, detail = ollama.probe(fake.url, "llama3.2:3b")
    assert status == "unavailable" and fake.url in detail


def test_probe_slow_server(fake):
    fake.routes[("GET", "/api/tags")] = lambda _b: (200, b'{"models": []}', 1.0)
    status, detail = ollama.probe(fake.url, "m", timeout=0.2)
    assert status == "unavailable" and detail == f"Ollama isn't answering at {fake.url}."


# ---------------------------------------------------------------------------
# prompt and reply
# ---------------------------------------------------------------------------


def test_instructions_contain_no_number():
    """The guardrail checks against the facts only, so the instructions must add no number
    (not even a number word) a model could copy."""
    assert guardrail.numbers(ollama.INSTRUCTIONS) == set()


def _case():
    p = puzzle(1, "river")
    res = result(p, option=0)
    res.pop("explanation")
    f = facts(res, p)
    return render(f), f


def test_user_message_holds_facts_and_template():
    template, f = _case()
    msg = ollama.user_message(template, f)
    for line in f.as_lines():
        assert line in msg
    assert template["headline"] in msg
    for s in template["sections"]:
        if s["id"] in ("hand", "verdict"):
            for para in s["paragraphs"]:
                assert para in msg
    assert ollama.template_fields(msg) == ollama.fields_of(template)


def test_parse_reply():
    assert ollama.parse_reply(GOOD) == {
        "headline": "Bet was best.",
        "hand": "You bet.",
        "verdict": "It was best.",
    }
    bad = [
        "not json",
        "[]",
        json.dumps({"headline": "x", "hand": "y"}),
        json.dumps({"headline": "x", "hand": "y", "verdict": "  "}),
        json.dumps({"headline": "x", "hand": "y", "verdict": 3}),
        json.dumps({"headline": "x", "hand": "y" * 1201, "verdict": "z"}),
    ]
    for content in bad:
        with pytest.raises(ollama.LlmInvalid) as e:
            ollama.parse_reply(content)
        assert e.value.reason == "invalid"
    ok = json.dumps({"headline": " x ", "hand": "y" * 1200, "verdict": "z", "extra": 1})
    assert ollama.parse_reply(ok)["hand"] == "y" * 1200
