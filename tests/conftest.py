"""Give direct pytest runs the same feedback isolation as the CI runner."""

import pytest


@pytest.fixture(autouse=True)
def isolate_feedback_environment(monkeypatch, tmp_path_factory):
    for name in ("RESEARCH_FEEDBACK_OUT", "RESEARCH_FEEDBACK_RUN_ID", "RESEARCH_FEEDBACK_ATTEMPT_ID"):
        monkeypatch.delenv(name, raising=False)
    directory = tmp_path_factory.mktemp("feedback")
    monkeypatch.setenv("RESEARCH_FEEDBACK_DIR", str(directory))
