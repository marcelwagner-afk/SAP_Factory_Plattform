"""
SAP Implementation Factory - Base Adapter Interface

Defines the abstract interface that all SAP adapters must implement.
This enables swapping between FakeSAP (simulation) and real SAP connections.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass
from enum import Enum


class APICallResult(Enum):
    """Result status of an API call."""
    SUCCESS = "success"
    ERROR = "error"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"


@dataclass
class TableOperationResult:
    """Result of a table operation."""
    success: bool
    table: str
    operation: str  # insert, update, delete
    key: Dict[str, Any]
    message: str = ""
    affected_rows: int = 0


@dataclass
class DataLoadResult:
    """Result of a data load operation."""
    success: bool
    object_type: str
    records_total: int
    records_loaded: int
    records_failed: int
    errors: List[Dict[str, Any]]
    reconciliation: Dict[str, Any]


@dataclass
class APIResponse:
    """Response from an API call."""
    status: APICallResult
    status_code: int
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    duration_ms: float = 0.0


class SAPAdapter(ABC):
    """
    Abstract base class for SAP system adapters.

    All SAP adapters (fake or real) must implement this interface.
    This ensures consistent behavior across simulation and production.
    """

    def __init__(self, system_id: str, client: str):
        """
        Initialize adapter for a specific SAP system.

        Args:
            system_id: SAP system identifier (DEV, QAS, PRD)
            client: SAP client number
        """
        self.system_id = system_id
        self.client = client

    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to SAP system.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    def disconnect(self) -> None:
        """Close connection to SAP system."""
        pass

    @abstractmethod
    def set_table(
        self,
        table: str,
        key: Dict[str, Any],
        values: Dict[str, Any],
    ) -> TableOperationResult:
        """
        Set/update a table entry (customizing).

        Args:
            table: SAP table name (e.g., T001, T001K)
            key: Key fields to identify the record
            values: Field values to set

        Returns:
            TableOperationResult with operation status
        """
        pass

    @abstractmethod
    def get_table(
        self,
        table: str,
        key: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Read table entries.

        Args:
            table: SAP table name
            key: Optional key filter
            fields: Optional field list to return

        Returns:
            List of table entries as dictionaries
        """
        pass

    @abstractmethod
    def delete_table(
        self,
        table: str,
        key: Dict[str, Any],
    ) -> TableOperationResult:
        """
        Delete a table entry.

        Args:
            table: SAP table name
            key: Key fields to identify record to delete

        Returns:
            TableOperationResult with operation status
        """
        pass

    @abstractmethod
    def load_data(
        self,
        object_type: str,
        data: List[Dict[str, Any]],
        mapping: Dict[str, str],
    ) -> DataLoadResult:
        """
        Load data into SAP (migration).

        Args:
            object_type: Type of object (BUSINESS_PARTNER, MATERIAL, etc.)
            data: List of records to load
            mapping: Field mapping (source -> SAP)

        Returns:
            DataLoadResult with load statistics
        """
        pass

    @abstractmethod
    def call_api(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """
        Call SAP API (REST/OData).

        Args:
            endpoint: API endpoint path
            method: HTTP method
            params: Query parameters
            data: Request body data

        Returns:
            APIResponse with result
        """
        pass

    @abstractmethod
    def call_bapi(
        self,
        bapi: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Call SAP BAPI/RFC function.

        Args:
            bapi: BAPI/RFC function name
            params: Input parameters

        Returns:
            BAPI return structure
        """
        pass

    @abstractmethod
    def get_state(self) -> Dict[str, Any]:
        """
        Get current adapter state (for debugging/auditing).

        Returns:
            Dictionary with current state information
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset adapter state (for testing)."""
        pass


class AdapterFactory:
    """
    Factory for creating SAP adapters.

    Usage:
        adapter = AdapterFactory.create("fake", "DEV", "100")
    """

    _adapters: Dict[str, type] = {}

    @classmethod
    def register(cls, adapter_type: str, adapter_class: type) -> None:
        """Register an adapter type."""
        cls._adapters[adapter_type] = adapter_class

    @classmethod
    def create(
        cls,
        adapter_type: str,
        system_id: str,
        client: str,
        **kwargs,
    ) -> SAPAdapter:
        """
        Create an adapter instance.

        Args:
            adapter_type: Type of adapter ("fake", "rfc", "odata")
            system_id: SAP system ID
            client: SAP client number
            **kwargs: Additional adapter-specific arguments

        Returns:
            Configured SAPAdapter instance

        Raises:
            ValueError: If adapter type is not registered
        """
        if adapter_type not in cls._adapters:
            raise ValueError(
                f"Unknown adapter type: {adapter_type}. "
                f"Available: {list(cls._adapters.keys())}"
            )
        return cls._adapters[adapter_type](system_id, client, **kwargs)

    @classmethod
    def available_adapters(cls) -> List[str]:
        """Get list of available adapter types."""
        return list(cls._adapters.keys())
