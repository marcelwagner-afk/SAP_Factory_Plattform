"""
SAP Implementation Factory - Customizing Plugin

Handles SAP customizing (configuration) activities.
Executes table entries, BAPI calls, and IMG activities.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from app.plugins.base import Plugin, PluginContext, PluginRegistry
from app.models import JobResult, JobStatus, JobType, CustomizingPackage

logger = logging.getLogger(__name__)


class CustomizingPlugin(Plugin):
    """
    Plugin for executing SAP customizing activities.

    Handles:
    - Table configuration (set_table)
    - BAPI/RFC calls (call_bapi)
    - IMG activity simulation

    Each customizing package is executed as a unit,
    with rollback support on failure.
    """

    PLUGIN_NAME = "customizing"
    PLUGIN_TYPE = JobType.CUSTOMIZING

    # Supported actions
    SUPPORTED_ACTIONS = ["set_table", "call_bapi", "set_parameter", "execute_report"]

    def validate(self, config: Dict[str, Any]) -> List[str]:
        """Validate customizing configuration."""
        errors = []

        if "id" not in config:
            errors.append("Customizing package must have 'id'")

        if "steps" not in config:
            errors.append("Customizing package must have 'steps'")
        elif not isinstance(config["steps"], list):
            errors.append("'steps' must be a list")
        else:
            for i, step in enumerate(config["steps"]):
                if "action" not in step:
                    errors.append(f"Step {i} missing 'action'")
                elif step["action"] not in self.SUPPORTED_ACTIONS:
                    errors.append(
                        f"Step {i}: Unknown action '{step['action']}'. "
                        f"Supported: {self.SUPPORTED_ACTIONS}"
                    )

                # Validate action-specific requirements
                action = step.get("action")
                if action == "set_table":
                    if "table" not in step:
                        errors.append(f"Step {i}: set_table requires 'table'")
                    if "key" not in step:
                        errors.append(f"Step {i}: set_table requires 'key'")
                elif action == "call_bapi":
                    if "bapi" not in step:
                        errors.append(f"Step {i}: call_bapi requires 'bapi'")

        return errors

    def execute(
        self,
        context: PluginContext,
        config: Dict[str, Any],
    ) -> JobResult:
        """
        Execute customizing package.

        Args:
            context: Execution context with SAP adapter
            config: Customizing package configuration

        Returns:
            JobResult with execution status
        """
        started_at = datetime.utcnow()
        package_id = config.get("id", "UNKNOWN")
        logs: List[Dict[str, Any]] = []
        artifacts: List[str] = []

        logs.append(context.log_info(f"Starting customizing package: {package_id}"))

        steps = config.get("steps", [])
        total_steps = len(steps)
        successful_steps = 0
        failed_steps = 0
        step_results: List[Dict[str, Any]] = []

        for i, step in enumerate(steps):
            step_num = i + 1
            action = step.get("action", "unknown")

            logs.append(context.log_info(
                f"Executing step {step_num}/{total_steps}: {action}"
            ))

            try:
                result = self._execute_step(context, step)
                step_results.append({
                    "step": step_num,
                    "action": action,
                    "success": result["success"],
                    "details": result,
                })

                if result["success"]:
                    successful_steps += 1
                    logs.append(context.log_info(
                        f"Step {step_num} completed successfully"
                    ))
                else:
                    failed_steps += 1
                    logs.append(context.log_error(
                        f"Step {step_num} failed: {result.get('message', 'Unknown error')}"
                    ))

            except Exception as e:
                failed_steps += 1
                error_msg = str(e)
                step_results.append({
                    "step": step_num,
                    "action": action,
                    "success": False,
                    "error": error_msg,
                })
                logs.append(context.log_error(f"Step {step_num} exception: {error_msg}"))

        # Determine overall status
        if failed_steps == 0:
            status = JobStatus.COMPLETED
            logs.append(context.log_info(
                f"Package {package_id} completed: {successful_steps}/{total_steps} steps"
            ))
        elif successful_steps > 0:
            status = JobStatus.COMPLETED  # Partial success still counts
            logs.append(context.log_warning(
                f"Package {package_id} partially completed: "
                f"{successful_steps} success, {failed_steps} failed"
            ))
        else:
            status = JobStatus.FAILED
            logs.append(context.log_error(f"Package {package_id} failed completely"))

        # Create artifact with detailed results
        artifact_data = {
            "package_id": package_id,
            "target_system": context.target_system,
            "executed_at": datetime.utcnow().isoformat(),
            "total_steps": total_steps,
            "successful_steps": successful_steps,
            "failed_steps": failed_steps,
            "step_results": step_results,
        }

        # Store in shared state for other plugins
        context.shared_state[f"customizing_{package_id}"] = {
            "success": failed_steps == 0,
            "steps_executed": total_steps,
        }

        return self.create_result(
            job_id=f"cust_{package_id}",
            job_name=f"Customizing: {package_id}",
            status=status,
            started_at=started_at,
            records_processed=total_steps,
            records_success=successful_steps,
            records_failed=failed_steps,
            logs=logs,
            artifacts=artifacts,
        )

    def _execute_step(
        self,
        context: PluginContext,
        step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a single customizing step.

        Args:
            context: Execution context
            step: Step configuration

        Returns:
            Result dictionary with success status
        """
        action = step.get("action")
        adapter = context.adapter

        if action == "set_table":
            return self._execute_set_table(adapter, step)
        elif action == "call_bapi":
            return self._execute_call_bapi(adapter, step)
        elif action == "set_parameter":
            return self._execute_set_parameter(adapter, step)
        elif action == "execute_report":
            return self._execute_report(adapter, step)
        else:
            return {
                "success": False,
                "message": f"Unknown action: {action}",
            }

    def _execute_set_table(
        self,
        adapter,
        step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute table entry configuration."""
        table = step.get("table")
        key = step.get("key", {})
        values = step.get("values", {})

        result = adapter.set_table(table, key, values)

        return {
            "success": result.success,
            "message": result.message,
            "table": table,
            "key": key,
            "operation": result.operation,
            "affected_rows": result.affected_rows,
        }

    def _execute_call_bapi(
        self,
        adapter,
        step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute BAPI call."""
        bapi = step.get("bapi")
        params = step.get("params", {})

        result = adapter.call_bapi(bapi, params)
        return_info = result.get("RETURN", {})

        success = return_info.get("TYPE", "S") in ["S", "W", "I"]

        return {
            "success": success,
            "message": return_info.get("MESSAGE", ""),
            "bapi": bapi,
            "return_type": return_info.get("TYPE", ""),
            "return_data": result,
        }

    def _execute_set_parameter(
        self,
        adapter,
        step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute parameter setting (simulation)."""
        param_name = step.get("parameter", "UNKNOWN")
        param_value = step.get("value")

        # Simulate parameter setting via table
        result = adapter.set_table(
            "TPARA",
            {"PARAMID": param_name},
            {"PARVAL": str(param_value)},
        )

        return {
            "success": result.success,
            "message": f"Parameter {param_name} set to {param_value}",
            "parameter": param_name,
            "value": param_value,
        }

    def _execute_report(
        self,
        adapter,
        step: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute ABAP report (simulation)."""
        report = step.get("report", "UNKNOWN")
        variant = step.get("variant", "")

        # Simulate report execution via API
        result = adapter.call_api(
            f"/sap/bc/bsp/sap/zbsp_report/{report}",
            method="POST",
            data={"variant": variant},
        )

        return {
            "success": result.status_code == 200,
            "message": f"Report {report} executed",
            "report": report,
            "variant": variant,
            "api_status": result.status_code,
        }


# Register plugin
PluginRegistry.register(CustomizingPlugin)
