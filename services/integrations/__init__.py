"""
Forest AI Integration Layer.

See base.py (IntegrationAdapter interface), categories.py (per-category
base classes), registry.py (provider catalog), manager.py (orchestration
called by api.py), risk_rules.py (Risk Engine bridge), demo/ (stage-1 demo
adapters: Fleet GPS, Sentinel, Weighbridge).
"""

from .base import IntegrationAdapter, AdapterError
from . import categories, registry, manager, risk_rules, crypto

__all__ = ["IntegrationAdapter", "AdapterError", "categories", "registry", "manager", "risk_rules", "crypto"]
