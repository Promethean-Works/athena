from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from athena.auth.deps import Authed
from athena.jobs import Job, JobManager, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def manager(request: Request) -> JobManager:
    return request.app.state.jobs


def _job(request: Request, job_id: str, user: Authed) -> Job:
    job = manager(request).get(job_id)
    # A job a plain user didn't have the right to start looks like one that doesn't exist.
    if job is None or not (user.user.is_admin or job.user_visible):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    return job


@router.get("/{job_id}", operation_id="getJob")
def get_job(job_id: str, request: Request, user: Authed) -> JobOut:
    return _job(request, job_id, user).out()


@router.get(
    "/{job_id}/events",
    operation_id="streamJobEvents",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def job_events(job_id: str, request: Request, user: Authed) -> StreamingResponse:
    """Server-Sent Events: `log` (one output line, JSON string), `progress` (a
    JobProgress, for jobs that report it) and a final `status`."""
    job = _job(request, job_id, user)
    return StreamingResponse(job.events(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/{job_id}/cancel", operation_id="cancelJob", status_code=status.HTTP_202_ACCEPTED)
async def cancel_job(job_id: str, request: Request, user: Authed) -> JobOut:
    """Stop a job that says it's `cancellable`. It ends as failed, with "Cancelled"."""
    job = _job(request, job_id, user)
    if not await job.cancel():
        raise HTTPException(status.HTTP_409_CONFLICT, "This job can't be stopped")
    return job.out()
