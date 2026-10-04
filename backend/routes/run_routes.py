import asyncio
import logging
import os
import time
import uuid
from typing import Dict

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile

from deps import db, get_uid
from schema import (
    DependencyReviewRequest,
    RestfulModel,
    WorkflowRunStartRequest,
)
from src.orchestration.orchestrator import CoordinatorAgent
from src.orchestration.storage import WorkflowRunStorage
from service import validate_edges_with_log_service


router = APIRouter(prefix="/workflow", tags=["workflow-runs"])
storage = WorkflowRunStorage()
orchestrator = CoordinatorAgent(storage)
active_tasks: Dict[str, asyncio.Task] = {}
logger = logging.getLogger(__name__)

_RUNNING_STATUSES = {
    "pending",
    "generating",
    "evaluating",
    "repairing",
    "verifying",
    "awaiting_review",
}


def _cleanup_scheduled_task(run_id: str, task: asyncio.Task) -> None:
    try:
        if task.cancelled():
            logger.info("Workflow run task %s was cancelled", run_id)
            return
        exception = task.exception()
        if exception is None:
            return

        logger.error(
            "Workflow run task %s exited with an unexpected exception",
            run_id,
            exc_info=(type(exception), exception, exception.__traceback__),
        )
        try:
            run = storage.get_run(run_id)
            if run and run.get("status") in _RUNNING_STATUSES:
                detail = str(exception).strip() or type(exception).__name__
                message = f"Coordinator task failed unexpectedly: {detail}"
                storage.update_run(
                    run_id,
                    status="failed",
                    active_agent="coordinator",
                    active_step="failed",
                    error_message=message,
                    completed_at=int(time.time() * 1000),
                )
                storage.add_event(
                    run_id,
                    "coordinator_task_failed",
                    agent="coordinator",
                    step="failed",
                    message=message,
                    payload={"error_type": type(exception).__name__},
                )
        except Exception:
            logger.exception(
                "Could not persist the unexpected failure for workflow run %s",
                run_id,
            )
    finally:
        if active_tasks.get(run_id) is task:
            active_tasks.pop(run_id, None)


def _schedule(run_id: str) -> None:
    existing = active_tasks.get(run_id)
    if existing and not existing.done():
        return
    task = asyncio.create_task(orchestrator.execute(run_id))
    active_tasks[run_id] = task
    task.add_done_callback(
        lambda completed_task: _cleanup_scheduled_task(run_id, completed_task)
    )


def _owned_run(run_id: str, uid: int):
    run = storage.get_run(run_id)
    if not run or int(run.get("uid") or 1) != int(uid):
        raise HTTPException(status_code=404, detail="Workflow run not found")
    return run


@router.post("/{workflow_id}/runs")
async def start_workflow_run(
    workflow_id: int,
    req: WorkflowRunStartRequest = Body(...),
    uid: int = Depends(get_uid),
):
    if not req.description.strip():
        return RestfulModel(code=-1, msg="Workflow description cannot be empty")
    if not 1 <= req.max_iterations <= 10:
        return RestfulModel(code=-1, msg="max_iterations must be between 1 and 10")
    if not 0.0 <= req.regeneration_threshold <= 5.0:
        return RestfulModel(
            code=-1,
            msg="regeneration_threshold must be between 0 and 5",
        )
    if not 1.0 <= req.acceptance_threshold <= 5.0:
        return RestfulModel(code=-1, msg="acceptance_threshold must be between 1 and 5")
    if req.regeneration_threshold >= req.acceptance_threshold:
        return RestfulModel(
            code=-1,
            msg="regeneration_threshold must be lower than acceptance_threshold",
        )

    workflow_rows = db.fetch_query(
        "SELECT id FROM workflow WHERE id = %s AND uid = %s LIMIT 1",
        (workflow_id, uid),
    )
    if not workflow_rows:
        return RestfulModel(code=-1, msg="Workflow not found")

    active = storage.get_active_run(workflow_id)
    if active:
        return RestfulModel(
            code=-1,
            msg="This workflow already has an active run",
            data=storage.get_detail(active["id"]),
        )

    run_id = str(uuid.uuid4())
    storage.create_run(
        run_id=run_id,
        workflow_id=workflow_id,
        uid=uid,
        description=req.description.strip(),
        max_iterations=req.max_iterations,
        regeneration_threshold=req.regeneration_threshold,
        acceptance_threshold=req.acceptance_threshold,
        auto_repair=req.auto_repair,
    )
    _schedule(run_id)
    return RestfulModel(
        code=200,
        msg="Workflow optimization run started",
        data=storage.get_detail(run_id),
    )


