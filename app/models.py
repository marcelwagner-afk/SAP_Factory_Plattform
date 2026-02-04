"""
SAP Implementation Factory - Domain Models

Defines all Pydantic models for the implementation model, execution plans,
job results, and API responses. These models form the core data structures
that flow through the entire system.
"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


# =============================================================================
# ENUMS
# =============================================================================

class JobStatus(str, Enum):
    """Status of an individual job in the execution pipeline."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class RunStatus(str, Enum):
    """Overall status of an implementation run."""
    CREATED = "created"
    PLANNING = "planning"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Types of jobs that can be executed."""
    CUSTOMIZING = "customizing"
    MIGRATION = "migration"
    TESTING = "testing"


# =============================================================================
# IMPLEMENTATION MODEL (YAML -> Domain Model)
# =============================================================================

class SystemConfig(BaseModel):
    """SAP System configuration (DEV, QAS, PRD)."""
    id: str = Field(..., description="System identifier (e.g., DEV, QAS)")
    client: str = Field(..., description="SAP client number")
    description: Optional[str] = None


class LandscapeConfig(BaseModel):
    """System landscape configuration."""
    systems: List[SystemConfig] = Field(default_factory=list)


class CompanyCodeConfig(BaseModel):
    """Company code organizational unit."""
    code: str = Field(..., description="Company code (e.g., 1000)")
    currency: str = Field(default="EUR", description="Local currency")
    name: Optional[str] = None
    country: Optional[str] = None


class PlantConfig(BaseModel):
    """Plant organizational unit."""
    code: str = Field(..., description="Plant code")
    name: Optional[str] = None
    company_code: Optional[str] = None


class OrgConfig(BaseModel):
    """Organizational structure configuration."""
    company_codes: List[CompanyCodeConfig] = Field(default_factory=list)
    plants: List[PlantConfig] = Field(default_factory=list)


class ScopeConfig(BaseModel):
    """Implementation scope definition."""
    country: List[str] = Field(default_factory=lambda: ["DE"])
    modules: List[str] = Field(default_factory=lambda: ["FI", "MM"])
    org: OrgConfig = Field(default_factory=OrgConfig)


class CustomizingStep(BaseModel):
    """Single customizing step (table entry, configuration)."""
    action: str = Field(..., description="Action type: set_table, call_bapi, etc.")
    table: Optional[str] = None
    key: Optional[Dict[str, Any]] = None
    values: Optional[Dict[str, Any]] = None
    bapi: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class CustomizingPackage(BaseModel):
    """Package of customizing steps to be executed together."""
    id: str = Field(..., description="Package identifier")
    target: str = Field(default="DEV", description="Target system")
    description: Optional[str] = None
    steps: List[CustomizingStep] = Field(default_factory=list)


class CustomizingConfig(BaseModel):
    """Customizing configuration."""
    packages: List[CustomizingPackage] = Field(default_factory=list)


class MigrationObject(BaseModel):
    """Data migration object definition."""
    id: str = Field(..., description="Object identifier (e.g., BUSINESS_PARTNER)")
    source: str = Field(default="csv", description="Source type")
    target: str = Field(default="DEV", description="Target system")
    mapping: Dict[str, str] = Field(default_factory=dict)
    validation_rules: Optional[List[str]] = None
    batch_size: int = Field(default=1000)


class MigrationConfig(BaseModel):
    """Migration configuration."""
    objects: List[MigrationObject] = Field(default_factory=list)


class TestCase(BaseModel):
    """Individual test case definition."""
    id: str = Field(..., description="Test case identifier")
    type: str = Field(default="api", description="Test type: api, bapi, process")
    endpoint: Optional[str] = None
    method: Optional[str] = Field(default="GET")
    expected_status: Optional[int] = None
    expected_data: Optional[Dict[str, Any]] = None
    description: Optional[str] = None


class TestSuite(BaseModel):
    """Test suite containing multiple test cases."""
    id: str = Field(..., description="Suite identifier")
    target: str = Field(default="DEV", description="Target system")
    description: Optional[str] = None
    cases: List[TestCase] = Field(default_factory=list)


class TestingConfig(BaseModel):
    """Testing configuration."""
    suites: List[TestSuite] = Field(default_factory=list)


class ProjectConfig(BaseModel):
    """Project metadata."""
    name: str = Field(..., description="Project name")
    customer: str = Field(..., description="Customer identifier")
    template: Optional[str] = Field(default="STANDARD", description="Template ID")
    version: Optional[str] = Field(default="1.0.0")


class ImplementationModel(BaseModel):
    """
    Complete Implementation Model - Single Source of Truth

    This is the central model that drives the entire implementation.
    It is parsed from YAML and controls all phases: Customizing, Migration, Testing.
    """
    project: ProjectConfig
    landscape: LandscapeConfig = Field(default_factory=LandscapeConfig)
    scope: ScopeConfig = Field(default_factory=ScopeConfig)
    customizing: CustomizingConfig = Field(default_factory=CustomizingConfig)
    migration: MigrationConfig = Field(default_factory=MigrationConfig)
    testing: TestingConfig = Field(default_factory=TestingConfig)


# =============================================================================
# EXECUTION MODELS
# =============================================================================

class JobDefinition(BaseModel):
    """Definition of a job to be executed."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    type: JobType
    name: str
    target_system: str
    config: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """Planned execution sequence."""
    run_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    jobs: List[JobDefinition] = Field(default_factory=list)
    total_jobs: int = 0
    estimated_duration_minutes: int = 0


