"""A recording forwarder between the Nutrient SDK and a model provider.

It exists because the SDK surfaces no token usage of its own, so the only way
to learn what a Nutrient-mediated call cost is to observe the call. Deliberately
thin: it does I/O and delegates every judgement to capture.py.

Standard library only — a tool prospects audit before running should not need a
web framework to move bytes between two sockets.
"""

from __future__ import annotations

import http.server
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .capture import read_usage, redact_headers, summarise_request

# Hop-by-hop headers must not be forwarded or echoed; length is recomputed for
# the body actually sent.
_DROP = {
    "host",
    "content-length",
    "transfer-encoding",
    "connection",
    "content-encoding",
}


class RecordingProxy:
    def __init__(
        self,
        upstream_base: str,
        out_dir: Path,
        capture_bodies: bool = True,
        timeout: float = 600.0,
        drop_request_keys: frozenset[str] = frozenset(),
    ):
        self.upstream_base = upstream_base.rstrip("/")
        self.out_dir = Path(out_dir)
        self.capture_bodies = capture_bodies
        # Generous but finite. urllib's default is no timeout at all, which
        # means one unresponsive provider hangs a corpus run forever with no
        # error to read. A local VLM legitimately takes minutes per document,
        # so this is sized for the slowest honest case, not the typical one.
        self.timeout = timeout
        # Top-level request keys removed before forwarding. Empty for every
        # hosted provider; a local runtime needs `logprobs`/`top_logprobs`
        # gone, because LM Studio drops the grammar-forced tokens from
        # `content` when logprobs are requested alongside a json_schema and
        # the SDK always asks for both. The SDK then reports SUCCESS carrying
        # mangled text -- `"totalAmount": 201.45` for a document reading
        # $4,201.45, a corrupted value rather than a visible failure. With the
        # two keys removed the same call returns correct values, source blocks
        # and bounding boxes. Neither key contributes to prompt tokens, so the
        # measurement this tool exists to make is unaffected.
        self.drop_request_keys = frozenset(drop_request_keys)
        self.records: list[dict[str, Any]] = []
        # The most recent outbound request body, IN MEMORY ONLY. The runner needs
        # it to build the no-Nutrient call from the same extracted document text
        # the SDK sent, which is what makes the two halves comparable. It is
        # deliberately NOT part of `records`: records get serialised into
        # reports, and document content must never ride along. It is also not
        # written to disk when capture_bodies is False.
        #
        # "Last" is only meaningful because the runner drives one call at a time
        # per proxy. Do not read it from concurrent callers.
        self.last_request_body: dict[str, Any] | None = None
        # The most recent response body, IN MEMORY ONLY, for the same reasons
        # last_request_body is: scoring needs what the model answered, and
        # --no-capture-bodies means nothing reaches disk. Not part of `records`,
        # because records get serialised into reports and an extracted value can
        # carry document content.
        self.last_response_body: dict[str, Any] | None = None
        self._label = "unlabelled"
        self._server: http.server.ThreadingHTTPServer | None = None
        # ThreadingHTTPServer handles requests in parallel, so claiming a
        # sequence number is a read-modify-write that must not interleave.
        self._lock = threading.Lock()
        self.out_dir.mkdir(parents=True, exist_ok=True)

    def label(self, text: str) -> None:
        self._label = text

    def start(self) -> int:
        """Bind an OS-chosen free port on loopback and serve in a daemon thread."""
        proxy = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 - http.server's required name
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                raw = proxy._drop_keys(raw)
                headers = {
                    k: v for k, v in self.headers.items() if k.lower() not in _DROP
                }
                started = time.perf_counter()
                content_type = "application/json"
                try:
                    req = urllib.request.Request(
                        f"{proxy.upstream_base}{self.path}",
                        data=raw,
                        headers=headers,
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=proxy.timeout) as resp:
                        status, body = resp.status, resp.read()
                        content_type = resp.headers.get("Content-Type", content_type)
                except urllib.error.HTTPError as exc:
                    status, body = exc.code, exc.read()
                    content_type = exc.headers.get("Content-Type", content_type)
                except Exception as exc:  # noqa: BLE001
                    # A timeout or a refused connection must reach the SDK as a
                    # failure it can report, not as a hung socket. 502 with a
                    # readable body is the honest translation.
                    status = 502
                    body = json.dumps(
                        {"error": f"{type(exc).__name__}: {exc}"}
                    ).encode()
                latency_ms = (time.perf_counter() - started) * 1000

                proxy._record(
                    self.path, raw, body, status, latency_ms, dict(self.headers)
                )

                self.send_response(status)
                # Echo the upstream's own content type. Labelling an HTML error
                # page as JSON turns a clear upstream failure into a parse error
                # somewhere else.
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):  # keep the tool's output readable
                pass

        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self._server.server_address[1]

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            # shutdown() stops serving but leaves the socket open. A corpus run
            # starts one proxy per cell, so without this the file descriptors
            # accumulate for the length of the run.
            self._server.server_close()
            self._server = None

    def _drop_keys(self, raw: bytes) -> bytes:
        """The outbound body with `drop_request_keys` removed.

        Rewrites rather than rejects, and only at the top level: a key named
        `logprobs` nested inside the schema is part of what the caller asked
        the model for, not a request parameter. A body that is not JSON is
        passed through untouched -- guessing at a payload we cannot parse
        would corrupt it.
        """
        if not self.drop_request_keys:
            return raw
        try:
            body = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return raw
        if not isinstance(body, dict) or not (self.drop_request_keys & body.keys()):
            return raw
        return json.dumps(
            {k: v for k, v in body.items() if k not in self.drop_request_keys}
        ).encode()

    def _record(self, path, raw, body, status, latency_ms, headers) -> None:
        def decode(data: bytes) -> Any:
            try:
                return json.loads(data)
            except (ValueError, UnicodeDecodeError):
                return {}

        request_body, response_body = decode(raw), decode(body)
        record = {
            "label": self._label,
            "path": path,
            "requestSummary": summarise_request(request_body),
            "usage": read_usage(response_body),
            "status": status,
            "latencyMs": round(latency_ms, 1),
        }
        # Claim the sequence number and publish the record as one step. Reading
        # len(self.records) and appending are separate operations, and the gap
        # between them here spans two function calls — wide enough that parallel
        # handlers really do claim the same number and overwrite each other's
        # body file, losing records with no error at all.
        with self._lock:
            seq = len(self.records) + 1
            record["seq"] = seq
            self.records.append(record)
            self.last_request_body = request_body
            self.last_response_body = response_body
        if self.capture_bodies:
            (self.out_dir / f"{seq}.json").write_text(
                json.dumps(
                    {
                        "request": request_body,
                        "response": response_body,
                        "headers": redact_headers(headers),
                    },
                    indent=2,
                )
            )
