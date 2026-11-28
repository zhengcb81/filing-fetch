"""Filing-fetch client for the isolated company-wiki T3 workspace contract."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any

from ff_company_wiki_connection import (
    WikiConnection,
    command_for,
    connection_cwd,
    connection_environment,
)
from ff_configuration import load_connection_root
from ff_errors import FilingFetchError
from ff_process_transport import run_bounded_json

REQUEST_SCHEMA = "cwp-t3-workspace-request/1"
RESPONSE_SCHEMA = "cwp-t3-workspace/1"
CONTROL_DEADLINE_SECONDS = 30


class WorkspaceUnavailable(RuntimeError):
    """No explicit public workspace endpoint is available."""


class WorkspaceProtocolError(RuntimeError):
    """A workspace reply lacks the owner facts required by the contract."""


class WorkspaceClient:
    def __init__(self, config: Path, *, skill_root: Path):
        try:
            endpoint = load_connection_root(config, skill_root=skill_root)
            if not isinstance(endpoint, WikiConnection):
                raise ValueError("isolated workspace command is not configured")
            self.command = command_for(endpoint, "t3_workspace")
        except (FilingFetchError, OSError, ValueError) as exc:
            raise WorkspaceUnavailable("no configured CWP workspace command") from exc
        self.cwd = connection_cwd(endpoint)
        self.environment = connection_environment(endpoint)

    def _call(self, operation: str, run: str, case: str, **fields: Any) -> dict[str, Any]:
        identity = {"operation": operation, "run_id": run, "case_id": case, **fields}
        request = {"schema_version": REQUEST_SCHEMA, **identity}
        raw, _, _ = run_bounded_json(
            self.command, input_bytes=json.dumps(request, ensure_ascii=True).encode("utf-8"),
            cwd=str(self.cwd), env=self.environment, timeout_seconds=CONTROL_DEADLINE_SECONDS,
        )
        response = json.loads(raw)
        if not isinstance(response, dict) or response.get("schema_version") != RESPONSE_SCHEMA:
            raise WorkspaceProtocolError("invalid workspace response schema")
        if any(response.get(field) != identity[field] for field in ("operation", "run_id", "case_id")):
            raise WorkspaceProtocolError("workspace response identity mismatch")
        return response

    def _close(self, run: str, case: str, workspace_id: str | None) -> None:
        fields = {} if workspace_id is None else {"workspace_id": workspace_id}
        response = self._call("close", run, case, **fields)
        closed_id = response.get("workspace_id")
        if (response.get("status") != "closed" or not isinstance(closed_id, str)
                or not closed_id or (workspace_id is not None and closed_id != workspace_id)):
            raise WorkspaceProtocolError("workspace cleanup was not confirmed")

    @contextmanager
    def open(self, run: str, case: str) -> Iterator[Workspace]:
        workspace_id = None
        # The owner may have created the scope even if its reply was lost.
        # Cleanup is addressed by the original run and case when no ID came back.
        try:
            response = self._call("open", run, case)
            opened_id = response.get("workspace_id")
            if response.get("status") != "opened" or not isinstance(opened_id, str) or not opened_id:
                raise WorkspaceProtocolError("workspace was not opened")
            workspace_id = opened_id
            workspace = Workspace(self, run, case, workspace_id)
            connection = response.get("connection")
            if not isinstance(connection, dict) or set(connection) != {"cwd", "commands"}:
                raise WorkspaceProtocolError("isolated public connection is missing")
            if not isinstance(connection["cwd"], str) or not Path(connection["cwd"]).is_absolute():
                raise WorkspaceProtocolError("isolated connection cwd is invalid")
            selected = WikiConnection(Path(connection["cwd"]), connection["commands"])
            workspace.connection = {"cwd": str(selected.workdir), "commands": dict(selected.commands)}
            yield workspace
        finally:
            self._close(run, case, workspace_id)


class Workspace:
    def __init__(self, client: WorkspaceClient, run: str, case: str, workspace_id: str):
        self._client, self._run, self._case, self._id = client, run, case, workspace_id
        self.connection: dict[str, Any]

    def observe(self, checkpoint: str) -> dict[str, Any]:
        response = self._client._call(
            "observe", self._run, self._case, workspace_id=self._id, checkpoint=checkpoint,
        )
        if (response.get("workspace_id") != self._id or response.get("status") != "observed"
                or response.get("checkpoint") != checkpoint or not isinstance(response.get("facts"), dict)):
            raise WorkspaceProtocolError("workspace observation is invalid")
        return response["facts"]

    def close(self) -> None:
        self._client._close(self._run, self._case, self._id)
