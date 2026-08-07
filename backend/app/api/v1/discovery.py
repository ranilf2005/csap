from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession, record_audit
from app.models import Connection, Job
from app.schemas import JobOut
from app.workers.tasks import discover_task

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/{connection_id}", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
def start_discovery(connection_id: str, request: Request, user: CurrentUser, db: DbSession) -> Job:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")

    running = (
        db.query(Job)
        .filter(
            Job.connection_id == connection_id,
            Job.job_type == "discover",
            Job.status.in_(["pending", "running"]),
        )
        .first()
    )
    if running is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A discovery job is already running for this system")

    job = Job(connection_id=connection_id, job_type="discover", created_by=user.id)
    db.add(job)
    db.commit()
    db.refresh(job)

    discover_task.delay(job.id)
    record_audit(db, request, "discovery.start", actor=user.email, target_type="job", target_id=job.id)
    return job


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(_user: CurrentUser, db: DbSession, limit: int = 50) -> list[Job]:
    return db.query(Job).order_by(Job.created_at.desc()).limit(min(limit, 200)).all()


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, _user: CurrentUser, db: DbSession) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job
