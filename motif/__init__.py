"""Motif: a motion-graphics language designed for AI models to write."""

from .schema import MOTIF_VERSION, Scene
from .validator import validate

__all__ = ["MOTIF_VERSION", "Scene", "validate"]
