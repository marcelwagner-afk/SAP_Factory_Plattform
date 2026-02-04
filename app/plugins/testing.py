"""
SAP Implementation Factory - Testing Plugin

Handles automated testing activities including:
- API health checks
- BAPI/RFC testing
- Process smoke tests
- Integration validation
"""

from __future__ import annotations
import random
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from app.plugins.base import Plugin, PluginContext, PluginRegistry
from app.models import JobResult, JobStatus, JobType

logger = logging.getLogger(__name__)


class TestingPlugin(Plugin):
    """
    Plugin for executing automated tests.

    Handles:
    - API health checks (OData, REST)
    - BAPI/RFC function tests
    - Process smoke tests
    - Data validation tests

    Test results include:
    - Pass/fail status
    - Response times
    - Error details
    """

    PLUGIN_NAME = "testing"
    PLUGIN_TYPE = JobType.TESTING

    # Supported test types
    SUPPORTED_TYPES = ["api", "bapi", "process", "data", "integration"]

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate test suite configuration."""
        errors = []

        if "id" not in config:
            errors.append("Test suite must have 'id'")

        if "cases" not in config:
            errors.append("Test suite must have 'cases'")
        elif not isinstance(config["cases"], list):
            errors.append("'cases' must be a list")
        else:
            for i, case in enumerate(config["cases"]):
                if "id" not in case:
                    errors.append(f"Test case {i} missing 'id'")
                if "type" not in case:
                    errors.append(f"Test case {i} missing 'type'")
                elif case["type"] not in self.SUPPORTED_TYPES:
                    errors.append(
                        f"Test case {i}: Unknown type '{case['type']}'. "
                        f"Supported: {self.SUPPORTED_TYPES}"
                    )

        return errors

    def execute(
        self,
        context: PluginContext,
        config: Dict[str, Any],
    ) -> JobResult:
        """
        Execute test suite.

        Args:
            context: Execution context with SAP adapter
            config: Test suite configuration

        Returns:
            JobResult with test results
        """
        started_at = datetime.utcnow()
        suite_id = config.get("id", "UNKNOWN")
        logs: List[Dict[str, Any]] = []
        artifacts: List[str] = []

        logs.append(context.log_info(f"Starting test suite: {suite_id}"))

        cases = config.get("cases", [])
        total_tests = len(cases)
        passed_tests = 0
        failed_tests = 0
        test_results: List[Dict[str, Any]] = []

        for i, test_case in enumerate(cases):
            case_id = test_case.get("id", f"test_{i}")
            case_type = test_case.get("type", "api")

            logs.append(context.log_info(
                f"Running test {i + 1}/{total_tests}: {case_id} ({case_type})"
            ))

            try:
                result = self._execute_test_case(context, test_case)
                test_results.append({
                    "test_id": case_id,
                    "type": case_type,
                    "passed": result["passed"],
                    "duration_ms": result.get("duration_ms", 0),
                    "details": result,
                })

                if result["passed"]:
                    passed_tests += 1
                    logs.append(context.log_info(f"Test {case_id}: PASSED"))
                else:
                    failed_tests += 1
                    logs.append(context.log_error(
                        f"Test {case_id}: FAILED - {result.get('error', 'Unknown')}"
                    ))

            except Exception as e:
                failed_tests += 1
                error_msg = str(e)
                test_results.append({
                    "test_id": case_id,
                    "type": case_type,
                    "passed": False,
                    "error": error_msg,
                })
                logs.append(context.log_error(f"Test {case_id} exception: {error_msg}"))

        # Determine overall status
        if failed_tests == 0:
            status = JobStatus.COMPLETED
            logs.append(context.log_info(
                f"Test suite {suite_id} completed: {passed_tests}/{total_tests} passed"
            ))
        elif passed_tests > 0:
            status = JobStatus.COMPLETED
            logs.append(context.log_warning(
                f"Test suite {suite_id}: {passed_tests} passed, {failed_tests} failed"
            ))
        else:
            status = JobStatus.FAILED
            logs.append(context.log_error(f"Test suite {suite_id}: All tests failed"))

        # Store test results in shared state
        context.shared_state[f"testing_{suite_id}"] = {
            "passed": passed_tests,
            "failed": failed_tests,
            "total": total_tests,
            "pass_rate": round(
                (passed_tests / total_tests * 100) if total_tests > 0 else 0, 2
            ),
        }

        return self.create_result(
            job_id=f"test_{suite_id}",
            job_name=f"Testing: {suite_id}",
            status=status,
            started_at=started_at,
            records_processed=total_tests,
            records_success=passed_tests,
            records_failed=failed_tests,
            logs=logs,
            artifacts=artifacts,
        )

    def _execute_test_case(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a single test case.

        Args:
            context: Execution context
            test_case: Test case configuration

        Returns:
            Test result dictionary
        """
        case_type = test_case.get("type", "api")
        start_time = datetime.utcnow()

        if case_type == "api":
            result = self._test_api(context, test_case)
        elif case_type == "bapi":
            result = self._test_bapi(context, test_case)
        elif case_type == "process":
            result = self._test_process(context, test_case)
        elif case_type == "data":
            result = self._test_data(context, test_case)
        elif case_type == "integration":
            result = self._test_integration(context, test_case)
        else:
            result = {"passed": False, "error": f"Unknown test type: {case_type}"}

        end_time = datetime.utcnow()
        result["duration_ms"] = (end_time - start_time).total_seconds() * 1000

        return result

    def _test_api(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute API test."""
        endpoint = test_case.get("endpoint", "/sap/health")
        method = test_case.get("method", "GET")
        expected_status = test_case.get("expected_status", 200)
        expected_data = test_case.get("expected_data")

        response = context.adapter.call_api(
            endpoint=endpoint,
            method=method,
            params=test_case.get("params"),
            data=test_case.get("data"),
        )

        passed = response.status_code == expected_status

        # Check expected data if specified
        if passed and expected_data and response.data:
            for key, expected_value in expected_data.items():
                actual_value = response.data.get(key)
                if actual_value != expected_value:
                    passed = False
                    break

        return {
            "passed": passed,
            "endpoint": endpoint,
            "method": method,
            "expected_status": expected_status,
            "actual_status": response.status_code,
            "response_time_ms": response.duration_ms,
            "error": response.error_message if not passed else None,
        }

    def _test_bapi(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute BAPI test."""
        bapi = test_case.get("bapi", "BAPI_TRANSACTION_COMMIT")
        params = test_case.get("params", {})

        result = context.adapter.call_bapi(bapi, params)
        return_info = result.get("RETURN", {})

        # Check return type - S, W, I are success/warning/info
        return_type = return_info.get("TYPE", "S")
        passed = return_type in ["S", "W", "I"]

        return {
            "passed": passed,
            "bapi": bapi,
            "return_type": return_type,
            "return_message": return_info.get("MESSAGE", ""),
            "error": return_info.get("MESSAGE") if not passed else None,
        }

    def _test_process(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute process smoke test.

        Simulates end-to-end process validation.
        """
        process = test_case.get("process", "ORDER_TO_CASH")
        steps = test_case.get("steps", [])

        # Simulate process steps
        step_results = []
        all_passed = True

        # If no steps defined, create default process steps
        if not steps:
            steps = self._get_default_process_steps(process)

        for step in steps:
            # Simulate step execution with random success
            step_passed = random.random() > 0.05  # 95% success rate
            step_results.append({
                "step": step.get("name", "Step"),
                "passed": step_passed,
                "message": "OK" if step_passed else "Simulated failure",
            })
            if not step_passed:
                all_passed = False

        return {
            "passed": all_passed,
            "process": process,
            "steps_total": len(steps),
            "steps_passed": sum(1 for s in step_results if s["passed"]),
            "step_results": step_results,
        }

    def _test_data(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute data validation test."""
        table = test_case.get("table", "T001")
        expected_count = test_case.get("expected_count")
        expected_key = test_case.get("expected_key")

        # Query table
        data = context.adapter.get_table(table, key=expected_key)
        actual_count = len(data)

        passed = True
        errors = []

        # Check count if specified
        if expected_count is not None:
            if actual_count < expected_count:
                passed = False
                errors.append(
                    f"Expected at least {expected_count} records, found {actual_count}"
                )

        # Check key exists if specified
        if expected_key and not data:
            passed = False
            errors.append(f"Expected key {expected_key} not found")

        return {
            "passed": passed,
            "table": table,
            "expected_count": expected_count,
            "actual_count": actual_count,
            "errors": errors,
        }

    def _test_integration(
        self,
        context: PluginContext,
        test_case: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute integration test."""
        integration_name = test_case.get("name", "default_integration")
        source = test_case.get("source", "SAP")
        target = test_case.get("target", "External")

        # Simulate integration test with API calls
        api_result = context.adapter.call_api("/sap/health")

        passed = api_result.status_code == 200

        return {
            "passed": passed,
            "integration": integration_name,
            "source": source,
            "target": target,
            "connectivity": "OK" if passed else "FAILED",
            "latency_ms": api_result.duration_ms,
        }

    def _get_default_process_steps(self, process: str) -> List[Dict[str, Any]]:
        """Get default process steps for common processes."""
        process_steps = {
            "ORDER_TO_CASH": [
                {"name": "Create Sales Order"},
                {"name": "Check Availability"},
                {"name": "Create Delivery"},
                {"name": "Post Goods Issue"},
                {"name": "Create Invoice"},
                {"name": "Post Payment"},
            ],
            "PROCURE_TO_PAY": [
                {"name": "Create Purchase Requisition"},
                {"name": "Create Purchase Order"},
                {"name": "Goods Receipt"},
                {"name": "Invoice Verification"},
                {"name": "Payment Processing"},
            ],
            "RECORD_TO_REPORT": [
                {"name": "Post Journal Entry"},
                {"name": "Run Depreciation"},
                {"name": "Period Close"},
                {"name": "Generate Reports"},
            ],
            "HIRE_TO_RETIRE": [
                {"name": "Create Employee"},
                {"name": "Assign Position"},
                {"name": "Process Payroll"},
            ],
        }

        return process_steps.get(process, [
            {"name": "Initialize"},
            {"name": "Execute"},
            {"name": "Validate"},
        ])


# Register plugin
PluginRegistry.register(TestingPlugin)
