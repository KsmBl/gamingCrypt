"""Smooth download progress although Steam updates its byte counters only rarely.

Steam often leaves "BytesDownloaded" at 0 until the end. The bytes the network
received since Steam's last counter update fill the gap; whenever Steam's
counter moves we re-sync to it, and the shown value never goes backwards.
"""

from __future__ import annotations

ACTIVE_RATE = 64 * 1024  # B/s - below this nothing is really downloading


class ProgressEstimator:
    def __init__(self):
        self.sync: dict[int, tuple[int, int]] = {}  # appid -> (Steam's count, network bytes then)
        self.shown: dict[int, int] = {}

    def estimate(self, appid: int, downloaded: int, total: int, net_rx: int | None,
                 since: int | None = None) -> int:
        """``since``: network counter when this download was first seen running (the
        previous measurement) - so the interval that revealed it is counted too."""
        if not total or net_rx is None:
            return downloaded
        base, net_at = self.sync.get(appid, (None, None))
        if base is None and since is not None:
            base, net_at = downloaded, since
            self.sync[appid] = (base, net_at)
        if base != downloaded:
            self.sync[appid] = (downloaded, net_rx)
            base, net_at = downloaded, net_rx
        guess = min(total, base + max(0, net_rx - net_at))
        shown = min(total, max(guess, self.shown.get(appid, 0), downloaded))
        self.shown[appid] = shown
        return shown

    def reset(self, appid: int, net_rx: int | None) -> None:
        """Not receiving for this game right now: freeze the network baseline."""
        if appid in self.sync and net_rx is not None:
            base, _ = self.sync[appid]
            self.sync[appid] = (base, net_rx - (self.shown.get(appid, base) - base))

    def forget(self, appid: int) -> None:
        self.sync.pop(appid, None)
        self.shown.pop(appid, None)
