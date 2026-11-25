"""FF-owned FMP HTTP simulation loaded by the real ET worker during matrix tests."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
from threading import Event

import requests


FMP_URL = "https://financialmodelingprep.com/stable/earning-call-transcript"


def build_session(spec: dict, context: dict) -> MatrixSession:
    if spec["scenario"] == "worker_loss":
        raise SystemExit(7)
    session = MatrixSession(spec)
    request = json.loads((Path(context["workdir"]) / "request.json").read_text(encoding="utf-8"))
    session.record(
        "envelope", budget=request["budget"],
        translator_loaded="translator" in sys.modules, scraper_loaded="scraper" in sys.modules,
    )
    return session


class MatrixSession:
    def __init__(self, spec: dict):
        self.headers: dict[str, str] = {}
        self.scenario = spec["scenario"]
        self.calls_file = Path(spec["calls_file"]) if spec["calls_file"] else None
        self.payload = base64.b64decode(spec["payload_b64"], validate=True)

    def record(self, operation: str, **fields: object) -> None:
        if self.calls_file is not None:
            self.calls_file.parent.mkdir(parents=True, exist_ok=True)
            with self.calls_file.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"op": operation, **fields}, ensure_ascii=False) + "\n")

    def get(self, url: str, **kwargs: object) -> MatrixResponse:
        params = kwargs.get("params")
        observed = ({key: ("***" if key == "apikey" else value) for key, value in params.items()}
                    if isinstance(params, dict) else None)
        self.record("get", url=url, timeout=kwargs.get("timeout"), params=observed)
        if url != FMP_URL:
            raise AssertionError("unexpected URL for the offline FMP fixture")
        if self.scenario == "stall":
            Event().wait()
        if self.scenario == "request_failure":
            raise requests.RequestException("synthetic-after-GET-failure")
        code = {"entitlement_402": 402, "http_429": 429, "http_500": 500}.get(self.scenario, 200)
        mime = "text/html" if self.scenario == "wrong_mime" else "application/json"
        return MatrixResponse(self, code, mime, self.payload if code == 200 else b"")

    def close(self) -> None:
        pass


class MatrixResponse:
    def __init__(self, session: MatrixSession, status: int, mime: str, payload: bytes):
        self.url = FMP_URL
        self.status_code = status
        self.headers = {"Content-Type": mime}
        self._session = session
        self._payload = payload

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self._payload), chunk_size):
            yield self._payload[offset:offset + chunk_size]

    def close(self) -> None:
        self._session.record("close", url=self.url)
