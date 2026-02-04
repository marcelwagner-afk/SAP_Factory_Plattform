"""
SAP Implementation Factory - FastAPI Application

Main entry point for the SAP Implementation Factory API.
Provides endpoints for running implementations and retrieving results.
"""

from __future__ import annotations
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import FastAPI, BackgroundTasks, HTTPException, status
from fastapi.responses import JSONResponse

from app.models import (
    RunCreateRequest,
    RunCreateResponse,
    RunStatusResponse,
    ArtifactsResponse,
    ErrorResponse,
    RunStatus,
    RunSummary,
)
from app.engine.parser import ConfigParser, ParserError
from app.engine.planner import ExecutionPlanner
from app.engine.executor import JobExecutor, create_executor
from app.storage import StorageManager, get_storage

# Import plugins and adapters to register them
from app.plugins import CustomizingPlugin, MigrationPlugin, TestingPlugin
from app.adapters import FakeSAPAdapter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# =============================================================================
# APPLICATION SETUP
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("SAP Implementation Factory starting...")
    logger.info(f"Storage path: {get_storage().base_path.absolute()}")
    yield
    # Shutdown
    logger.info("SAP Implementation Factory shutting down...")


app = FastAPI(
    title="SAP Implementation Factory",
    description="""
    ## Fully Automated SAP S/4HANA Implementation Platform

    This API provides endpoints for:
    - **Creating implementation runs** from YAML configuration
    - **Monitoring execution status** in real-time
    - **Retrieving artifacts** (customizing, migration, testing results)

    ### Key Features
    - Model-driven implementation (YAML as Single Source of Truth)
    - Plugin-based execution engine
    - Automated customizing, migration, and testing
    - Evidence generation for governance

    ### Execution Flow
    1. Submit YAML configuration via POST /runs
    2. Engine parses config, creates plan, executes jobs
    3. Monitor progress via GET /runs/{run_id}
    4. Retrieve artifacts via GET /runs/{run_id}/artifacts
    """,
    version="1.0.0",
    lifespan=lifespan,
)

# Global state for tracking active runs
active_runs: Dict[str, Dict[str, Any]] = {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def generate_run_id() -> str:
    """Generate unique run ID."""
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    unique = uuid.uuid4().hex[:6]
    return f"run_{timestamp}_{unique}"


async def execute_run_async(
    run_id: str,
    yaml_content: str,
    storage: StorageManager,
) -> None:
    """
    Execute implementation run asynchronously.

    This runs in a background task to not block the API response.
    """
    try:
        # Update status
        active_runs[run_id]["status"] = RunStatus.PLANNING
        active_runs[run_id]["message"] = "Parsing configuration..."

        # Parse configuration
        parser = ConfigParser()
        model = parser.parse(yaml_content)

        # Create run in storage
        storage.create_run(
            run_id=run_id,
            project_name=model.project.name,
            customer=model.project.customer,
        )

        # Create execution plan
        active_runs[run_id]["message"] = "Creating execution plan..."
        planner = ExecutionPlanner()
        plan = planner.create_plan(run_id, model)

        # Save plan
        storage.save_plan(run_id, plan)
        active_runs[run_id]["plan"] = plan

        # Update status
        active_runs[run_id]["status"] = RunStatus.EXECUTING
        active_runs[run_id]["message"] = "Executing jobs..."
        active_runs[run_id]["total_jobs"] = plan.total_jobs

        # Create executor with progress callback
        executor = create_executor(storage=storage, adapter_type="fake")

        def progress_callback(rid: str, percent: int, current_job: str):
            if rid in active_runs:
                active_runs[rid]["progress_percent"] = percent
                active_runs[rid]["current_job"] = current_job

        executor.set_progress_callback(progress_callback)

        # Execute (this is the long-running part)
        # Run in thread pool to not block event loop
        loop = asyncio.get_event_loop()
        summary = await loop.run_in_executor(
            None,
            lambda: executor.execute(run_id, plan, model),
        )

        # Update final status
        active_runs[run_id]["status"] = summary.status
        active_runs[run_id]["summary"] = summary
        active_runs[run_id]["message"] = "Execution completed"
        active_runs[run_id]["progress_percent"] = 100

        logger.info(f"Run {run_id} completed: {summary.status}")

    except ParserError as e:
        logger.error(f"Run {run_id} parsing failed: {e.message}")
        active_runs[run_id]["status"] = RunStatus.FAILED
        active_runs[run_id]["message"] = f"Configuration error: {e.message}"
        active_runs[run_id]["errors"] = e.errors

    except Exception as e:
        logger.exception(f"Run {run_id} failed: {str(e)}")
        active_runs[run_id]["status"] = RunStatus.FAILED
        active_runs[run_id]["message"] = f"Execution error: {str(e)}"


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/", tags=["Health"])
async def root():
    """Root endpoint with API information."""
    return {
        "name": "SAP Implementation Factory",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "create_run": "POST /runs",
            "get_status": "GET /runs/{run_id}",
            "get_artifacts": "GET /runs/{run_id}/artifacts",
            "list_runs": "GET /runs",
        },
    }


@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_runs": len([r for r in active_runs.values() if r["status"] == RunStatus.EXECUTING]),
    }


