from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, record_audit
from app.core.crypto import encrypt
from app.models import Connection
from app.plugins import registry
from app.schemas import (
    ConnectionCreate,
    ConnectionOut,
    ConnectionTestResult,
    ConnectionUpdate,
)
from app.services.connections import UnsafeTargetError, assert_target_allowed, to_context

router = APIRouter(prefix="/connections", tags=["connections"])


def _get_or_404(db: DbSession, connection_id: str) -> Connection:
    conn = db.get(Connection, connection_id)
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found")
    return conn


@router.get("", response_model=list[ConnectionOut])
def list_connections(_user: CurrentUser, db: DbSession) -> list[Connection]:
    return db.query(Connection).order_by(Connection.name).all()


@router.post("", response_model=ConnectionOut, status_code=status.HTTP_201_CREATED)
def create_connection(
    payload: ConnectionCreate, request: Request, user: CurrentUser, db: DbSession
) -> Connection:
    try:
        registry.get(payload.product)
    except KeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    try:
        assert_target_allowed(payload.host)
    except UnsafeTargetError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None

    conn = Connection(
        name=payload.name,
        product=payload.product,
        host=payload.host,
        port=payload.port,
        username=payload.username,
        encrypted_password=encrypt(payload.password),
        verify_tls=payload.verify_tls,
    )
    db.add(conn)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "A connection with that name already exists") from None

    db.refresh(conn)
    record_audit(
        db, request, "connection.create", actor=user.email, target_type="connection", target_id=conn.id
    )
    return conn


@router.patch("/{connection_id}", response_model=ConnectionOut)
def update_connection(
    connection_id: str, payload: ConnectionUpdate, request: Request, user: CurrentUser, db: DbSession
) -> Connection:
    conn = _get_or_404(db, connection_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("host"):
        try:
            assert_target_allowed(data["host"])
        except UnsafeTargetError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
    if "password" in data:
        conn.encrypted_password = encrypt(data.pop("password"))
    for key, value in data.items():
        setattr(conn, key, value)
    db.commit()
    db.refresh(conn)
    record_audit(
        db, request, "connection.update", actor=user.email, target_type="connection", target_id=conn.id
    )
    return conn


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_connection(connection_id: str, request: Request, user: CurrentUser, db: DbSession) -> None:
    conn = _get_or_404(db, connection_id)
    db.delete(conn)
    db.commit()
    record_audit(
        db, request, "connection.delete", actor=user.email, target_type="connection", target_id=connection_id
    )


@router.post("/{connection_id}/test", response_model=ConnectionTestResult)
def test_connection(
    connection_id: str, request: Request, user: CurrentUser, db: DbSession
) -> ConnectionTestResult:
    conn = _get_or_404(db, connection_id)
    plugin = registry.get(conn.product)
    result = plugin.test_connection(to_context(conn))

    conn.last_status = "connected" if result.ok else "error"
    conn.last_error = None if result.ok else result.detail
    conn.detected_version = result.product_version or conn.detected_version
    db.commit()

    record_audit(
        db,
        request,
        "connection.test",
        actor=user.email,
        outcome="success" if result.ok else "failure",
        target_type="connection",
        target_id=conn.id,
    )
    return ConnectionTestResult(ok=result.ok, product_version=result.product_version, detail=result.detail)
