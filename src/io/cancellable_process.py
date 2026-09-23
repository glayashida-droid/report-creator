"""Run a child process that close can kill before the timeout."""

from __future__ import annotations

import subprocess
import time
from typing import Optional, Sequence, Union


class ProcessCancelled(Exception):
    """The caller asked the child to stop."""


def run_cancellable(
    args: Sequence[str],
    *,
    input: Optional[Union[bytes, str]] = None,
    timeout: Optional[float] = None,
    env=None,
    cwd=None,
    text: bool = False,
    cancelled=None,
    poll_sec: float = 0.05,
) -> subprocess.CompletedProcess:
    """Like subprocess.run, but `cancelled()` kills the child on the next poll."""
    proc = subprocess.Popen(
        list(args),
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=cwd,
        text=text,
    )
    deadline = None if timeout is None else time.monotonic() + float(timeout)
    sent_input = False
    step = max(float(poll_sec), 0.01)
    try:
        while True:
            communicate_input = input if not sent_input else None
            sent_input = True
            try:
                stdout, stderr = proc.communicate(input=communicate_input, timeout=step)
                break
            except subprocess.TimeoutExpired:
                if cancelled is not None and cancelled():
                    _kill(proc)
                    raise ProcessCancelled()
                if deadline is not None and time.monotonic() >= deadline:
                    _kill(proc)
                    raise subprocess.TimeoutExpired(list(args), timeout)
        return subprocess.CompletedProcess(list(args), proc.returncode, stdout, stderr)
    finally:
        if proc.poll() is None:
            _kill(proc)


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.kill()
    try:
        proc.communicate(timeout=2)
    except Exception:
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
