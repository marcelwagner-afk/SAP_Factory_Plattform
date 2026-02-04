"""
SAP Implementation Factory - Job Executor

Executes jobs from execution plans using plugins and adapters.
Handles sequential execution, error handling, and artifact generation.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
import logging

from app.models import (
    ImplementationModel,
    ExecutionPlan,
    JobDefinition,
    JobResult,
    JobStatus,
    JobType,
    RunSummary,
    RunStatus,
)
from app.plugins.base import Plugin, PluginContext, PluginRegistry
from app.adapters.base import SAPAdapter, AdapterFactory
from app.storage import StorageManager

logger = logging.getLogger(__name__)


class ExecutionError(Exception):
    """Exception raised during job execution."""

    def __init__(self, message: str, job_id: str, original_error: Optional[Exception] = None):
        self.message = message
        self.job_id = job_id
        self.original_error = original_error
        super().__init__(self.message)


class JobExecutor:
    """
    Executes jobs from execution plans.

    Responsibilities:
    - Execute jobs sequentially in planned order
    - Manage adapter connections
    - Route jobs to appropriate plugins
    - Handle errors and stop on failure
    - Generate artifacts and summary

    Error Handling:
    - Each job is wrapped in try/except
    - Failed jobs stop the pipeline
    - All results are captured regardless of status
    """

    def __init__(
        self,
        storage: StorageManager,
        adapter_type: str = "fake",
    ):
        """
        Initialize executor.

        Args:
            storage: Storage manager for artifacts
            adapter_type: Type of SAP adapter to use
        """
        self.storage = storage
        self.adapter_type = adapter_type
        self.logger = logging.getLogger(__name__)

        # Execution state
        self._adapters: Dict[str, SAPAdapter] = {}
        self._plugins: Dict[JobType, Plugin] = {}
        self._current_run: Optional[str] = None
        self._progress_callback: Optional[Callable] = None

    def set_progress_callback(self, callback: Callable[[str, int, str], None]) -> None:
        """
        Set callback for progress updates.

        Args:
            callback: Function(run_id, percent, current_job)
        """
        self._progress_callback = callback

    def _report_progress(self, run_id: str, percent: int, current_job: str) -> None:
        """Report progress via callback if set."""
        if self._progress_callback:
            self._progress_callback(run_id, percent, current_job)

    def execute(
        self,
        run_id: str,
        plan: ExecutionPlan,
        model: ImplementationModel,
    ) -> RunSummary:
        """
        Execute an implementation run.

        Args:
            run_id: Unique run identifier
            plan: Execution plan with jobs
            model: Implementation model

        Returns:
            RunSummary with results
        """
        self._current_run = run_id
        started_at = datetime.utcnow()

        # Initialize summary
        summary = RunSummary(
            run_id=run_id,
            project_name=model.project.name,
            customer=model.project.customer,
            status=RunStatus.EXECUTING,
            started_at=started_at,
            total_jobs=plan.total_jobs,
        )

        self.logger.info(f"Starting execution: {run_id} with {plan.total_jobs} jobs")

        # Initialize plugins
        self._initialize_plugins()

        # Initialize adapters for all target systems
        systems = {job.target_system for job in plan.jobs}
        for system_id in systems:
            self._get_or_create_adapter(system_id, model)

        # Execute jobs
        job_results: List[JobResult] = []
        completed = 0
        failed = 0
        skipped = 0
        stop_execution = False

        for i, job in enumerate(plan.jobs):
            # Report progress
            percent = int((i / plan.total_jobs) * 100)
            self._report_progress(run_id, percent, job.name)

            if stop_execution:
                # Skip remaining jobs after failure
                result = JobResult(
                    job_id=job.id,
                    job_type=job.type,
                    job_name=job.name,
                    status=JobStatus.SKIPPED,
                    error_message="Skipped due to previous failure",
                )
                job_results.append(result)
                skipped += 1
                continue

            # Execute job
            self.logger.info(f"Executing job {i + 1}/{plan.total_jobs}: {job.name}")

            try:
                result = self._execute_job(job, model, run_id)
                job_results.append(result)

                # Save artifact
                artifact_path = self.storage.save_job_result(
                    run_id=run_id,
                    job_type=job.type.value,
                    job_name=job.config.get("id", job.id),
                    result=result,
                )
                result.artifacts.append(artifact_path)

                if result.status == JobStatus.COMPLETED:
                    completed += 1
                    self.logger.info(f"Job completed: {job.name}")
                else:
                    failed += 1
                    stop_execution = True
                    self.logger.error(f"Job failed: {job.name} - {result.error_message}")

            except Exception as e:
                self.logger.exception(f"Job execution error: {job.name}")
                result = JobResult(
                    job_id=job.id,
                    job_type=job.type,
                    job_name=job.name,
                    status=JobStatus.FAILED,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    error_message=str(e),
                )
                job_results.append(result)
                failed += 1
                stop_execution = True

        # Finalize summary
        completed_at = datetime.utcnow()
        duration = (completed_at - started_at).total_seconds()

        # Calculate totals
        total_records = sum(r.records_processed for r in job_results)
        success_records = sum(r.records_success for r in job_results)
        failed_records = sum(r.records_failed for r in job_results)

        summary.completed_at = completed_at
        summary.duration_seconds = duration
        summary.completed_jobs = completed
        summary.failed_jobs = failed
        summary.skipped_jobs = skipped
        summary.total_records = total_records
        summary.success_records = success_records
        summary.failed_records = failed_records
        summary.job_results = job_results

        # Calculate KPIs
        summary.success_rate = (
            (completed / plan.total_jobs * 100) if plan.total_jobs > 0 else 0
        )
        summary.automation_rate = 100.0  # All jobs are automated

        # Estimate manual hours and savings
        from app.engine.planner import get_planner
        planner = get_planner()
        manual_hours = planner.estimate_manual_hours(model)
        actual_hours = duration / 3600

        summary.estimated_manual_hours = manual_hours
        summary.actual_hours = round(actual_hours, 2)
        summary.cost_savings_percent = (
            round((1 - actual_hours / manual_hours) * 100, 1)
            if manual_hours > 0 else 0
        )

        # Determine final status
        if failed == 0 and skipped == 0:
            summary.status = RunStatus.COMPLETED
        else:
            summary.status = RunStatus.FAILED

        # Collect artifact paths
        summary.artifacts = [
            artifact
            for result in job_results
            for artifact in result.artifacts
        ]

        # Save final summary
        self.storage.save_summary(run_id, summary)
        self.storage.save_artifact(
            run_id=run_id,
            subdir="",
            filename="summary.json",
            content=summary.model_dump(mode="json"),
        )

        # Report completion
        self._report_progress(run_id, 100, "Complete")
        self.logger.info(
            f"Execution completed: {run_id} - "
            f"{completed}/{plan.total_jobs} jobs, "
            f"{summary.cost_savings_percent}% cost savings"
        )

        # Cleanup
        self._cleanup()

        return summary

    def _initialize_plugins(self) -> None:
        """Initialize all required plugins."""
        self._plugins = {
            JobType.CUSTOMIZING: PluginRegistry.get_by_type(JobType.CUSTOMIZING),
            JobType.MIGRATION: PluginRegistry.get_by_type(JobType.MIGRATION),
            JobType.TESTING: PluginRegistry.get_by_type(JobType.TESTING),
        }

        # Verify all plugins loaded
        for job_type, plugin in self._plugins.items():
            if plugin is None:
                raise ExecutionError(
                    f"Plugin not found for job type: {job_type}",
                    job_id="init",
                )
        self.logger.debug("Plugins initialized")

    def _get_or_create_adapter(
        self,
        system_id: str,
        model: ImplementationModel,
    ) -> SAPAdapter:
        """Get or create adapter for a system."""
        if system_id in self._adapters:
            return self._adapters[system_id]

        # Find client from landscape
        client = "100"  # Default
        for system in model.landscape.systems:
            if system.id == system_id:
                client = system.client
                break

        # Create adapter
        adapter = AdapterFactory.create(
            adapter_type=self.adapter_type,
            system_id=system_id,
            client=client,
        )
        adapter.connect()

        self._adapters[system_id] = adapter
        self.logger.debug(f"Created adapter for system: {system_id}")

        return adapter

    def _execute_job(
        self,
        job: JobDefinition,
        model: ImplementationModel,
        run_id: str,
    ) -> JobResult:
        """
        Execute a single job.

        Args:
            job: Job definition
            model: Implementation model
            run_id: Current run ID

        Returns:
            JobResult with execution outcome
        """
        # Get plugin
        plugin = self._plugins.get(job.type)
        if not plugin:
            return JobResult(
                job_id=job.id,
                job_type=job.type,
                job_name=job.name,
                status=JobStatus.FAILED,
                error_message=f"No plugin for job type: {job.type}",
            )

        # Get adapter
        adapter = self._adapters.get(job.target_system)
        if not adapter:
            return JobResult(
                job_id=job.id,
                job_type=job.type,
                job_name=job.name,
                status=JobStatus.FAILED,
                error_message=f"No adapter for system: {job.target_system}",
            )

        # Find client
        client = "100"
        for system in model.landscape.systems:
            if system.id == job.target_system:
                client = system.client
                break

        # Create context
        context = PluginContext(
            run_id=run_id,
            adapter=adapter,
            artifacts_path=str(self.storage._run_path(run_id)),
            project_name=model.project.name,
            customer=model.project.customer,
            target_system=job.target_system,
            client=client,
        )

        # Validate configuration
        validation_errors = plugin.validate(job.config)
        if validation_errors:
            return JobResult(
                job_id=job.id,
                job_type=job.type,
                job_name=job.name,
                status=JobStatus.FAILED,
                error_message=f"Validation failed: {'; '.join(validation_errors)}",
            )

        # Execute plugin
        result = plugin.execute(context, job.config)

        return result

    def _cleanup(self) -> None:
        """Cleanup resources after execution."""
        # Disconnect adapters
        for system_id, adapter in self._adapters.items():
            try:
                adapter.disconnect()
            except Exception as e:
                self.logger.warning(f"Error disconnecting adapter {system_id}: {e}")

        self._adapters.clear()
        self._current_run = None
        self.logger.debug("Executor cleanup complete")


# Factory function
def create_executor(
    storage: StorageManager,
    adapter_type: str = "fake",
) -> JobExecutor:
    """
    Create a job executor instance.

    Args:
        storage: Storage manager
        adapter_type: Type of SAP adapter

    Returns:
        Configured JobExecutor
    """
    return JobExecutor(storage=storage, adapter_type=adapter_type)
