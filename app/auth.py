"""Mock sessions for the lab.

Logging in only needs a customer number, no password. Authentication isn't what this project
is about: the attacks assume someone who is already signed in as a customer (T12 in
docs/threat-model.md). Obviously, don't do this in a real system.
"""

from __future__ import annotations

import secrets
import threading


class SessionStore:
    def __init__(self) -> None:
        self._tokens: dict[str, int] = {}
        self._lock = threading.Lock()

    def create(self, customer_id: int) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = customer_id
        return token

    def resolve(self, token: str) -> int | None:
        with self._lock:
            return self._tokens.get(token)
