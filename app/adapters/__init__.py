"""
SAP Implementation Factory - Adapters Package

Provides adapter interfaces and implementations for SAP system communication.
The adapter pattern allows swapping between fake (simulation) and real SAP adapters.
"""

from app.adapters.base import SAPAdapter
from app.adapters.fake_sap import FakeSAPAdapter

__all__ = ["SAPAdapter", "FakeSAPAdapter"]
