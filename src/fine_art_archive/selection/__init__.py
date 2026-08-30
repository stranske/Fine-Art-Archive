"""Candidate selection: which of the eligible works to actually acquire."""

from .lenses import (
    LENS_SHARES,
    Lens,
    LensReport,
    SaturationReport,
    allocate,
    apply_saturation_cap,
    select,
)

__all__ = [
    "LENS_SHARES",
    "Lens",
    "LensReport",
    "SaturationReport",
    "allocate",
    "apply_saturation_cap",
    "select",
]
