"""Optional FastAPI server for running the AIPM pipeline via HTTP."""

from __future__ import annotations

import json
import logging
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from aipm.core.orchestrator import PipelineOrchestrator
from aipm.schemas.config import RunConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(title="AIPM - Autonomous AI Product Manager", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory run state store
# ---------------------------------------------------------------------------

_RunStatus = Literal["running", "completed", "failed"]

_runs: dict[str, dict] = {}
# Shape of each entry:
# {
#     "run_id": str,
#     "status": _RunStatus,
#     "agents_completed": list[str],
#     "current_agent": str,
#     "manifest": dict | None,
#     "error": str | None,
#     "run_dir": str,
# }


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    """JSON body for starting a pipeline run from a text prompt."""

    prompt: str = Field(..., description="Product idea or feature description as free text")
    provider: Literal["openai"] = Field(default="openai", description="LLM provider to use")
    model: str = Field(default="gpt-4o", description="Model identifier")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="LLM sampling temperature")
    policy_path: str = Field(default="src/aipm/policies/default_policy.yaml", description="Path to policy YAML")
    output_dir: str = Field(default="output", description="Base output directory")


class RunStartedResponse(BaseModel):
    """Returned immediately after a run is accepted."""

    run_id: str
    status: Literal["started"] = "started"


class RunStatusResponse(BaseModel):
    """Current status of a pipeline run."""

    run_id: str
    status: _RunStatus
    agents_completed: list[str]
    current_agent: str


class ArtifactLink(BaseModel):
    """Metadata for a single generated artifact."""

    name: str
    download_url: str


class ArtifactsResponse(BaseModel):
    """List of artifacts available for a completed run."""

    run_id: str
    artifacts: list[ArtifactLink]


class HealthResponse(BaseModel):
    """API health check response."""

    status: str
    version: str


# ---------------------------------------------------------------------------
# Background pipeline runner
# ---------------------------------------------------------------------------


async def _run_pipeline(run_id: str, input_path: str, run_config: RunConfig) -> None:
    """Execute the pipeline in the background and update run state."""
    _runs[run_id]["current_agent"] = "intake"
    try:
        orchestrator = PipelineOrchestrator(run_config)
        manifest = await orchestrator.run(input_path)

        _runs[run_id]["status"] = "completed"
        _runs[run_id]["agents_completed"] = manifest.get("agents_run", [])
        _runs[run_id]["current_agent"] = ""
        _runs[run_id]["manifest"] = manifest

        # Resolve the run_dir from the orchestrator's output
        run_dir = Path(run_config.output_dir) / run_id
        _runs[run_id]["run_dir"] = str(run_dir)

        logger.info("Pipeline completed for run_id=%s", run_id)
    except Exception as exc:
        logger.error("Pipeline failed for run_id=%s: %s", run_id, exc)
        _runs[run_id]["status"] = "failed"
        _runs[run_id]["current_agent"] = ""
        _runs[run_id]["error"] = str(exc)


def _start_run(
    background_tasks: BackgroundTasks,
    input_path: str,
    provider: str = "openai",
    model: str = "gpt-4o",
    temperature: float = 0.2,
    policy_path: str = "src/aipm/policies/default_policy.yaml",
    output_dir: str = "output",
) -> str:
    """Register a new run in the state store and enqueue the background task."""
    run_id = str(uuid.uuid4())
    run_config = RunConfig(
        run_id=run_id,
        input_path=input_path,
        output_dir=output_dir,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        temperature=temperature,
        policy_path=policy_path,
    )
    _runs[run_id] = {
        "run_id": run_id,
        "status": "running",
        "agents_completed": [],
        "current_agent": "initializing",
        "manifest": None,
        "error": None,
        "run_dir": str(Path(output_dir) / run_id),
    }
    background_tasks.add_task(_run_pipeline, run_id, input_path, run_config)
    return run_id


