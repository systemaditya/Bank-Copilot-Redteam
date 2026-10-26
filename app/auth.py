"""Mock sessions for the lab.

Logging in only needs a customer or staff number, no password. Authentication isn't what this
project is about: the attacks assume someone who is already signed in (T12 in
docs/threat-model.md). Obviously, don't do this in a real system.
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Principal:
    kind: Literal["customer", "staff"]
    id: int
    number: str  # customer or staff number, e.g. C1000 or S100

    @property
    def actor(self) -> str:
        """How this principal appears in the audit log, e.g. ``staff:S100``."""
        return f"{self.kind}:{self.number}"


class SessionStore:
    def __init__(self) -> None:
        self._tokens: dict[str, Principal] = {}
        self._lock = threading.Lock()

    def create(self, principal: Principal) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = principal
        return token

    def resolve(self, token: str) -> Principal | None:
        with self._lock:
            return self._tokens.get(token)
