"""Variant-upgrade logic shared by the detector and the promotion executor."""

from .upgrade_gates import CropGate, crop_gate, master_facts

__all__ = ["CropGate", "crop_gate", "master_facts"]
