"""Paper broker placeholder. Fill simulation arrives in Phase 9.

It has no network client and no credentials, by design.
"""

from __future__ import annotations


class PaperBroker:
    is_paper = True

    def submit(self, order: dict) -> dict:
        raise NotImplementedError("Paper fill simulation is implemented in Phase 9.")