def _get_run_or_404(run_id: str) -> dict:
    """Return the run state dict or raise 404."""
    run = _runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")
    return run


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.post("/api/v1/run", response_model=RunStartedResponse, status_code=202)
async def start_run(
    background_tasks: BackgroundTasks,
    body: RunRequest | None = None,
    file: UploadFile | None = None,
) -> RunStartedResponse:
    """Start a pipeline run from a JSON prompt or a zip bundle upload.

    Accepts **either** a JSON body `{prompt: str, ...}` **or** a multipart
    file upload of a `.zip` bundle directory (not both).
    Returns immediately with `{run_id, status: "started"}`.
    """
    if file is not None:
        # Multipart zip upload — extract to a temp directory and use it as input
        if not file.filename or not file.filename.endswith(".zip"):
            raise HTTPException(status_code=400, detail="Uploaded file must be a .zip archive")

        tmp_dir = tempfile.mkdtemp(prefix="aipm_bundle_")
        zip_path = Path(tmp_dir) / "bundle.zip"
        zip_path.write_bytes(await file.read())

        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(tmp_dir)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid zip archive")

        # Use the extracted directory as input_path (the zip root)
        input_path = tmp_dir
        run_id = _start_run(background_tasks, input_path)

    elif body is not None:
        run_id = _start_run(
            background_tasks,
            input_path=body.prompt,
            provider=body.provider,
            model=body.model,
            temperature=body.temperature,
            policy_path=body.policy_path,
            output_dir=body.output_dir,
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Provide either a JSON body with 'prompt' or a multipart 'file' upload",
        )

    logger.info("Accepted run_id=%s", run_id)
    return RunStartedResponse(run_id=run_id)


@app.get("/api/v1/run/{run_id}/status", response_model=RunStatusResponse)
async def get_run_status(run_id: str) -> RunStatusResponse:
    """Return the current pipeline status for a given run."""
    run = _get_run_or_404(run_id)
    return RunStatusResponse(
        run_id=run_id,
        status=run["status"],
        agents_completed=run["agents_completed"],
        current_agent=run["current_agent"],
    )


@app.get("/api/v1/run/{run_id}/artifacts", response_model=ArtifactsResponse)
async def list_artifacts(run_id: str) -> ArtifactsResponse:
    """Return the list of generated artifacts with download links."""
    run = _get_run_or_404(run_id)

    if run["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Run is not completed yet (status: {run['status']})",
        )

    artifacts_dir = Path(run["run_dir"]) / "artifacts"
    if not artifacts_dir.exists():
        return ArtifactsResponse(run_id=run_id, artifacts=[])

    links = [
        ArtifactLink(
            name=p.name,
            download_url=f"/api/v1/run/{run_id}/artifacts/{p.name}",
        )
        for p in sorted(artifacts_dir.iterdir())
        if p.is_file()
    ]
    return ArtifactsResponse(run_id=run_id, artifacts=links)


@app.get("/api/v1/run/{run_id}/artifacts/{artifact_name}")
async def download_artifact(run_id: str, artifact_name: str) -> FileResponse:
    """Download a specific artifact file by name (e.g. prd.md, roadmap.json)."""
    run = _get_run_or_404(run_id)

    if run["status"] != "completed":
        raise HTTPException(
            status_code=409,
            detail=f"Run is not completed yet (status: {run['status']})",
        )

    # Guard against path traversal
    artifacts_dir = Path(run["run_dir"]) / "artifacts"
    artifact_path = (artifacts_dir / artifact_name).resolve()
    if not str(artifact_path).startswith(str(artifacts_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid artifact name")

    if not artifact_path.exists():
        raise HTTPException(status_code=404, detail=f"Artifact not found: {artifact_name}")

    return FileResponse(path=str(artifact_path), filename=artifact_name)


@app.get("/api/v1/run/{run_id}/manifest")
async def get_manifest(run_id: str) -> JSONResponse:
    """Return the full run manifest JSON for a completed run."""
    run = _get_run_or_404(run_id)

    # Prefer the in-memory manifest (available immediately after completion)
    if run["manifest"] is not None:
        return JSONResponse(content=run["manifest"])

    # Fall back to reading from disk
    manifest_path = Path(run["run_dir"]) / "run_manifest.json"
    if not manifest_path.exists():
        status = run["status"]
        raise HTTPException(
            status_code=409 if status == "running" else 404,
            detail=f"Manifest not available (status: {status})",
        )

    return JSONResponse(content=json.loads(manifest_path.read_text(encoding="utf-8")))


@app.get("/api/v1/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Return API health status."""
    return HealthResponse(status="healthy", version="1.0.0")
