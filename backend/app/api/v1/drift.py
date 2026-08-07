from fastapi import APIRouter, HTTPException, Request, status

from app.api.deps import CurrentUser, DbSession, record_audit
from app.schemas import DriftOut, DriftRequest
from app.services import drift as drift_service

router = APIRouter(prefix="/drift", tags=["drift"])


@router.post("", response_model=DriftOut)
def compare_snapshots(
    payload: DriftRequest, request: Request, user: CurrentUser, db: DbSession
) -> DriftOut:
    """Compare two snapshots of the same system and produce a drift report."""
    try:
        result = drift_service.run_drift(
            db, payload.baseline_snapshot_id, payload.current_snapshot_id, actor=user.email
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    record_audit(
        db,
        request,
        "drift.compare",
        actor=user.email,
        target_type="snapshot",
        target_id=payload.current_snapshot_id,
        detail={k: v for k, v in result.items() if k != "report_id"},
    )
    return DriftOut(**result)
