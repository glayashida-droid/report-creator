"""Keep background warm-up off the UI thread's scheduling class."""

from __future__ import annotations

import sys

_QOS_CLASS_BACKGROUND = 0x09
_applied = False


def run_in_background() -> None:
    """Mark the current thread as background work and yield the GIL more often.

    QoS does not release the GIL by itself. Callers still sleep between chunks
    so the UI thread can take mouse events.
    """
    global _applied
    if sys.platform == "darwin":
        try:
            import ctypes

            libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
            libc.pthread_set_qos_class_self_np(_QOS_CLASS_BACKGROUND, 0)
        except Exception:
            pass
    if not _applied:
        try:
            sys.setswitchinterval(0.002)
        except Exception:
            pass
        _applied = True
