"""
SAP Implementation Factory - Execution Planner

Creates execution plans from implementation models.
Determines job order, dependencies, and estimates.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List
import logging
import uuid

from app.models import (
    ImplementationModel,
    ExecutionPlan,
    JobDefinition,
    JobType,
)

logger = logging.getLogger(__name__)


class ExecutionPlanner:
    """
    Creates execution plans from implementation models.

    Responsibilities:
    - Analyze implementation model
    - Create ordered job list (Customizing -> Migration -> Testing)
    - Resolve dependencies
    - Estimate duration

    Execution Order (fixed):
    1. Customizing packages (in order defined)
    2. Migration objects (in order defined)
    3. Testing suites (in order defined)
    """

    # Estimated duration per job type (minutes)
    DURATION_ESTIMATES = {
        JobType.CUSTOMIZING: 5,  # Per package
        JobType.MIGRATION: 15,   # Per object
        JobType.TESTING: 10,     # Per suite
    }

    # Additional time per record estimate
    RECORDS_PER_MINUTE = {
        JobType.CUSTOMIZING: 100,  # Steps
        JobType.MIGRATION: 500,    # Records
        JobType.TESTING: 50,       # Test cases
    }

    def __init__(self):
        """Initialize planner."""
        self.logger = logging.getLogger(__name__)

    def create_plan(
        self,
        run_id: str,
        model: ImplementationModel,
    ) -> ExecutionPlan:
        """
        Create execution plan from implementation model.

        Args:
            run_id: Unique run identifier
            model: Validated implementation model

        Returns:
            ExecutionPlan with ordered jobs
        """
        jobs: List[JobDefinition] = []

        # Phase 1: Customizing Jobs
        customizing_jobs = self._create_customizing_jobs(model)
        jobs.extend(customizing_jobs)

        # Phase 2: Migration Jobs (depend on customizing)
        customizing_ids = [j.id for j in customizing_jobs]
        migration_jobs = self._create_migration_jobs(model, customizing_ids)
        jobs.extend(migration_jobs)

        # Phase 3: Testing Jobs (depend on migration)
        migration_ids = [j.id for j in migration_jobs]
        testing_jobs = self._create_testing_jobs(model, migration_ids)
        jobs.extend(testing_jobs)

        # Calculate estimates
        total_jobs = len(jobs)
        estimated_duration = self._estimate_duration(jobs, model)

        plan = ExecutionPlan(
            run_id=run_id,
            created_at=datetime.utcnow(),
            jobs=jobs,
            total_jobs=total_jobs,
            estimated_duration_minutes=estimated_duration,
        )

        self.logger.info(
            f"Created execution plan: {total_jobs} jobs, "
            f"estimated {estimated_duration} minutes"
        )

        return plan

    def _create_customizing_jobs(
        self,
        model: ImplementationModel,
    ) -> List[JobDefinition]:
        """Create jobs for customizing packages."""
        jobs = []
        previous_job_id = None

        for package in model.customizing.packages:
            job_id = f"cust_{package.id}_{uuid.uuid4().hex[:6]}"

            # Each package depends on the previous one (sequential)
            dependencies = [previous_job_id] if previous_job_id else []

            job = JobDefinition(
                id=job_id,
                type=JobType.CUSTOMIZING,
                name=f"Customizing: {package.id}",
                target_system=package.target,
                config={
                    "id": package.id,
                    "target": package.target,
                    "steps": [step.model_dump() for step in package.steps],
                    "description": package.description,
                },
                dependencies=dependencies,
            )
            jobs.append(job)
            previous_job_id = job_id

        self.logger.debug(f"Created {len(jobs)} customizing jobs")
        return jobs

    def _create_migration_jobs(
        self,
        model: ImplementationModel,
        dependencies: List[str],
    ) -> List[JobDefinition]:
        """Create jobs for migration objects."""
        jobs = []

        # All migrations depend on ALL customizing being complete
        base_dependencies = dependencies.copy()

        for obj in model.migration.objects:
            job_id = f"migr_{obj.id}_{uuid.uuid4().hex[:6]}"

            job = JobDefinition(
                id=job_id,
                type=JobType.MIGRATION,
                name=f"Migration: {obj.id}",
                target_system=obj.target,
                config={
                    "id": obj.id,
                    "source": obj.source,
                    "target": obj.target,
                    "mapping": obj.mapping,
                    "batch_size": obj.batch_size,
                    "validation_rules": obj.validation_rules,
                },
                dependencies=base_dependencies,
            )
            jobs.append(job)

        self.logger.debug(f"Created {len(jobs)} migration jobs")
        return jobs

    def _create_testing_jobs(
        self,
        model: ImplementationModel,
        dependencies: List[str],
    ) -> List[JobDefinition]:
        """Create jobs for test suites."""
        jobs = []

        # All tests depend on ALL migrations being complete
        base_dependencies = dependencies.copy()

        for suite in model.testing.suites:
            job_id = f"test_{suite.id}_{uuid.uuid4().hex[:6]}"

            job = JobDefinition(
                id=job_id,
                type=JobType.TESTING,
                name=f"Testing: {suite.id}",
                target_system=suite.target,
                config={
                    "id": suite.id,
                    "target": suite.target,
                    "cases": [case.model_dump() for case in suite.cases],
                    "description": suite.description,
                },
                dependencies=base_dependencies,
            )
            jobs.append(job)

        self.logger.debug(f"Created {len(jobs)} testing jobs")
        return jobs

    def _estimate_duration(
        self,
        jobs: List[JobDefinition],
        model: ImplementationModel,
    ) -> int:
        """
        Estimate total execution duration in minutes.

        Args:
            jobs: List of planned jobs
            model: Implementation model for additional context

        Returns:
            Estimated duration in minutes
        """
        total_minutes = 0

        for job in jobs:
            # Base time per job type
            base_time = self.DURATION_ESTIMATES.get(job.type, 5)

            # Additional time based on content
            if job.type == JobType.CUSTOMIZING:
                steps = len(job.config.get("steps", []))
                additional = steps / self.RECORDS_PER_MINUTE[job.type]
            elif job.type == JobType.MIGRATION:
                batch_size = job.config.get("batch_size", 100)
                additional = batch_size / self.RECORDS_PER_MINUTE[job.type]
            elif job.type == JobType.TESTING:
                cases = len(job.config.get("cases", []))
                additional = cases / self.RECORDS_PER_MINUTE[job.type]
            else:
                additional = 0

            total_minutes += base_time + additional

        # Add 10% buffer
        return int(total_minutes * 1.1)

    def get_job_order(self, plan: ExecutionPlan) -> List[str]:
        """
        Get topologically sorted job execution order.

        Args:
            plan: Execution plan

        Returns:
            List of job IDs in execution order
        """
        # Build dependency graph
        job_deps: Dict[str, List[str]] = {}
        for job in plan.jobs:
            job_deps[job.id] = job.dependencies.copy()

        # Topological sort (Kahn's algorithm)
        result = []
        available = [jid for jid, deps in job_deps.items() if not deps]

        while available:
            job_id = available.pop(0)
            result.append(job_id)

            # Remove this job from all dependencies
            for jid, deps in job_deps.items():
                if job_id in deps:
                    deps.remove(job_id)
                    if not deps and jid not in result and jid not in available:
                        available.append(jid)

        return result

    def estimate_manual_hours(self, model: ImplementationModel) -> float:
        """
        Estimate equivalent manual implementation hours.

        This is used to calculate cost savings from automation.

        Args:
            model: Implementation model

        Returns:
            Estimated manual hours
        """
        hours = 0.0

        # Customizing: ~2 hours per step (manual)
        for pkg in model.customizing.packages:
            hours += len(pkg.steps) * 2.0

        # Migration: ~4 hours per object (manual ETL)
        hours += len(model.migration.objects) * 4.0

        # Testing: ~1 hour per test case (manual)
        for suite in model.testing.suites:
            hours += len(suite.cases) * 1.0

        # Add project management overhead (20%)
        hours *= 1.2

        return round(hours, 1)


# Singleton instance
planner = ExecutionPlanner()


def get_planner() -> ExecutionPlanner:
    """Get planner instance."""
    return planner
