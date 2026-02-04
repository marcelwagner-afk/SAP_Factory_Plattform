"""
SAP Implementation Factory - Migration Plugin

Handles data migration activities including:
- Data extraction and transformation
- SAP data loading
- Reconciliation and validation
"""

from __future__ import annotations
import random
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from app.plugins.base import Plugin, PluginContext, PluginRegistry
from app.models import JobResult, JobStatus, JobType

logger = logging.getLogger(__name__)


class MigrationPlugin(Plugin):
    """
    Plugin for executing data migration activities.

    Handles:
    - Source data extraction (CSV, database simulation)
    - Data transformation and mapping
    - SAP loading via adapter
    - Reconciliation report generation

    Supports various migration objects:
    - BUSINESS_PARTNER (CVI migration)
    - CUSTOMER, VENDOR (legacy migration)
    - MATERIAL, COST_CENTER, GL_ACCOUNT
    """

    PLUGIN_NAME = "migration"
    PLUGIN_TYPE = JobType.MIGRATION

    # Supported source types
    SUPPORTED_SOURCES = ["csv", "database", "legacy_sap", "excel"]

    # Object type to table mapping
    OBJECT_TABLE_MAP = {
        "BUSINESS_PARTNER": "BUT000",
        "CUSTOMER": "KNA1",
        "VENDOR": "LFA1",
        "MATERIAL": "MARA",
        "COST_CENTER": "CSKS",
        "PROFIT_CENTER": "CEPC",
        "GL_ACCOUNT": "SKA1",
        "COMPANY_CODE": "T001",
        "PLANT": "T001W",
    }

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate migration configuration."""
        errors = []

        if "id" not in config:
            errors.append("Migration object must have 'id'")

        source = config.get("source", "csv")
        if source not in self.SUPPORTED_SOURCES:
            errors.append(
                f"Unknown source '{source}'. Supported: {self.SUPPORTED_SOURCES}"
            )

        if "mapping" not in config:
            errors.append("Migration object must have 'mapping'")
        elif not isinstance(config["mapping"], dict):
            errors.append("'mapping' must be a dictionary")

        return errors

    def execute(
        self,
        context: PluginContext,
        config: Dict[str, Any],
    ) -> JobResult:
        """
        Execute data migration.

        Args:
            context: Execution context with SAP adapter
            config: Migration object configuration

        Returns:
            JobResult with migration status and reconciliation
        """
        started_at = datetime.utcnow()
        object_id = config.get("id", "UNKNOWN")
        logs: List[Dict[str, Any]] = []
        artifacts: List[str] = []

        logs.append(context.log_info(f"Starting migration: {object_id}"))

        try:
            # Step 1: Extract source data (simulated)
            logs.append(context.log_info(f"Extracting source data for {object_id}"))
            source_data = self._extract_source_data(config)
            total_records = len(source_data)
            logs.append(context.log_info(f"Extracted {total_records} records"))

            # Step 2: Transform data according to mapping
            logs.append(context.log_info("Transforming data with mapping"))
            transformed_data = self._transform_data(source_data, config)
            logs.append(context.log_info(f"Transformed {len(transformed_data)} records"))

            # Step 3: Validate data
            logs.append(context.log_info("Validating data"))
            validation_result = self._validate_data(transformed_data, config)
            if validation_result["errors"]:
                for error in validation_result["errors"][:5]:  # Log first 5 errors
                    logs.append(context.log_warning(f"Validation: {error}"))

            # Step 4: Load data into SAP
            logs.append(context.log_info(f"Loading data into {context.target_system}"))
            load_result = context.adapter.load_data(
                object_type=object_id,
                data=transformed_data,
                mapping=config.get("mapping", {}),
            )

            # Step 5: Generate reconciliation
            logs.append(context.log_info("Generating reconciliation report"))
            reconciliation = self._generate_reconciliation(
                source_count=total_records,
                load_result=load_result,
            )

            # Determine status
            if load_result.success:
                status = JobStatus.COMPLETED
                logs.append(context.log_info(
                    f"Migration {object_id} completed: "
                    f"{load_result.records_loaded}/{total_records} records loaded"
                ))
            elif load_result.records_loaded > 0:
                status = JobStatus.COMPLETED
                logs.append(context.log_warning(
                    f"Migration {object_id} partially completed: "
                    f"{load_result.records_loaded} loaded, "
                    f"{load_result.records_failed} failed"
                ))
            else:
                status = JobStatus.FAILED
                logs.append(context.log_error(f"Migration {object_id} failed"))

            # Store migration result in shared state
            context.shared_state[f"migration_{object_id}"] = {
                "success": load_result.success,
                "records_loaded": load_result.records_loaded,
                "records_failed": load_result.records_failed,
                "reconciliation": reconciliation,
            }

            return self.create_result(
                job_id=f"migr_{object_id}",
                job_name=f"Migration: {object_id}",
                status=status,
                started_at=started_at,
                records_processed=total_records,
                records_success=load_result.records_loaded,
                records_failed=load_result.records_failed,
                logs=logs,
                artifacts=artifacts,
            )

        except Exception as e:
            error_msg = str(e)
            logs.append(context.log_error(f"Migration error: {error_msg}"))

            return self.create_result(
                job_id=f"migr_{object_id}",
                job_name=f"Migration: {object_id}",
                status=JobStatus.FAILED,
                started_at=started_at,
                error_message=error_msg,
                logs=logs,
            )

    def _extract_source_data(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract/simulate source data.

        In a real implementation, this would read from CSV, database, etc.
        For the prototype, we generate sample data.
        """
        object_id = config.get("id", "UNKNOWN")
        source_type = config.get("source", "csv")
        batch_size = config.get("batch_size", 100)

        # Generate sample data based on object type
        data = []
        sample_size = min(batch_size, random.randint(50, 200))

        if object_id == "BUSINESS_PARTNER":
            data = self._generate_bp_data(sample_size)
        elif object_id == "CUSTOMER":
            data = self._generate_customer_data(sample_size)
        elif object_id == "VENDOR":
            data = self._generate_vendor_data(sample_size)
        elif object_id == "MATERIAL":
            data = self._generate_material_data(sample_size)
        elif object_id == "COST_CENTER":
            data = self._generate_cost_center_data(sample_size)
        elif object_id == "GL_ACCOUNT":
            data = self._generate_gl_account_data(sample_size)
        else:
            # Generic data
            data = [
                {"ID": f"REC{i:05d}", "NAME": f"Record {i}", "STATUS": "A"}
                for i in range(sample_size)
            ]

        return data

    def _generate_bp_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample Business Partner data."""
        bp_types = ["1", "2"]  # Organization, Person
        countries = ["DE", "AT", "CH"]
        return [
            {
                "BP_ID": f"BP{i:07d}",
                "NAME": f"Business Partner {i}",
                "TYPE": random.choice(bp_types),
                "COUNTRY": random.choice(countries),
                "CITY": f"City {i % 50}",
                "POSTAL_CODE": f"{10000 + i}",
            }
            for i in range(1, count + 1)
        ]

    def _generate_customer_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample Customer data."""
        countries = ["DE", "AT", "CH", "FR", "IT"]
        return [
            {
                "KUNNR": f"{i:010d}",
                "NAME1": f"Customer {i} GmbH",
                "LAND1": random.choice(countries),
                "ORT01": f"City {i % 30}",
                "PSTLZ": f"{20000 + i}",
                "KTOKD": "0001",
            }
            for i in range(1, count + 1)
        ]

    def _generate_vendor_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample Vendor data."""
        countries = ["DE", "CN", "US", "IT"]
        return [
            {
                "LIFNR": f"{i:010d}",
                "NAME1": f"Supplier {i} Ltd",
                "LAND1": random.choice(countries),
                "ORT01": f"Vendor City {i % 20}",
                "KTOKK": "0001",
            }
            for i in range(1, count + 1)
        ]

    def _generate_material_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample Material data."""
        mtypes = ["ROH", "HALB", "FERT", "HAWA"]
        return [
            {
                "MATNR": f"MAT{i:08d}",
                "MAKTX": f"Material Description {i}",
                "MTART": random.choice(mtypes),
                "MEINS": "ST",
                "MATKL": f"0{(i % 9) + 1}",
            }
            for i in range(1, count + 1)
        ]

    def _generate_cost_center_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample Cost Center data."""
        return [
            {
                "KOSTL": f"{1000 + i}",
                "KTEXT": f"Cost Center {i}",
                "KOSAR": "H",  # Hierarchical area
                "VERAK": f"Manager{i % 10}",
            }
            for i in range(1, count + 1)
        ]

    def _generate_gl_account_data(self, count: int) -> List[Dict[str, Any]]:
        """Generate sample GL Account data."""
        account_types = ["X", "S"]  # Balance sheet, P&L
        return [
            {
                "SAKNR": f"{100000 + i}",
                "TXT50": f"GL Account {i}",
                "XBILK": random.choice(account_types),
                "GVTYP": "01" if i % 2 == 0 else "02",
            }
            for i in range(1, count + 1)
        ]

    def _transform_data(
        self,
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """
        Transform source data using mapping.

        Args:
            data: Source data records
            config: Configuration with mapping

        Returns:
            Transformed data records
        """
        mapping = config.get("mapping", {})
        if not mapping:
            return data  # No transformation needed

        transformed = []
        for record in data:
            new_record = {}
            for source_field, target_field in mapping.items():
                if source_field in record:
                    new_record[target_field] = record[source_field]
            # Keep unmapped fields
            for key, value in record.items():
                if key not in mapping:
                    new_record[key] = value
            transformed.append(new_record)

        return transformed

    def _validate_data(
        self,
        data: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Validate data before loading.

        Args:
            data: Data to validate
            config: Configuration with validation rules

        Returns:
            Validation result with errors
        """
        errors = []
        validation_rules = config.get("validation_rules", [])

        # Basic validation
        for i, record in enumerate(data):
            # Check for empty required fields
            for key, value in record.items():
                if value is None or (isinstance(value, str) and not value.strip()):
                    if not key.startswith("_"):  # Skip internal fields
                        errors.append(f"Record {i}: Empty value for {key}")

        # Simulate some random validation errors
        if random.random() < 0.1:  # 10% chance of validation warning
            errors.append("Warning: Some records may have data quality issues")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "records_validated": len(data),
        }

    def _generate_reconciliation(
        self,
        source_count: int,
        load_result,
    ) -> Dict[str, Any]:
        """
        Generate reconciliation report.

        Args:
            source_count: Number of source records
            load_result: Result from data loading

        Returns:
            Reconciliation report
        """
        loaded = load_result.records_loaded
        failed = load_result.records_failed

        return {
            "source_system": {
                "name": "Legacy System",
                "record_count": source_count,
            },
            "target_system": {
                "name": "S/4HANA",
                "record_count": loaded,
            },
            "reconciliation": {
                "matched": loaded,
                "unmatched": source_count - loaded,
                "failed": failed,
                "match_rate_percent": round(
                    (loaded / source_count * 100) if source_count > 0 else 0, 2
                ),
            },
            "status": "RECONCILED" if loaded == source_count else "DISCREPANCY",
            "timestamp": datetime.utcnow().isoformat(),
        }


# Register plugin
PluginRegistry.register(MigrationPlugin)