class JobResult(BaseModel):
    """Result of a single job execution."""
    job_id: str
    job_type: JobType
    job_name: str
    status: JobStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0
    records_processed: int = 0
    records_success: int = 0
    records_failed: int = 0
    error_message: Optional[str] = None
    artifacts: List[str] = Field(default_factory=list)
    kpis: Dict[str, Any] = Field(default_factory=dict)
    logs: List[Dict[str, Any]] = Field(default_factory=list)


class RunSummary(BaseModel):
    """Summary of an implementation run."""
    run_id: str
    project_name: str
    customer: str
    status: RunStatus
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0.0

    # Job statistics
    total_jobs: int = 0
    completed_jobs: int = 0
    failed_jobs: int = 0
    skipped_jobs: int = 0

    # Record statistics
    total_records: int = 0
    success_records: int = 0
    failed_records: int = 0

    # KPIs
    success_rate: float = 0.0
    automation_rate: float = 100.0  # All jobs are automated
    estimated_manual_hours: float = 0.0
    actual_hours: float = 0.0
    cost_savings_percent: float = 0.0

    # Results
    job_results: List[JobResult] = Field(default_factory=list)
    artifacts: List[str] = Field(default_factory=list)


# =============================================================================
# API MODELS
# =============================================================================

class RunCreateRequest(BaseModel):
    """Request to create a new implementation run."""
    config_yaml: str = Field(..., description="YAML configuration content")
    dry_run: bool = Field(default=False, description="Validate without executing")


class RunCreateResponse(BaseModel):
    """Response after creating a run."""
    run_id: str
    status: RunStatus
    message: str
    plan: Optional[ExecutionPlan] = None


class RunStatusResponse(BaseModel):
    """Response for run status query."""
    run_id: str
    status: RunStatus
    progress_percent: float = 0.0
    current_job: Optional[str] = None
    summary: Optional[RunSummary] = None


class ArtifactInfo(BaseModel):
    """Information about a generated artifact."""
    name: str
    path: str
    type: str
    size_bytes: int
    created_at: datetime


class ArtifactsResponse(BaseModel):
    """Response containing list of artifacts."""
    run_id: str
    artifacts: List[ArtifactInfo] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error response."""
    error: str
    detail: Optional[str] = None
    run_id: Optional[str] = None
