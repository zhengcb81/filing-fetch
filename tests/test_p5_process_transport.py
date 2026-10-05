"""FAILING-FIRST tests: JSON subprocesses are bounded DURING read.

P5-FF: one shared bounded-process layer limits the child's stdout/stderr in
actual bytes while reading, shares the remaining deadline, decodes strictly
as UTF-8, reaps the process tree it created, and never retries or absorbs a
failed run. Both transports (filing runner + transcript runner) must reuse it.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ff_process_transport as fpt  # noqa: E402
import fetch_filing  # noqa: E402
import transcript_tool_transport as ttt  # noqa: E402


class BoundedTransportUnitTests(unittest.TestCase):
    """ff_process_transport.run_bounded core behaviour."""

    def test_stdout_counted_in_utf8_bytes_not_chars(self):
        # 1000 CJK chars == 3000 UTF-8 bytes; a 2500-byte cap must fail even
        # though the string is only 1000 Python "characters" long.
        child = "import sys\nsys.stdout.write('字'*1000)\nsys.stdout.flush()\n"
        with self.assertRaises(fpt.OutputLimitExceeded):
            fpt.run_bounded(
                [sys.executable, "-S", "-X", "utf8", "-c", child],
                stdout_cap_bytes=2500,
                timeout_seconds=30,
            )

    def test_capture_at_cap_stops_reading(self):
        # Child writes 64 MiB quickly; cap is 1 MiB. Elapsed wall time must be
        # small (read stopped early), and the result must be a named failure.
        child = (
            "import sys,time;sys.stdout.write('a'*(64*1024*1024));sys.stdout.flush();time.sleep(30)"
        )
        start = time.monotonic()
        with self.assertRaises(fpt.OutputLimitExceeded) as ctx:
            fpt.run_bounded(
                [sys.executable, "-S", "-c", child],
                stdout_cap_bytes=1 * 1024 * 1024,
                timeout_seconds=20,
            )
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 15, "read did not stop near the cap")
        _ = ctx.exception

    def test_stderr_concurrently_bounded(self):
        child = (
            "import sys,time\n"
            "for _ in range(200000):\n"
            "    sys.stderr.write('b'*4096)\n"
            "sys.stderr.flush(); time.sleep(30)\n"
        )
        start = time.monotonic()
        with self.assertRaises(fpt.OutputLimitExceeded):
            fpt.run_bounded(
                [sys.executable, "-S", "-c", child],
                stderr_cap_bytes=256 * 1024,
                timeout_seconds=20,
            )
        self.assertLess(time.monotonic() - start, 15)

    def test_success_returns_bounded_bytes_and_exit(self):
        child = "import sys; sys.stdout.write('ok'); print('!')"
        result = fpt.run_bounded([sys.executable, "-S", "-c", child], timeout_seconds=30)
        self.assertEqual(result["returncode"], 0)
        self.assertIn(b"ok", result["stdout"])
        self.assertEqual(result["stderr_bytes_read"], 0)

    def test_nonzero_exit_raises_named_error(self):
        child = "import sys; sys.stderr.write('boom'); sys.exit(3)"
        with self.assertRaises(fpt.ChildFailed) as ctx:
            fpt.run_bounded([sys.executable, "-S", "-c", child], timeout_seconds=30)
        self.assertEqual(ctx.exception.returncode, 3)

    def test_deadline_shared_not_renewed(self):
        start = time.monotonic()
        with self.assertRaises(fpt.ChildTimeout):
            fpt.run_bounded(
                [sys.executable, "-S", "-c", "import time;time.sleep(60)"],
                timeout_seconds=1.5,
            )
        self.assertLess(time.monotonic() - start, 13)

    def test_grandchild_holding_pipe_never_hangs(self):
        # Child spawns a grandchild seeding the grandchild's stdout/stderr to
        # OS null handles *except* one inherited anonymous pipe that the child
        # itself owns — the child exits first; the parent must not wait on the
        # grandchild. kill_tree reaps the orphan afterwards.
        if os.name != "nt":
            self.skipTest("windows-family process-tree reaper test")
        child = (
            "import subprocess,sys,os\n"
            "p = subprocess.Popen([\n"
            "  sys.executable,'-S','-c','import time;time.sleep(60)'\n"
            "])\n"
            "print('parent-exit')\n"
            "sys.stdout.flush()\n"
        )
        start = time.monotonic()
        result = fpt.run_bounded(
            [sys.executable, "-S", "-X", "utf8", "-c", child],
            timeout_seconds=15,
        )
        self.assertLess(time.monotonic() - start, 14)
        self.assertIn(b"parent-exit", result["stdout"])

    def test_thread_pool_reaped_after_run(self):
        before = len([t for t in __import__("threading").enumerate() if "ff-process" in t.name])
        child = "print('hi')"
        fpt.run_bounded([sys.executable, "-S", "-c", child], timeout_seconds=20)
        deadline = time.monotonic() + 5
        after = None
        while time.monotonic() < deadline:
            after = len([t for t in __import__("threading").enumerate() if "ff-process" in t.name])
            if after <= before:
                break
            time.sleep(0.05)
        self.assertLessEqual(after or 0, before)


class FilingRunnerReusesLayerTests(unittest.TestCase):
    """fetch_filing._run_company_wiki_json delegates to the shared layer."""

    def test_runner_uses_shared_transport(self):
        self.assertIs(fetch_filing._run_bounded, fpt.run_bounded)

    def test_runner_failure_stays_named_upstream_error(self):
        # An overflowing child is reclassified as the runner's own named code:
        # 40 MiB of stdout must trip the 32 MiB read-time cap (upstream_error),
        # never the "stdout is not JSON" fatal branch and never a full
        # buffering wait.
        child = "import sys; sys.stdout.write('a'*(40*1024*1024))"
        start = time.monotonic()
        with self.assertRaises(fetch_filing.FilingFetchError) as ctx:
            fetch_filing._run_company_wiki_json(
                command=[sys.executable, "-S", "-c", child],
                root=Path(tempfile.gettempdir()),
                timeout_seconds=20,
                action="ensure",
            )
        self.assertEqual(ctx.exception.code, "upstream_error")
        self.assertIn("output byte cap", str(ctx.exception))
        # The read had to stop near the cap (40 MiB < buffered-wait time).
        self.assertLess(time.monotonic() - start, 19)


class TranscriptRunnerReusesLayerTests(unittest.TestCase):
    """transcript_tool_transport subprocesses delegate to the shared layer."""

    def test_runner_uses_shared_transport(self):
        self.assertIs(ttt._run_bounded, fpt.run_bounded)

    def test_verified_open_stderr_cap_is_real(self):
        # Child writes far beyond the stderr cap; must fail during read.
        child = (
            "import sys,time\n"
            "sys.stderr.write('c'*(2*1024*1024)); sys.stderr.flush()\n"
            "time.sleep(30)\n"
        )
        start = time.monotonic()
        with self.assertRaises((fpt.OutputLimitExceeded, ValueError)):
            fpt.run_bounded(
                [sys.executable, "-S", "-c", child],
                stderr_cap_bytes=64 * 1024,
                timeout_seconds=20,
            )
        self.assertLess(time.monotonic() - start, 15)


if __name__ == "__main__":
    unittest.main()
