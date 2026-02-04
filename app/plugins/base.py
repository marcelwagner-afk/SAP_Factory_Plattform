"""
SAP Implementation Factory - Base Plugin Interface

Defines the plugin interface and registry for extensibility.
All execution plugins must inherit from the Plugin base class.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type
import logging

from app.adapters.base import SAPAdapter
from app.models import JobResult, JobStatus, JobType

logger = logging.getLogger(__name__)


@dataclass
class PluginContext:
    """
    Execution context passed to plugins.

    Contains everything a plugin needs to execute:
    - SAP adapter for system communication
    - Run metadata
    - Storage paths
    - Shared state for cross-plugin communication
    """
    run_id: str
    adapter: SAPAdapter
    artifacts_path: str
    project_name: str
    customer: str
    target_system: str
    client: str
    shared_state: Dict[str, Any] = field(default_factory=dict)

    def log_info(self, message: str) -> Dict[str, Any]:
        """Create structured info log entry."""
        return self._create_log("INFO", message)

    def log_warning(self, message: str) -> Dict[str, Any]:
        """Create structured warning log entry."""
        return self._create_log("WARNING", message)

    def log_error(self, message: str) -> Dict[str, Any]:
        """Create structured error log entry."""
        return self._create_log("ERROR", message)

    def _create_log(self, level: str, message: str) -> Dict[str, Any]:
        """Create structured log entry."""
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "run_id": self.run_id,
            "system": self.target_system,
            "message": message,
        }


class Plugin(ABC):
    """
    Abstract base class for all execution plugins.

    Plugins handle specific phases of the implementation:
    - CustomizingPlugin: Configuration/customizing activities
    - MigrationPlugin: Data migration and loading
    - TestingPlugin: Automated testing

    Each plugin:
    - Receives context with adapter and metadata
    - Writes structured JSON logs
    - Returns status and KPIs
    - Generates artifacts
    """

    # Plugin metadata (override in subclasses)
    PLUGIN_NAME: str = "base"
    PLUGIN_TYPE: JobType = JobType.CUSTOMIZING

    def __init__(self):
        """Initialize plugin."""
        self.logger = logging.getLogger(f"plugin.{self.PLUGIN_NAME}")

    @abstractmethod
    def execute(
        self,
        context: PluginContext,
        config: Dict[str, Any],
    ) -> JobResult:
        """
        Execute the plugin's main logic.

        Args:
            context: Execution context with adapter and metadata
            config: Plugin-specific configuration

        Returns:
            JobResult with execution status and metrics
        """
        pass

    @abstractmethod
    def validate(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate plugin configuration.

        Args:
            config: Configuration to validate

        Returns:
            List of validation errors (empty if valid)
        """
        pass

    def get_kpis(self, result: JobResult) -> Dict[str, Any]:
        """
        Calculate KPIs from execution result.

        Args:
            result: Job execution result

        Returns:
            Dictionary of KPI metrics
        """
        total = result.records_processed
        success_rate = (
            (result.records_success / total * 100) if total > 0 else 100.0
        )

        return {
            "total_records": total,
            "success_records": result.records_success,
            "failed_records": result.records_failed,
            "success_rate_percent": round(success_rate, 2),
            "duration_seconds": result.duration_seconds,
            "throughput_per_second": (
                round(total / result.duration_seconds, 2)
                if result.duration_seconds > 0
                else 0
            ),
        }

    def create_result(
        self,
        job_id: str,
        job_name: str,
        status: JobStatus,
        started_at: datetime,
        records_processed: int = 0,
        records_success: int = 0,
        records_failed: int = 0,
        error_message: Optional[str] = None,
        logs: Optional[List[Dict[str, Any]]] = None,
        artifacts: Optional[List[str]] = None,
    ) -> JobResult:
        """
        Create a standardized job result.

        Args:
            job_id: Unique job identifier
            job_name: Human-readable job name
            status: Final job status
            started_at: Job start timestamp
            records_processed: Total records handled
            records_success: Successful records
            records_failed: Failed records
            error_message: Error details if failed
            logs: Execution logs
            artifacts: Generated artifact paths

        Returns:
            Populated JobResult instance
        """
        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        result = JobResult(
            job_id=job_id,
            job_type=self.PLUGIN_TYPE,
            job_name=job_name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration,
            records_processed=records_processed,
            records_success=records_success,
            records_failed=records_failed,
            error_message=error_message,
            logs=logs or [],
            artifacts=artifacts or [],
        )

        # Calculate and add KPIs
        result.kpis = self.get_kpis(result)

        return result


class PluginRegistry:
    """
    Registry for managing available plugins.

    Usage:
        PluginRegistry.register(CustomizingPlugin)
        plugin = PluginRegistry.get("customizing")
    """

    _plugins: Dict[str, Type[Plugin]] = {}

    @classmethod
    def register(cls, plugin_class: Type[Plugin]) -> None:
        """Register a plugin class."""
        name = plugin_class.PLUGIN_NAME
        cls._plugins[name] = plugin_class
        logger.info(f"Registered plugin: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[Plugin]:
        """Get plugin instance by name."""
        plugin_class = cls._plugins.get(name)
        if plugin_class:
            return plugin_class()
        return None

    @classmethod
    def get_by_type(cls, job_type: JobType) -> Optional[Plugin]:
        """Get plugin instance by job type."""
        for plugin_class in cls._plugins.values():
            if plugin_class.PLUGIN_TYPE == job_type:
                return plugin_class()
        return None

    @classmethod
    def available(cls) -> List[str]:
        """Get list of available plugin names."""
        return list(cls._plugins.keys())

    @classmethod
    def all_plugins(cls) -> Dict[str, Type[Plugin]]:
        """Get all registered plugins."""
        return cls._plugins.copy()
