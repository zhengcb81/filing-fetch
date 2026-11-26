"""Give direct pytest runs the same feedback isolation as the CI runner."""

import pytest


@pytest.fixture(autouse=True)
def isolate_feedback_environment(monkeypatch, tmp_path):
    for name in ("RESEARCH_FEEDBACK_OUT", "RESEARCH_FEEDBACK_RUN_ID", "RESEARCH_FEEDBACK_ATTEMPT_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(tmp_path / "feedback"))
