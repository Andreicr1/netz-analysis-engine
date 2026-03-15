"""Quant Engine — universal quantitative analytics services.

Services in this package follow the parameter-injection pattern:
config resolved once at async entry point via ConfigService.get(),
passed down to sync functions as dict parameter.

Import direction: quant_engine/ imports from app.shared.models (global tables).
Some services still import from app.domains.wealth (documented in their docstrings).
"""
