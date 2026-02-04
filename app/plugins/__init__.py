"""
SAP Implementation Factory - Plugins Package

Plugin-based execution system for customizing, migration, and testing.
Each plugin handles a specific phase of the SAP implementation.
"""

from app.plugins.base import Plugin, PluginContext, PluginRegistry
from app.plugins.customizing import CustomizingPlugin
from app.plugins.migration import MigrationPlugin
from app.plugins.testing import TestingPlugin

__all__ = [
    "Plugin",
    "PluginContext",
    "PluginRegistry",
    "CustomizingPlugin",
    "MigrationPlugin",
    "TestingPlugin",
]
