"""A Wilson confidence interval for a proportion.

Attack success rates here come from tens of runs, not thousands, so a point estimate like
"3 of 20" on its own is misleading. The Wilson interval stays sensible at small n and at rates
near 0 or 1, where the textbook normal interval doesn't. No SciPy needed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# z for a 95% two-sided interval.
Z95 = 1.959963984540054


@dataclass(frozen=True)
class Proportion:
    successes: int
    total: int
    low: float
    high: float

    @property
    def rate(self) -> float:
        return self.successes / self.total if self.total else 0.0

    def pct(self) -> str:
        if not self.total:
            return "n/a (0 runs)"
        ci = f"95% CI {self.low:.0%}-{self.high:.0%}"
        return f"{self.rate:.0%} ({self.successes}/{self.total}, {ci})"


def wilson(successes: int, total: int, z: float = Z95) -> Proportion:
    if total <= 0:
        return Proportion(successes, total, 0.0, 0.0)
    if successes < 0 or successes > total:
        raise ValueError("successes must be between 0 and total")
    p = successes / total
    z2 = z * z
    denom = 1 + z2 / total
    centre = (p + z2 / (2 * total)) / denom
    half = (z / denom) * math.sqrt(p * (1 - p) / total + z2 / (4 * total * total))
    return Proportion(successes, total, max(0.0, centre - half), min(1.0, centre + half))
