"""Estimación cuantitativa determinista (covarianzas, retornos, régimen). Sin ADK ni LLM."""

from investmentsys.quant.covariance import estimar_covarianza
from investmentsys.quant.estimates import estimar

__all__ = ["estimar", "estimar_covarianza"]