@router.get("/{workflow_id}/runs/latest")
async def get_latest_workflow_run(
    workflow_id: int,
    uid: int = Depends(get_uid),
):
    run = storage.get_latest_run(workflow_id)
    if not run or int(run.get("uid") or 1) != int(uid):
        return RestfulModel(code=200, msg="No workflow run found", data=None)
    return RestfulModel(data=storage.get_detail(run["id"]))


@router.get("/runs/{run_id}")
async def get_workflow_run(run_id: str, uid: int = Depends(get_uid)):
    _owned_run(run_id, uid)
    return RestfulModel(data=storage.get_detail(run_id))


@router.get("/runs/{run_id}/versions")
async def list_workflow_run_versions(
    run_id: str,
    uid: int = Depends(get_uid),
):
    _owned_run(run_id, uid)
    return RestfulModel(data=storage.list_versions(run_id))


@router.get("/runs/{run_id}/versions/{version_no}")
async def get_workflow_run_version(
    run_id: str,
    version_no: int,
    uid: int = Depends(get_uid),
):
    _owned_run(run_id, uid)
    version = storage.get_version(run_id, version_no)
    if not version:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    return RestfulModel(data=version)


@router.post("/runs/{run_id}/stop")
async def stop_workflow_run(run_id: str, uid: int = Depends(get_uid)):
    run = _owned_run(run_id, uid)
    if run.get("status") not in {
        "pending",
        "generating",
        "evaluating",
        "repairing",
        "verifying",
        "awaiting_review",
    }:
        return RestfulModel(
            code=-1,
            msg=f"Run cannot be stopped from status {run.get('status')}",
        )
    if run.get("status") == "awaiting_review":
        storage.update_run(
            run_id,
            status="stopped",
            stop_requested=False,
            active_agent="coordinator",
            active_step="stopped",
            completed_at=int(time.time() * 1000),
            error_message="The run was stopped during dependency review.",
        )
        storage.add_event(
            run_id,
            "coordinator_stopped",
            agent="coordinator",
            step="stopped",
            message=(
                "Coordinator Agent stopped the run during dependency review "
                "at the user's request."
            ),
        )
    else:
        storage.request_stop(run_id)
    return RestfulModel(
        data=storage.get_detail(run_id),
        msg=(
            "Workflow run stopped"
            if run.get("status") == "awaiting_review"
            else "Stop requested"
        ),
    )


@router.post("/runs/{run_id}/retry")
async def retry_workflow_run(run_id: str, uid: int = Depends(get_uid)):
    run = _owned_run(run_id, uid)
    if run.get("status") not in {"failed", "needs_review", "stopped"}:
        return RestfulModel(
            code=-1,
            msg=f"Run cannot be retried from status {run.get('status')}",
        )
    current_version = int(run.get("current_version") or 0)
    max_iterations = min(10, max(1, int(run.get("max_iterations") or 3)))
    if run.get("status") == "needs_review" and current_version >= max_iterations:
        return RestfulModel(
            code=-1,
            msg=(
                f"The maximum of {max_iterations} workflow versions has "
                "already been reached"
            ),
        )
    storage.update_run(
        run_id,
        status="pending",
        stop_requested=False,
        error_message=None,
        completed_at=None,
        final_version=None,
        max_iterations=max_iterations,
    )
    _schedule(run_id)
    return RestfulModel(
        data=storage.get_detail(run_id),
        msg="Workflow run retry started",
    )


@router.post("/runs/{run_id}/versions/{version_no}/accept")
async def accept_workflow_version(
    run_id: str,
    version_no: int,
    uid: int = Depends(get_uid),
):
    run = _owned_run(run_id, uid)
    if run.get("status") in {
        "pending",
        "generating",
        "evaluating",
        "repairing",
        "verifying",
        "awaiting_review",
    }:
        return RestfulModel(
            code=-1,
            msg="An active workflow run cannot be accepted",
        )
    version = storage.get_version(run_id, version_no)
    if not version:
        raise HTTPException(status_code=404, detail="Workflow version not found")
    await orchestrator._finish_run(
        run_id,
        version_no,
        version["dag"],
        status="completed",
        message=f"Version v{version_no} was accepted by the user.",
    )
    return RestfulModel(
        data=storage.get_detail(run_id),
        msg=f"Version v{version_no} accepted",
    )


