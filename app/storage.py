"""
SAP Implementation Factory - Storage Layer

Handles persistence of runs, artifacts, and state.
Uses JSON files for MVP - can be extended to SQLite or other backends.
"""

from __future__ import annotations
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import logging

from app.models import (
    RunSummary,
    RunStatus,
    ExecutionPlan,
    JobResult,
    ArtifactInfo,
)

logger = logging.getLogger(__name__)


class StorageManager:
    """
    Manages storage of runs, artifacts, and state.

    Directory structure:
    /artifacts/
        <run_id>/
            plan.json           - Execution plan
            state.json          - Current run state
            summary.json        - Final summary
            customizing/        - Customizing artifacts
            migration/          - Migration artifacts
            testing/            - Testing artifacts
    """

    def __init__(self, base_path: str = "./artifacts"):
        """Initialize storage manager with base path."""
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Storage initialized at: {self.base_path.absolute()}")

    def _run_path(self, run_id: str) -> Path:
        """Get path for a specific run."""
        return self.base_path / run_id

    def _ensure_run_dirs(self, run_id: str) -> Path:
        """Ensure all directories for a run exist."""
        run_path = self._run_path(run_id)
        subdirs = ["customizing", "migration", "testing"]
        for subdir in subdirs:
            (run_path / subdir).mkdir(parents=True, exist_ok=True)
        return run_path

    # =========================================================================
    # RUN MANAGEMENT
    # =========================================================================

    def create_run(self, run_id: str, project_name: str, customer: str) -> RunSummary:
        """Create a new run with initial state."""
        self._ensure_run_dirs(run_id)

        summary = RunSummary(
            run_id=run_id,
            project_name=project_name,
            customer=customer,
            status=RunStatus.CREATED,
            started_at=datetime.utcnow(),
        )

        self.save_summary(run_id, summary)
        logger.info(f"Created run: {run_id}")
        return summary

    def run_exists(self, run_id: str) -> bool:
        """Check if a run exists."""
        return self._run_path(run_id).exists()

    def get_all_runs(self) -> List[str]:
        """Get all run IDs."""
        if not self.base_path.exists():
            return []
        return [
            d.name for d in self.base_path.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        ]

    def delete_run(self, run_id: str) -> bool:
        """Delete a run and all its artifacts."""
        run_path = self._run_path(run_id)
        if run_path.exists():
            shutil.rmtree(run_path)
            logger.info(f"Deleted run: {run_id}")
            return True
        return False

    # =========================================================================
    # SUMMARY MANAGEMENT
    # =========================================================================

    def save_summary(self, run_id: str, summary: RunSummary) -> None:
        """Save run summary."""
        run_path = self._ensure_run_dirs(run_id)
        summary_path = run_path / "summary.json"
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(summary.model_dump(mode="json"), f, indent=2, default=str)
        logger.debug(f"Saved summary for run: {run_id}")

    def load_summary(self, run_id: str) -> Optional[RunSummary]:
        """Load run summary."""
        summary_path = self._run_path(run_id) / "summary.json"
        if not summary_path.exists():
            return None
        with open(summary_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return RunSummary(**data)

    def update_summary_status(
        self,
        run_id: str,
        status: RunStatus,
        current_job: Optional[str] = None,
    ) -> None:
        """Update run status in summary."""
        summary = self.load_summary(run_id)
        if summary:
            summary.status = status
            if status == RunStatus.COMPLETED or status == RunStatus.FAILED:
                summary.completed_at = datetime.utcnow()
                if summary.started_at:
                    delta = summary.completed_at - summary.started_at
                    summary.duration_seconds = delta.total_seconds()
            self.save_summary(run_id, summary)

    # =========================================================================
    # EXECUTION PLAN
    # =========================================================================

    def save_plan(self, run_id: str, plan: ExecutionPlan) -> str:
        """Save execution plan and return file path."""
        run_path = self._ensure_run_dirs(run_id)
        plan_path = run_path / "plan.json"
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan.model_dump(mode="json"), f, indent=2, default=str)
        logger.info(f"Saved execution plan for run: {run_id}")
        return str(plan_path)

    def load_plan(self, run_id: str) -> Optional[ExecutionPlan]:
        """Load execution plan."""
        plan_path = self._run_path(run_id) / "plan.json"
        if not plan_path.exists():
            return None
        with open(plan_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ExecutionPlan(**data)

    # =========================================================================
    # JOB RESULTS / ARTIFACTS
    # =========================================================================

    def save_job_result(
        self,
        run_id: str,
        job_type: str,
        job_name: str,
        result: JobResult,
    ) -> str:
        """
        Save job result as artifact.

        Args:
            run_id: Run identifier
            job_type: Type of job (customizing, migration, testing)
            job_name: Name/ID of the job
            result: Job result to save

        Returns:
            Path to saved artifact
        """
        run_path = self._ensure_run_dirs(run_id)
        artifact_dir = run_path / job_type
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Sanitize job name for filename
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in job_name)
        artifact_path = artifact_dir / f"{safe_name}.json"

        with open(artifact_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(mode="json"), f, indent=2, default=str)

        logger.debug(f"Saved job result: {artifact_path}")
        return str(artifact_path)

    def save_artifact(
        self,
        run_id: str,
        subdir: str,
        filename: str,
        content: Any,
    ) -> str:
        """
        Save arbitrary artifact content.

        Args:
            run_id: Run identifier
            subdir: Subdirectory (customizing, migration, testing)
            filename: Filename for the artifact
            content: Content to save (dict/list -> JSON, str -> text)

        Returns:
            Path to saved artifact
        """
        run_path = self._ensure_run_dirs(run_id)
        artifact_dir = run_path / subdir
        artifact_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = artifact_dir / filename

        if isinstance(content, (dict, list)):
            with open(artifact_path, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=2, default=str)
        else:
            with open(artifact_path, "w", encoding="utf-8") as f:
                f.write(str(content))

        logger.debug(f"Saved artifact: {artifact_path}")
        return str(artifact_path)

    def load_artifact(self, run_id: str, subdir: str, filename: str) -> Optional[Any]:
        """Load artifact content."""
        artifact_path = self._run_path(run_id) / subdir / filename
        if not artifact_path.exists():
            return None

        with open(artifact_path, "r", encoding="utf-8") as f:
            if filename.endswith(".json"):
                return json.load(f)
            return f.read()

    # =========================================================================
    # ARTIFACT LISTING
    # =========================================================================

    def list_artifacts(self, run_id: str) -> List[ArtifactInfo]:
        """List all artifacts for a run."""
        run_path = self._run_path(run_id)
        if not run_path.exists():
            return []

        artifacts = []

        def scan_directory(dir_path: Path, prefix: str = ""):
            """Recursively scan directory for artifacts."""
            if not dir_path.exists():
                return
            for item in dir_path.iterdir():
                if item.is_file() and item.suffix == ".json":
                    rel_path = f"{prefix}/{item.name}" if prefix else item.name
                    stat = item.stat()
                    artifacts.append(
                        ArtifactInfo(
                            name=item.name,
                            path=rel_path,
                            type=self._get_artifact_type(prefix or "root"),
                            size_bytes=stat.st_size,
                            created_at=datetime.fromtimestamp(stat.st_mtime),
                        )
                    )
                elif item.is_dir() and not item.name.startswith("."):
                    scan_directory(item, item.name)

        scan_directory(run_path)
        return sorted(artifacts, key=lambda a: a.path)

    def _get_artifact_type(self, prefix: str) -> str:
        """Determine artifact type from directory prefix."""
        type_map = {
            "root": "summary",
            "customizing": "customizing",
            "migration": "migration",
            "testing": "testing",
        }
        return type_map.get(prefix, "other")

    # =========================================================================
    # STATE MANAGEMENT (for resumability)
    # =========================================================================

    def save_state(self, run_id: str, state: Dict[str, Any]) -> None:
        """Save current execution state."""
        run_path = self._ensure_run_dirs(run_id)
        state_path = run_path / "state.json"
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)

    def load_state(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load execution state."""
        state_path = self._run_path(run_id) / "state.json"
        if not state_path.exists():
            return None
        with open(state_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_artifact_content(self, run_id: str, artifact_path: str) -> Optional[Any]:
        """Get content of a specific artifact by path."""
        full_path = self._run_path(run_id) / artifact_path
        if not full_path.exists():
            return None

        with open(full_path, "r", encoding="utf-8") as f:
            if full_path.suffix == ".json":
                return json.load(f)
            return f.read()


# Singleton instance for application-wide use
storage = StorageManager()


def get_storage() -> StorageManager:
    """Get the storage manager instance."""
    return storage
