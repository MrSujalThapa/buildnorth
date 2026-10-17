from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class ExponentialDecay:
    half_life_days: float

    def __post_init__(self) -> None:
        if self.half_life_days <= 0:
            raise ValueError("half_life_days must be positive")

    def weights(self, ages_days: NDArray[np.float64]) -> NDArray[np.float64]:
        if np.any(ages_days < 0):
            raise ValueError("event ages cannot be negative")
        return np.power(0.5, ages_days / self.half_life_days)

    def aggregate(self, values: NDArray[np.float64], ages_days: NDArray[np.float64]) -> float:
        if values.shape != ages_days.shape:
            raise ValueError("values and ages must have the same shape")
        return float(np.sum(values * self.weights(ages_days)))