@router.post("/runs/{run_id}/versions/{version_no}/validate-log")
async def validate_workflow_run_version_log(
    run_id: str,
    version_no: int,
    file: UploadFile = File(...),
    uid: int = Depends(get_uid),
):
    run = _owned_run(run_id, uid)
    if run.get("status") in {
        "pending",
        "generating",
        "evaluating",
        "repairing",
        "verifying",
    }:
        return RestfulModel(
            code=-1,
            msg="Execution logs can be attached after the automatic run stops",
        )
    version = storage.get_version(run_id, version_no)
    if not version or not version.get("simulation_results"):
        return RestfulModel(
            code=-1,
            msg="This version has no discrepancy analysis to validate",
        )
    if not (
        file.filename
        and (file.filename.endswith(".xes") or file.filename.endswith(".xes.gz"))
    ):
        return RestfulModel(code=-1, msg="Please upload a .xes or .xes.gz file")

    backend_dir = os.path.dirname(os.path.dirname(__file__))
    log_dir = os.path.join(
        backend_dir,
        "data",
        "logs",
        str(run["workflow_id"]),
        run_id,
    )
    os.makedirs(log_dir, exist_ok=True)
    extension = ".xes.gz" if file.filename.endswith(".xes.gz") else ".xes"
    log_path = os.path.join(
        log_dir,
        f"v{version_no}_{int(time.time())}{extension}",
    )
    content = await file.read()
    with open(log_path, "wb") as handle:
        handle.write(content)

    updated_simulation = validate_edges_with_log_service(
        version["simulation_results"],
        log_path,
    )
    orchestrator.apply_log_validation(
        run_id,
        version_no,
        updated_simulation,
    )
    return RestfulModel(
        data=storage.get_detail(run_id),
        msg="Execution-log validation completed",
    )


@router.post("/runs/{run_id}/versions/{version_no}/dependency-review")
async def confirm_dependency_review(
    run_id: str,
    version_no: int,
    req: DependencyReviewRequest = Body(...),
    uid: int = Depends(get_uid),
):
    run = _owned_run(run_id, uid)
    if (
        run.get("status") != "awaiting_review"
        or int(run.get("current_version") or 0) != version_no
    ):
        return RestfulModel(
            code=-1,
            msg="This workflow version is not awaiting dependency review",
        )
    version = storage.get_version(run_id, version_no)
    if not version or not version.get("simulation_results"):
        return RestfulModel(code=-1, msg="Dependency analysis is unavailable")
    simulation_links = version["simulation_results"].get("task_links", [])
    if not simulation_links or not all(
        link.get("log_edge_type") for link in simulation_links
    ):
        return RestfulModel(
            code=-1,
            msg="Select and validate an XES execution log before confirming dependencies",
        )

    submitted = {}
    for link in req.task_links:
        source = str(link.get("source", "")).strip()
        target = str(link.get("target", "")).strip()
        status = str(link.get("status", "")).lower()
        if not source or not target or status not in {"pass", "warn"}:
            return RestfulModel(
                code=-1,
                msg="Each dependency must have source, target and PASS/WARN status",
            )
        submitted[(source, target)] = status

    simulation = dict(version["simulation_results"])
    reviewed_links = []
    for link in simulation.get("task_links", []):
        key = (
            str(link.get("source", "")).strip(),
            str(link.get("target", "")).strip(),
        )
        if key not in submitted:
            return RestfulModel(
                code=-1,
                msg=f"Missing review decision for dependency {key[0]} -> {key[1]}",
            )
        reviewed_links.append({**link, "status": submitted[key]})
    simulation["task_links"] = reviewed_links

    storage.update_version(
        run_id,
        version_no,
        simulation_results=simulation,
        status="review_confirmed",
    )
    storage.update_run(
        run_id,
        status="pending",
        active_agent="coordinator",
        active_step="user_input_received",
        stop_requested=False,
        completed_at=None,
        error_message=None,
    )
    storage.add_event(
        run_id,
        "dependency_review_confirmed",
        agent="coordinator",
        step="user_input_received",
        version_no=version_no,
        message=(
            f"Coordinator Agent received dependency decisions for v{version_no} "
            "and delegated scoring to Evaluation Agent."
        ),
        payload={
            "decision": "delegate_evaluation",
            "target_agent": "evaluation",
            "warn_count": sum(
                1 for link in reviewed_links if link["status"] == "warn"
            )
        },
    )
    _schedule(run_id)
    return RestfulModel(
        data=storage.get_detail(run_id),
        msg="Dependency review confirmed; evaluation resumed",
    )