@app.post(
    "/runs",
    response_model=RunCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Runs"],
    summary="Create and start a new implementation run",
)
async def create_run(
    request: RunCreateRequest,
    background_tasks: BackgroundTasks,
) -> RunCreateResponse:
    """
    Create and start a new SAP implementation run.

    The run executes asynchronously. Use GET /runs/{run_id} to monitor progress.

    **Request Body:**
    - `config_yaml`: YAML configuration string (see example_project.yaml)
    - `dry_run`: If true, validates config without executing (default: false)

    **Returns:**
    - `run_id`: Unique identifier for the run
    - `status`: Initial status (created/planning)
    - `message`: Status message
    - `plan`: Execution plan (if dry_run)
    """
    run_id = generate_run_id()
    storage = get_storage()

    # Validate configuration first
    try:
        parser = ConfigParser()
        model = parser.parse(request.config_yaml)
    except ParserError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": "Configuration validation failed",
                "message": e.message,
                "errors": e.errors,
            },
        )

    # For dry run, just return the plan
    if request.dry_run:
        planner = ExecutionPlanner()
        plan = planner.create_plan(run_id, model)

        return RunCreateResponse(
            run_id=run_id,
            status=RunStatus.CREATED,
            message="Dry run - configuration validated successfully",
            plan=plan,
        )

    # Initialize run state
    active_runs[run_id] = {
        "status": RunStatus.CREATED,
        "message": "Run created, starting execution...",
        "progress_percent": 0,
        "current_job": None,
        "total_jobs": 0,
        "created_at": datetime.utcnow().isoformat(),
    }

    # Start background execution
    background_tasks.add_task(
        execute_run_async,
        run_id,
        request.config_yaml,
        storage,
    )

    logger.info(f"Run created: {run_id} for project {model.project.name}")

    return RunCreateResponse(
        run_id=run_id,
        status=RunStatus.CREATED,
        message=f"Run created for project: {model.project.name}",
    )


@app.get(
    "/runs/{run_id}",
    response_model=RunStatusResponse,
    tags=["Runs"],
    summary="Get run status and progress",
)
async def get_run_status(run_id: str) -> RunStatusResponse:
    """
    Get the current status of an implementation run.

    **Returns:**
    - `run_id`: Run identifier
    - `status`: Current status (created/planning/executing/completed/failed)
    - `progress_percent`: Execution progress (0-100)
    - `current_job`: Name of currently executing job
    - `summary`: Full summary (when completed)
    """
    # Check active runs first
    if run_id in active_runs:
        run_state = active_runs[run_id]
        return RunStatusResponse(
            run_id=run_id,
            status=run_state["status"],
            progress_percent=run_state.get("progress_percent", 0),
            current_job=run_state.get("current_job"),
            summary=run_state.get("summary"),
        )

    # Check storage
    storage = get_storage()
    summary = storage.load_summary(run_id)

    if summary is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )

    return RunStatusResponse(
        run_id=run_id,
        status=summary.status,
        progress_percent=100 if summary.status in [RunStatus.COMPLETED, RunStatus.FAILED] else 0,
        summary=summary,
    )


@app.get(
    "/runs/{run_id}/artifacts",
    response_model=ArtifactsResponse,
    tags=["Runs"],
    summary="List artifacts generated by a run",
)
async def get_artifacts(run_id: str) -> ArtifactsResponse:
    """
    Get list of artifacts generated by an implementation run.

    Artifacts include:
    - `plan.json`: Execution plan
    - `customizing/*.json`: Customizing job results
    - `migration/*.json`: Migration job results with reconciliation
    - `testing/*.json`: Test suite results
    - `summary.json`: Final execution summary
    """
    storage = get_storage()

    if not storage.run_exists(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )

    artifacts = storage.list_artifacts(run_id)

    return ArtifactsResponse(
        run_id=run_id,
        artifacts=artifacts,
    )


@app.get(
    "/runs/{run_id}/artifacts/{artifact_path:path}",
    tags=["Runs"],
    summary="Get specific artifact content",
)
async def get_artifact_content(run_id: str, artifact_path: str):
    """
    Get the content of a specific artifact.

    **Path Parameters:**
    - `run_id`: Run identifier
    - `artifact_path`: Path to artifact (e.g., "customizing/FI_CORE.json")
    """
    storage = get_storage()

    if not storage.run_exists(run_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )

    content = storage.get_artifact_content(run_id, artifact_path)

    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Artifact not found: {artifact_path}",
        )

    return content


@app.get(
    "/runs",
    tags=["Runs"],
    summary="List all runs",
)
async def list_runs():
    """
    List all implementation runs.

    Returns a list of run IDs with their current status.
    """
    storage = get_storage()
    run_ids = storage.get_all_runs()

    runs = []
    for run_id in run_ids:
        # Check active state first
        if run_id in active_runs:
            runs.append({
                "run_id": run_id,
                "status": active_runs[run_id]["status"],
                "progress_percent": active_runs[run_id].get("progress_percent", 0),
            })
        else:
            # Load from storage
            summary = storage.load_summary(run_id)
            if summary:
                runs.append({
                    "run_id": run_id,
                    "status": summary.status,
                    "project_name": summary.project_name,
                    "customer": summary.customer,
                    "completed_at": summary.completed_at.isoformat() if summary.completed_at else None,
                })

    return {"runs": runs, "total": len(runs)}


@app.delete(
    "/runs/{run_id}",
    tags=["Runs"],
    summary="Delete a run and its artifacts",
)
async def delete_run(run_id: str):
    """
    Delete an implementation run and all its artifacts.

    **Warning:** This action cannot be undone.
    """
    # Cannot delete running jobs
    if run_id in active_runs:
        run_state = active_runs[run_id]
        if run_state["status"] == RunStatus.EXECUTING:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a running execution",
            )
        del active_runs[run_id]

    storage = get_storage()
    if storage.delete_run(run_id):
        return {"message": f"Run {run_id} deleted successfully"}
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run not found: {run_id}",
        )


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    """Global exception handler."""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal server error",
            "detail": str(exc),
        },
    )


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info",
    )
