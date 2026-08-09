"""Preference modelling from Tim's ratings (owner decision D6)."""

from .rocchio import PreferenceVector, build, features_of, score

__all__ = ["PreferenceVector", "build", "features_of", "score"]
