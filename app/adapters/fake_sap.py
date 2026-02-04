"""
SAP Implementation Factory - Fake SAP Adapter

Simulates SAP system behavior for prototyping and testing.
Stores data in-memory with JSON persistence for state inspection.
"""

from __future__ import annotations
import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from app.adapters.base import (
    SAPAdapter,
    AdapterFactory,
    TableOperationResult,
    DataLoadResult,
    APIResponse,
    APICallResult,
)

logger = logging.getLogger(__name__)


class FakeSAPAdapter(SAPAdapter):
    """
    Fake SAP Adapter for simulation and prototyping.

    Features:
    - In-memory table storage (simulates SAP tables)
    - Simulated API responses
    - Data migration with validation
    - Reconciliation report generation
    - State persistence to JSON

    This adapter allows testing the entire implementation flow
    without requiring a real SAP system.
    """

    # Simulated SAP tables with their key fields
    TABLE_DEFINITIONS: Dict[str, List[str]] = {
        # FI Tables
        "T001": ["BUKRS"],  # Company Codes
        "T001K": ["BUKRS", "KTOPL"],  # Chart of Accounts Assignment
        "SKA1": ["KTOPL", "SAKNR"],  # GL Account Master (COA)
        "SKB1": ["BUKRS", "SAKNR"],  # GL Account Master (Company Code)
        "T003": ["BLART"],  # Document Types
        "T007A": ["KALSM", "MWSKZ"],  # Tax Codes
        "T052": ["ZTERM"],  # Payment Terms

        # CO Tables
        "CSKS": ["KOKRS", "KOSTL"],  # Cost Centers
        "CEPC": ["KOKRS", "PRCTR"],  # Profit Centers
        "CSKA": ["KTOPL", "KSTAR"],  # Cost Elements

        # MM Tables
        "T001W": ["WERKS"],  # Plants
        "T001L": ["WERKS", "LGORT"],  # Storage Locations
        "MARA": ["MATNR"],  # Material Master (General)
        "MARC": ["MATNR", "WERKS"],  # Material Master (Plant)
        "LFA1": ["LIFNR"],  # Vendor Master

        # SD Tables
        "KNA1": ["KUNNR"],  # Customer Master
        "TVKO": ["VKORG"],  # Sales Organizations
        "TVTW": ["VTWEG"],  # Distribution Channels
        "KNVV": ["KUNNR", "VKORG", "VTWEG", "SPART"],  # Customer Sales Data

        # BP Tables (S/4HANA)
        "BUT000": ["PARTNER"],  # Business Partner
        "BUT020": ["PARTNER", "ADDRNUMBER"],  # BP Addresses
        "BUT100": ["PARTNER", "RLTYP"],  # BP Roles
    }

    # Simulated API endpoints
    API_ENDPOINTS: Dict[str, Dict[str, Any]] = {
        "/sap/health": {"status": "healthy", "version": "S/4HANA 2023"},
        "/sap/opu/odata/sap/API_BUSINESS_PARTNER": {"d": {"results": []}},
        "/sap/opu/odata/sap/API_MATERIAL_DOCUMENT_SRV": {"d": {"results": []}},
        "/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV": {"d": {"results": []}},
    }

    def __init__(
        self,
        system_id: str,
        client: str,
        simulate_latency: bool = True,
        failure_rate: float = 0.0,
        state_path: Optional[str] = None,
    ):
        """
        Initialize Fake SAP Adapter.

        Args:
            system_id: SAP system identifier
            client: SAP client number
            simulate_latency: Add realistic delays
            failure_rate: Probability of simulated failures (0.0 - 1.0)
            state_path: Optional path to persist state
        """
        super().__init__(system_id, client)
        self.simulate_latency = simulate_latency
        self.failure_rate = failure_rate
        self.state_path = Path(state_path) if state_path else None

        # In-memory storage
        self._tables: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._api_calls: List[Dict[str, Any]] = []
        self._migrations: Dict[str, DataLoadResult] = {}
        self._connected = False
        self._operation_count = 0

        # Initialize empty tables
        for table in self.TABLE_DEFINITIONS:
            self._tables[table] = {}

        logger.info(
            f"FakeSAPAdapter initialized: system={system_id}, client={client}"
        )

    def _simulate_latency(self, base_ms: int = 50, variance_ms: int = 30) -> None:
        """Simulate realistic network/processing latency."""
        if self.simulate_latency:
            delay = (base_ms + random.randint(-variance_ms, variance_ms)) / 1000
            time.sleep(max(0.01, delay))

    def _should_fail(self) -> bool:
        """Check if operation should fail (for testing error handling)."""
        return random.random() < self.failure_rate

    def _make_key(self, table: str, key: Dict[str, Any]) -> str:
        """Create unique key string for table entry."""
        key_fields = self.TABLE_DEFINITIONS.get(table, ["KEY"])
        key_parts = [str(key.get(f, "")) for f in key_fields]
        return "|".join(key_parts)

    def connect(self) -> bool:
        """Simulate connection to SAP system."""
        self._simulate_latency(100, 50)
        if self._should_fail():
            logger.error(f"Connection failed to {self.system_id}")
            return False
        self._connected = True
        logger.info(f"Connected to FakeSAP: {self.system_id}/{self.client}")
        return True

    def disconnect(self) -> None:
        """Simulate disconnection."""
        self._connected = False
        logger.info(f"Disconnected from FakeSAP: {self.system_id}")

    def set_table(
        self,
        table: str,
        key: Dict[str, Any],
        values: Dict[str, Any],
    ) -> TableOperationResult:
        """Set/update table entry."""
        self._simulate_latency(30, 15)
        self._operation_count += 1

        if self._should_fail():
            return TableOperationResult(
                success=False,
                table=table,
                operation="update",
                key=key,
                message="Simulated failure",
                affected_rows=0,
            )

        # Initialize table if needed
        if table not in self._tables:
            self._tables[table] = {}

        key_str = self._make_key(table, key)
        is_insert = key_str not in self._tables[table]

        # Merge key and values
        entry = {**key, **values}
        entry["_MODIFIED_AT"] = datetime.utcnow().isoformat()
        entry["_MODIFIED_BY"] = "SAP_FACTORY"

        self._tables[table][key_str] = entry

        operation = "insert" if is_insert else "update"
        logger.debug(f"Table {operation}: {table} key={key}")

        return TableOperationResult(
            success=True,
            table=table,
            operation=operation,
            key=key,
            message=f"Successfully {operation}ed entry",
            affected_rows=1,
        )

    def get_table(
        self,
        table: str,
        key: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Read table entries."""
        self._simulate_latency(20, 10)

        if table not in self._tables:
            return []

        entries = list(self._tables[table].values())

        # Filter by key if provided
        if key:
            entries = [
                e for e in entries
                if all(e.get(k) == v for k, v in key.items())
            ]

        # Filter fields if specified
        if fields:
            entries = [
                {k: e.get(k) for k in fields if k in e}
                for e in entries
            ]

        return entries

    def delete_table(
        self,
        table: str,
        key: Dict[str, Any],
    ) -> TableOperationResult:
        """Delete table entry."""
        self._simulate_latency(30, 15)
        self._operation_count += 1

        if table not in self._tables:
            return TableOperationResult(
                success=False,
                table=table,
                operation="delete",
                key=key,
                message="Table not found",
                affected_rows=0,
            )

        key_str = self._make_key(table, key)
        if key_str in self._tables[table]:
            del self._tables[table][key_str]
            return TableOperationResult(
                success=True,
                table=table,
                operation="delete",
                key=key,
                message="Entry deleted",
                affected_rows=1,
            )

        return TableOperationResult(
            success=False,
            table=table,
            operation="delete",
            key=key,
            message="Entry not found",
            affected_rows=0,
        )

    def load_data(
        self,
        object_type: str,
        data: List[Dict[str, Any]],
        mapping: Dict[str, str],
    ) -> DataLoadResult:
        """Load data into SAP (migration simulation)."""
        self._simulate_latency(100 + len(data), 50)

        # Determine target table based on object type
        table_map = {
            "BUSINESS_PARTNER": "BUT000",
            "CUSTOMER": "KNA1",
            "VENDOR": "LFA1",
            "MATERIAL": "MARA",
            "COST_CENTER": "CSKS",
            "PROFIT_CENTER": "CEPC",
            "GL_ACCOUNT": "SKA1",
        }

        target_table = table_map.get(object_type, object_type)
        if target_table not in self._tables:
            self._tables[target_table] = {}

        records_loaded = 0
        records_failed = 0
        errors = []

        for i, record in enumerate(data):
            # Apply mapping
            mapped_record = {}
            for source_field, target_field in mapping.items():
                if source_field in record:
                    mapped_record[target_field] = record[source_field]

            # Simulate random failures
            if self._should_fail():
                records_failed += 1
                errors.append({
                    "record_index": i,
                    "error": "Simulated validation failure",
                    "data": record,
                })
                continue

            # Generate key
            key_fields = self.TABLE_DEFINITIONS.get(target_table, ["KEY"])
            key = {f: mapped_record.get(f, f"AUTO_{i}") for f in key_fields}

            # Store record
            key_str = self._make_key(target_table, key)
            self._tables[target_table][key_str] = {
                **mapped_record,
                "_LOADED_AT": datetime.utcnow().isoformat(),
                "_BATCH_ID": f"{object_type}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            }
            records_loaded += 1

        # Generate reconciliation
        reconciliation = {
            "source_count": len(data),
            "target_count": records_loaded,
            "delta": len(data) - records_loaded,
            "reconciled": records_loaded == len(data),
            "reconciliation_time": datetime.utcnow().isoformat(),
        }

        result = DataLoadResult(
            success=records_failed == 0,
            object_type=object_type,
            records_total=len(data),
            records_loaded=records_loaded,
            records_failed=records_failed,
            errors=errors,
            reconciliation=reconciliation,
        )

        self._migrations[object_type] = result
        logger.info(
            f"Data load: {object_type} - loaded={records_loaded}, failed={records_failed}"
        )

        return result

    def call_api(
        self,
        endpoint: str,
        method: str = "GET",
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Simulate API call."""
        start_time = time.time()
        self._simulate_latency(50, 25)

        # Log API call
        call_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "endpoint": endpoint,
            "method": method,
            "params": params,
            "data": data,
        }
        self._api_calls.append(call_record)

        # Simulate failure
        if self._should_fail():
            duration = (time.time() - start_time) * 1000
            return APIResponse(
                status=APICallResult.ERROR,
                status_code=500,
                error_message="Simulated server error",
                duration_ms=duration,
            )

        # Check for predefined endpoints
        response_data = None
        status_code = 200

        if endpoint in self.API_ENDPOINTS:
            response_data = self.API_ENDPOINTS[endpoint]
        elif endpoint.startswith("/sap"):
            # Generic SAP endpoint simulation
            response_data = {
                "d": {
                    "results": [],
                    "__metadata": {"uri": endpoint, "type": "SAP.Entity"},
                }
            }
        else:
            status_code = 404
            return APIResponse(
                status=APICallResult.NOT_FOUND,
                status_code=404,
                error_message=f"Endpoint not found: {endpoint}",
                duration_ms=(time.time() - start_time) * 1000,
            )

        duration = (time.time() - start_time) * 1000
        return APIResponse(
            status=APICallResult.SUCCESS,
            status_code=status_code,
            data=response_data,
            duration_ms=duration,
        )

    def call_bapi(
        self,
        bapi: str,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Simulate BAPI call."""
        self._simulate_latency(100, 50)

        # Simulate common BAPIs
        bapi_responses = {
            "BAPI_COMPANYCODE_GETDETAIL": {
                "COMPANYCODE_DETAIL": {
                    "BUKRS": params.get("COMPANYCODE", "1000"),
                    "BUTXT": "Demo Company",
                    "WAERS": "EUR",
                },
                "RETURN": {"TYPE": "S", "MESSAGE": "Success"},
            },
            "BAPI_COSTCENTER_GETLIST": {
                "COSTCENTER_LIST": [],
                "RETURN": {"TYPE": "S", "MESSAGE": "Success"},
            },
            "BAPI_MATERIAL_GETLIST": {
                "MATNRLIST": [],
                "RETURN": {"TYPE": "S", "MESSAGE": "Success"},
            },
            "BAPI_TRANSACTION_COMMIT": {
                "RETURN": {"TYPE": "S", "MESSAGE": "Transaction committed"},
            },
        }

        if self._should_fail():
            return {
                "RETURN": {
                    "TYPE": "E",
                    "MESSAGE": "Simulated BAPI error",
                    "NUMBER": "999",
                }
            }

        return bapi_responses.get(bapi, {
            "RETURN": {"TYPE": "S", "MESSAGE": f"BAPI {bapi} executed"},
        })

    def get_state(self) -> Dict[str, Any]:
        """Get current adapter state."""
        return {
            "system_id": self.system_id,
            "client": self.client,
            "connected": self._connected,
            "operation_count": self._operation_count,
            "tables": {
                table: len(entries)
                for table, entries in self._tables.items()
                if entries
            },
            "api_calls": len(self._api_calls),
            "migrations": list(self._migrations.keys()),
        }

    def reset(self) -> None:
        """Reset adapter state."""
        self._tables = {table: {} for table in self.TABLE_DEFINITIONS}
        self._api_calls = []
        self._migrations = {}
        self._operation_count = 0
        logger.info(f"FakeSAP adapter reset: {self.system_id}")

    def export_state(self, path: Optional[str] = None) -> str:
        """Export current state to JSON file."""
        export_path = Path(path) if path else self.state_path
        if not export_path:
            export_path = Path(f"./fake_sap_state_{self.system_id}.json")

        state = {
            "metadata": {
                "system_id": self.system_id,
                "client": self.client,
                "exported_at": datetime.utcnow().isoformat(),
                "operation_count": self._operation_count,
            },
            "tables": self._tables,
            "api_calls": self._api_calls[-100:],  # Last 100 calls
            "migrations": {
                k: {
                    "success": v.success,
                    "records_total": v.records_total,
                    "records_loaded": v.records_loaded,
                    "records_failed": v.records_failed,
                }
                for k, v in self._migrations.items()
            },
        }

        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

        logger.info(f"State exported to: {export_path}")
        return str(export_path)

    def import_state(self, path: str) -> None:
        """Import state from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)

        self._tables = state.get("tables", {})
        self._api_calls = state.get("api_calls", [])
        logger.info(f"State imported from: {path}")


# Register adapter with factory
AdapterFactory.register("fake", FakeSAPAdapter)
