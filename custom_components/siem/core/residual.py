"""Optional load-residual baseline: unexplained power steps."""

from __future__ import annotations


class LoadResidualDetector:
    """Detect a sustained step in the house load minus its automated loads.

    The baseline is an exponential moving average of the residual. When the
    residual rises at least ``step_watts`` above it and stays there for
    ``sustain_minutes``, the detector fires once and adopts the new level so
    the same appliance is not reported again until it changes.
    """

    def __init__(self, step_watts: float = 100.0, sustain_minutes: float = 5.0, alpha: float = 0.05) -> None:
        """Configure the step size, the sustain time and the baseline smoothing."""
        self.step_watts = step_watts
        self.sustain_s = sustain_minutes * 60.0
        self._alpha = alpha
        self.baseline: float | None = None
        self.residual: float | None = None
        self._candidate_since: float | None = None

    def update(self, load_w: float, automated_w: float, now: float) -> bool:
        """Feed a load sample; return True when a sustained step is confirmed."""
        residual = load_w - automated_w
        self.residual = residual
        if self.baseline is None:
            self.baseline = residual
            return False
        if residual - self.baseline >= self.step_watts:
            if self._candidate_since is None:
                self._candidate_since = now
            elif now - self._candidate_since >= self.sustain_s:
                self.baseline = residual
                self._candidate_since = None
                return True
            return False
        self._candidate_since = None
        self.baseline += self._alpha * (residual - self.baseline)
        return False
