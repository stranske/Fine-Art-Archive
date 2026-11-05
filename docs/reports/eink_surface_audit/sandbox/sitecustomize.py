"""Opt-in test harness for hosts that deny asyncio's socketpair wakeup writes.

Use only through PYTHONPATH for audit commands. Polling bounds selector waits
when a thread's wakeup write is denied; all existing I/O permissions still apply.
This changes scheduling in the audit process, not application or test sources.
"""

import selectors


class AuditPollingSelector(selectors.DefaultSelector):
    def select(self, timeout=None):
        return super().select(0.01 if timeout is None else min(timeout, 0.01))


selectors.DefaultSelector = AuditPollingSelector
