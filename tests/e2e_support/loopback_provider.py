"""Test-only provider adapter. Transport is ordinary HTTP to the owning test's loopback fixture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def main() -> int:
    origin, operation, *arguments = sys.argv[1:]
    endpoint = urlsplit(origin)
    if endpoint.scheme != "http" or endpoint.hostname != "127.0.0.1" or endpoint.port is None:
        raise ValueError("test adapter requires an explicit loopback provider")
    request = json.load(sys.stdin)
    identity = {"name": "ff-loopback-fixture", "version": "1.0.0"}
    try:
        with urlopen(Request(
            f"{origin}/{operation}", data=json.dumps(request).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        ), timeout=5) as response:
            body = response.read()
    except HTTPError:
        sys.stderr.write(json.dumps({"schema_version": "1.0", "error_code": "provider_unavailable",
                                     "retryable": True, "error": "offline provider failed",
                                     "adapter": identity}) + "\n")
        return 1

    result = {
        "schema_version": "1.0", "status": "ok", "adapter": identity,
        "acquisition_usage": {"schema_version": "1.0", "response_bytes": len(body), "cost_usd": "0"},
    }
    if operation == "discover":
        result["candidates"] = json.loads(body)
    elif operation == "fetch":
        staged = Path(arguments[arguments.index("--staging-dir") + 1]) / "annual.pdf"
        staged.write_bytes(body)
        result["receipt"] = {
            "candidate_id": request["candidate_id"], "provider": request["provider"],
            "provider_document_id": request["provider_document_id"], "source_url": request["source_url"],
            "staged_path": str(staged), "content_sha256": hashlib.sha256(body).hexdigest(),
            "byte_size": len(body), "mime_type": "application/pdf",
            "retrieved_at": "2026-05-01T00:00:00Z", "http_status": 200,
            "adapter_name": identity["name"], "adapter_version": identity["version"],
            "etag": None, "last_modified": None,
        }
    else:
        raise ValueError("unknown fixture operation")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
