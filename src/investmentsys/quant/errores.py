"""Errores compartidos por los módulos de ``quant/``."""

from __future__ import annotations


class LookAheadError(ValueError):
    """La muestra contiene observaciones posteriores a la fecha de decisión."""
