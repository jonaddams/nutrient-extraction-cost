import json
import threading
import urllib.request
from pathlib import Path

from costlab.proxy import RecordingProxy


class _Upstream:
    """A stand-in provider, so the test spends nothing and needs no network."""

    def __init__(self, status: int = 200, body: dict | None = None, delay: float = 0.0):
        self.status = status
        self.body = body
        self.delay = delay

    def __enter__(self):
        import http.server
        import time

        payload = json.dumps(
            self.body
            if self.body is not None
            else {
                "choices": [{"finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1234, "completion_tokens": 56},
            }
        ).encode()
        status, delay = self.status, self.delay

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                if delay:
                    time.sleep(delay)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.srv.server_address[1]}"

    def __exit__(self, *a):
        self.srv.shutdown()


def _post(port: int, path: str, body: dict | bytes, headers: dict | None = None):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    return urllib.request.urlopen(req).read()


def test_proxy_records_usage_and_never_writes_a_credential(tmp_path: Path):
    with _Upstream() as upstream:
        proxy = RecordingProxy(upstream_base=upstream, out_dir=tmp_path)
        port = proxy.start()
        proxy.label("doc-a")
        _post(
            port,
            "/v1/chat/completions",
            {"model": "m", "messages": [{"role": "user", "content": "hi"}]},
            {"Authorization": "Bearer sk-secret"},
        )
        proxy.stop()

    assert len(proxy.records) == 1
    rec = proxy.records[0]
    assert rec["label"] == "doc-a"
    assert rec["path"] == "/v1/chat/completions"
    assert rec["usage"] == {
        "inputTokens": 1234,
        "outputTokens": 56,
        "cachedInputTokens": 0,
    }

    written = "".join(p.read_text() for p in tmp_path.rglob("*.json"))
    assert "sk-secret" not in written
    assert "<redacted>" in written


def test_proxy_forwards_the_path_unchanged(tmp_path: Path):
    # A mangled forward path breaks every measurement, and it fails as an
    # upstream 404 rather than anything obvious. Pin it.
    with _Upstream() as upstream:
        proxy = RecordingProxy(upstream_base=upstream, out_dir=tmp_path)
        port = proxy.start()
        _post(port, "/v1/messages?beta=true", b"{}")
        proxy.stop()
        seen = [r["path"] for r in proxy.records]

    assert seen == ["/v1/messages?beta=true"]


def test_capture_bodies_false_writes_no_document_content(tmp_path: Path):
    with _Upstream() as upstream:
        proxy = RecordingProxy(
            upstream_base=upstream, out_dir=tmp_path, capture_bodies=False
        )
        port = proxy.start()
        _post(
            port,
            "/v1/chat/completions",
            {"messages": [{"role": "user", "content": "SECRET DOCUMENT TEXT"}]},
        )
        proxy.stop()

    written = "".join(p.read_text() for p in tmp_path.rglob("*") if p.is_file())
    assert "SECRET DOCUMENT TEXT" not in written
    assert proxy.records[0]["usage"] is not None  # summaries still captured


# --- Beyond the plan. Both come from Task 1 measurements.


def test_a_failed_call_is_recorded_with_its_status_and_no_usage(tmp_path: Path):
    """The SDK retries a failing call four times, so one extraction can produce
    four records. Task 5 must be able to tell a retry storm from four real
    calls, and `status` plus a null `usage` is the only signal it gets.

    Verified live 2026-08-14: a 502 upstream produced exactly four proxy hits
    for a single extract_structured() call.
    """
    with _Upstream(status=502, body={"error": "upstream exploded"}) as upstream:
        proxy = RecordingProxy(upstream_base=upstream, out_dir=tmp_path)
        port = proxy.start()
        for _ in range(4):
            try:
                _post(port, "/v1/chat/completions", {"model": "m"})
            except urllib.error.HTTPError:
                pass  # the proxy must relay the failure, not swallow it
        proxy.stop()

    assert len(proxy.records) == 4
    assert [r["status"] for r in proxy.records] == [502, 502, 502, 502]
    assert all(r["usage"] is None for r in proxy.records)
    # Sequence numbers must stay unique so a body file is never overwritten.
    assert sorted(r["seq"] for r in proxy.records) == [1, 2, 3, 4]


def test_concurrent_calls_get_unique_sequence_numbers(tmp_path: Path):
    """ThreadingHTTPServer serves in parallel, so `len(self.records) + 1` is a
    race: two threads read the same length, claim the same seq, and the second
    body file silently overwrites the first. A corpus run with any concurrency
    would lose records with no error.
    """
    with _Upstream(delay=0.05) as upstream:
        proxy = RecordingProxy(upstream_base=upstream, out_dir=tmp_path)
        port = proxy.start()
        threads = [
            threading.Thread(
                target=_post, args=(port, "/v1/chat/completions", {"model": "m"})
            )
            for _ in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        proxy.stop()

    seqs = [r["seq"] for r in proxy.records]
    assert len(proxy.records) == 8
    assert sorted(seqs) == list(range(1, 9)), f"duplicate seq: {sorted(seqs)}"
    assert len(list(tmp_path.glob("*.json"))) == 8


def test_proxy_keeps_the_last_response_body_in_memory(tmp_path: Path):
    """Scoring needs what the model answered, and with --no-capture-bodies
    nothing is written to disk. Like last_request_body this is memory-only and
    deliberately NOT part of `records`, which get serialised into reports."""
    with _Upstream() as upstream:
        proxy = RecordingProxy(
            upstream_base=upstream, out_dir=tmp_path, capture_bodies=False
        )
        port = proxy.start()
        _post(port, "/v1/chat/completions", {"model": "m"})
        proxy.stop()

    assert proxy.last_response_body is not None
    assert proxy.last_response_body["usage"]["prompt_tokens"] == 1234
    assert "responseBody" not in proxy.records[0]
