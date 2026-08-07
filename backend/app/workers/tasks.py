from app.core.database import SessionLocal
from app.services.changes import run_deployment, run_rollback
from app.services.discovery import run_discovery
from app.workers.celery_app import celery_app


@celery_app.task(name="csap.discover")
def discover_task(job_id: str) -> str:
    db = SessionLocal()
    try:
        run_discovery(db, job_id)
    finally:
        db.close()
    return job_id


@celery_app.task(name="csap.deploy")
def deploy_task(job_id: str) -> str:
    db = SessionLocal()
    try:
        run_deployment(db, job_id)
    finally:
        db.close()
    return job_id


@celery_app.task(name="csap.rollback")
def rollback_task(job_id: str) -> str:
    db = SessionLocal()
    try:
        run_rollback(db, job_id)
    finally:
        db.close()
    return job_id
