"""Decide when a SoftEther session that claims to be up must be rebuilt.

``models.SessionStatus.is_phantom`` says *what* went wrong; this module decides
*when to act*.  It is deliberately free of Qt, asyncio and the D-Bus client so
the policy can be unit-tested with an injected clock instead of sleeping.

The rule: a session that reports "connected" while carrying no TCP transport is
never repaired by SoftEther itself, and ``AccountList`` keeps saying
``Connected``, so nothing else notices either.  Counting consecutive phantom
samples and then forcing ``AccountDisconnect`` + ``AccountConnect`` is the only
thing that actually drops the dead socket.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum


class RecoveryDecision(str, Enum):
    """What the caller should do after an observation."""

    NONE = "none"
    RECONNECT = "reconnect"
    EXHAUSTED = "exhausted"


@dataclass
class RecoverySettings:
    """Policy knobs, mirroring the ``[monitor]`` preference group."""

    enabled: bool = True
    after_samples: int = 3
    cooldown_s: int = 60
    max_attempts: int = 5
    grace_s: float = 30.0


class SessionRecovery:
    """Consecutive-sample policy for repairing phantom VPN sessions."""

    def __init__(
        self,
        settings: RecoverySettings | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings or RecoverySettings()
        self._clock = clock
        self._phantom_samples = 0
        self._attempts = 0
        self._last_attempt_at = 0.0
        self._grace_until = 0.0
        self._exhausted_notified = False

    @property
    def attempts(self) -> int:
        """Reconnect attempts issued since the last healthy observation."""
        return self._attempts

    @property
    def phantom_samples(self) -> int:
        return self._phantom_samples

    @property
    def in_grace(self) -> bool:
        """``True`` while a fresh reconnect is still being given time to settle."""
        return self._clock() < self._grace_until

    def observe(self, is_phantom: bool, *, busy: bool = False) -> RecoveryDecision:
        """Feed one monitor snapshot and get the action to take.

        ``busy`` defers the decision while a user-initiated action is in flight,
        so the wrapper never fights the person in front of it.
        """
        settings = self.settings
        if not settings.enabled:
            return RecoveryDecision.NONE

        now = self._clock()
        if not is_phantom:
            self._phantom_samples = 0
            # A healthy sample only clears the attempt budget once the fresh
            # session has had time to prove itself; otherwise the reconnect we
            # just issued would instantly reset its own back-off.
            if now >= self._grace_until:
                self._attempts = 0
                self._exhausted_notified = False
            return RecoveryDecision.NONE

        if now < self._grace_until:
            return RecoveryDecision.NONE

        self._phantom_samples += 1
        if self._phantom_samples < max(1, settings.after_samples) or busy:
            return RecoveryDecision.NONE

        if self._last_attempt_at and (now - self._last_attempt_at) < settings.cooldown_s:
            return RecoveryDecision.NONE

        if self._attempts >= max(1, settings.max_attempts):
            if self._exhausted_notified:
                return RecoveryDecision.NONE
            self._exhausted_notified = True
            return RecoveryDecision.EXHAUSTED

        self._phantom_samples = 0
        self._attempts += 1
        self._last_attempt_at = now
        return RecoveryDecision.RECONNECT

    def attempt_finished(self) -> None:
        """Call once the reconnect has been issued (successfully or not).

        Starts the grace window so the client has time to negotiate before the
        next samples are judged; the next natural poll verifies the result.
        """
        self._phantom_samples = 0
        self._grace_until = self._clock() + self.settings.grace_s
