"""Bounded single-process controls for the public, account-free mock demo."""
from __future__ import annotations

import os
from dataclasses import dataclass


def integer(name: str, default: int, minimum: int, maximum: int) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class ReplayLimits:
    max_sessions: int = 32
    max_playing: int = 32
    idle_seconds: int = 86_400
    max_age_seconds: int = 86_400
    persist_interval_seconds: float = 0
    ready_seconds: int = 86_400
    ended_seconds: int = 86_400
    disconnected_pause_seconds: int = 86_400

    @classmethod
    def environment(cls):
        public = os.getenv("PUBLIC_DEMO", "false").lower() == "true"
        return cls(max_sessions=integer("MAX_SESSIONS", 24 if public else 32, 1, 64),
            max_playing=integer("MAX_PLAYING_SESSIONS", 8 if public else 32, 1, 32),
            idle_seconds=integer("SESSION_IDLE_SECONDS", 1800 if public else 86_400, 60, 86_400),
            max_age_seconds=integer("SESSION_MAX_AGE_SECONDS", 21_600 if public else 86_400, 300, 86_400),
            persist_interval_seconds=.5 if public else 0,
            ready_seconds=integer("SESSION_READY_SECONDS", 120 if public else 86_400, 30, 86_400),
            ended_seconds=integer("SESSION_ENDED_SECONDS", 900 if public else 86_400, 60, 86_400),
            disconnected_pause_seconds=integer("DISCONNECTED_PAUSE_SECONDS", 30 if public else 86_400, 10, 86_400))
