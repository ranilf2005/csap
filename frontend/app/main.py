"""CSAP web UI: thin server-rendered client over the backend REST API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

BASE_DIR = Path(__file__).resolve().parent
BACKEND_URL = os.environ.get("BACKEND_URL", "http://backend:8000")
SECRET_KEY = os.environ["SECRET_KEY"]
IS_PROD = os.environ.get("ENVIRONMENT", "production") == "production"

app = FastAPI(title="CSAP UI", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="csap_session",
    https_only=IS_PROD,
    same_site="lax",
    max_age=60 * 60,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# --- backend helpers -------------------------------------------------------
def _token(request: Request) -> str | None:
    return request.session.get("token")


async def api(
    request: Request,
    method: str,
    path: str,
    *,
    json: Any = None,
    data: Any = None,
    files: Any = None,
    raw: bool = False,
) -> Any:
    token = _token(request)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=300.0) as client:
        resp = await client.request(method, path, json=json, data=data, files=files, headers=headers)
    if resp.status_code == 401:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session expired")
    if raw:
        return resp
    if resp.status_code >= 400:
        detail = resp.json().get("detail", resp.text) if resp.content else resp.reason_phrase
        raise HTTPException(resp.status_code, detail)
    return resp.json() if resp.content else None


def render(request: Request, template: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
    return templates.TemplateResponse(
        request, template, {"user": request.session.get("user"), **ctx}, status_code=status_code
    )


@app.exception_handler(HTTPException)
async def _auth_redirect(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == status.HTTP_401_UNAUTHORIZED:
        request.session.clear()
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(
        request, "error.html", status_code=exc.status_code, code=exc.status_code, message=exc.detail
    )


# --- auth ------------------------------------------------------------------
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> HTMLResponse:
    return render(request, "login.html")


@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)) -> Response:
    async with httpx.AsyncClient(base_url=BACKEND_URL, timeout=30.0) as client:
        resp = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
    if resp.status_code != 200:
        return render(request, "login.html", error="Incorrect email or password")

    data = resp.json()
    request.session["token"] = data["access_token"]
    request.session["user"] = email
    request.session["must_change_password"] = data.get("must_change_password", False)
    return RedirectResponse("/", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/logout")
async def logout(request: Request) -> Response:
    request.session.clear()
    return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)


# --- pages -----------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    connections = await api(request, "GET", "/api/v1/connections")
    jobs = await api(request, "GET", "/api/v1/discovery/jobs?limit=10")
    snapshots = await api(request, "GET", "/api/v1/snapshots?limit=10")
    return render(
        request,
        "dashboard.html",
        connections=connections,
        jobs=jobs,
        snapshots=snapshots,
        must_change_password=request.session.get("must_change_password"),
    )


@app.get("/connections", response_class=HTMLResponse)
async def connections_page(request: Request) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    connections = await api(request, "GET", "/api/v1/connections")
    plugins = await api(request, "GET", "/api/v1/plugins")
    return render(request, "connections.html", connections=connections, plugins=plugins)


@app.post("/connections")
async def create_connection(
    request: Request,
    name: str = Form(...),
    product: str = Form(...),
    host: str = Form(...),
    port: int = Form(443),
    username: str = Form(...),
    password: str = Form(...),
    verify_tls: str | None = Form(None),
) -> Response:
    await api(
        request,
        "POST",
        "/api/v1/connections",
        json={
            "name": name,
            "product": product,
            "host": host,
            "port": port,
            "username": username,
            "password": password,
            "verify_tls": verify_tls == "on",
        },
    )
    return RedirectResponse("/connections", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/connections/{connection_id}/test", response_class=HTMLResponse)
async def test_connection(request: Request, connection_id: str) -> HTMLResponse:
    result = await api(request, "POST", f"/api/v1/connections/{connection_id}/test")
    return render(request, "partials/test_result.html", result=result)


@app.post("/connections/{connection_id}/delete")
async def delete_connection(request: Request, connection_id: str) -> Response:
    await api(request, "DELETE", f"/api/v1/connections/{connection_id}")
    return RedirectResponse("/connections", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/connections/{connection_id}/discover")
async def start_discovery(request: Request, connection_id: str) -> Response:
    job = await api(request, "POST", f"/api/v1/discovery/{connection_id}")
    return RedirectResponse(f"/jobs/{job['id']}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_page(request: Request, job_id: str) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    job = await api(request, "GET", f"/api/v1/discovery/jobs/{job_id}")
    return render(request, "job.html", job=job)


@app.get("/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str) -> HTMLResponse:
    job = await api(request, "GET", f"/api/v1/discovery/jobs/{job_id}")
    return render(request, "partials/job_status.html", job=job)


@app.get("/snapshots/{snapshot_id}", response_class=HTMLResponse)
async def inventory_page(
    request: Request, snapshot_id: str, item_type: str = "", search: str = "", offset: int = 0
) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    query = f"?limit=100&offset={offset}"
    if item_type:
        query += f"&item_type={item_type}"
    if search:
        query += f"&search={search}"
    page = await api(request, "GET", f"/api/v1/snapshots/{snapshot_id}/inventory{query}")
    snapshots = await api(request, "GET", "/api/v1/snapshots?limit=100")
    snapshot = next((s for s in snapshots if s["id"] == snapshot_id), None)
    return render(
        request,
        "inventory.html",
        snapshot=snapshot,
        items=page["items"],
        meta=page["meta"],
        item_type=item_type,
        search=search,
        offset=offset,
    )


@app.get("/snapshots/{snapshot_id}/template")
async def download_template(request: Request, snapshot_id: str) -> Response:
    resp = await api(request, "GET", f"/api/v1/snapshots/{snapshot_id}/template", raw=True)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, "Could not generate the template")
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type"),
        headers={"Content-Disposition": resp.headers.get("content-disposition", "attachment")},
    )


@app.post("/snapshots/{snapshot_id}/report")
async def make_inventory_report(request: Request, snapshot_id: str) -> Response:
    report = await api(request, "POST", f"/api/v1/snapshots/{snapshot_id}/report")
    return RedirectResponse(f"/reports/{report['id']}", status_code=status.HTTP_303_SEE_OTHER)


# --- change requests -------------------------------------------------------
@app.get("/changes", response_class=HTMLResponse)
async def changes_page(request: Request) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    changes = await api(request, "GET", "/api/v1/changes")
    connections = await api(request, "GET", "/api/v1/connections")
    snapshots = await api(request, "GET", "/api/v1/snapshots?limit=100")
    by_connection = {c["id"]: c for c in connections}
    ready = {s["connection_id"] for s in snapshots}
    return render(
        request,
        "changes.html",
        changes=changes,
        connections=connections,
        by_connection=by_connection,
        ready=ready,
    )


@app.post("/changes")
async def upload_change(
    request: Request, connection_id: str = Form(...), file: UploadFile = File(...)
) -> Response:
    content = await file.read()
    change = await api(
        request,
        "POST",
        "/api/v1/changes",
        data={"connection_id": connection_id},
        files={
            "file": (
                file.filename or "changes.xlsx",
                content,
                file.content_type or "application/octet-stream",
            )
        },
    )
    return RedirectResponse(f"/changes/{change['id']}", status_code=status.HTTP_303_SEE_OTHER)


@app.get("/changes/{change_id}", response_class=HTMLResponse)
async def change_detail(request: Request, change_id: str) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    change = await api(request, "GET", f"/api/v1/changes/{change_id}")
    connections = await api(request, "GET", "/api/v1/connections")
    change_reports = await api(request, "GET", f"/api/v1/reports?subject_id={change_id}")
    connection = next((c for c in connections if c["id"] == change["connection_id"]), None)
    return render(
        request,
        "change_detail.html",
        change=change,
        connection=connection,
        reports=change_reports,
        issues=(change.get("validation") or {}).get("issues", []),
    )


@app.post("/changes/{change_id}/revalidate")
async def revalidate_change(request: Request, change_id: str) -> Response:
    await api(request, "POST", f"/api/v1/changes/{change_id}/revalidate")
    return RedirectResponse(f"/changes/{change_id}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/changes/{change_id}/deploy")
async def deploy_change(
    request: Request, change_id: str, mode: str = Form("dry_run"), engine: str = Form("rest")
) -> Response:
    dry_run = mode != "apply"
    job = await api(
        request,
        "POST",
        f"/api/v1/changes/{change_id}/deploy",
        json={"dry_run": dry_run, "engine": engine, "confirm": not dry_run},
    )
    return RedirectResponse(f"/jobs/{job['id']}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/changes/{change_id}/rollback")
async def rollback_change(request: Request, change_id: str) -> Response:
    job = await api(request, "POST", f"/api/v1/changes/{change_id}/rollback")
    return RedirectResponse(f"/jobs/{job['id']}", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/changes/{change_id}/delete")
async def delete_change(request: Request, change_id: str) -> Response:
    await api(request, "DELETE", f"/api/v1/changes/{change_id}")
    return RedirectResponse("/changes", status_code=status.HTTP_303_SEE_OTHER)


# --- reports ---------------------------------------------------------------
@app.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, kind: str = "") -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    query = f"?kind={kind}" if kind else ""
    items = await api(request, "GET", f"/api/v1/reports{query}")
    return render(request, "reports.html", reports=items, kind=kind)


@app.get("/reports/{report_id}", response_class=HTMLResponse)
async def view_report(request: Request, report_id: str) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    resp = await api(request, "GET", f"/api/v1/reports/{report_id}/html", raw=True)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, "Report not available")
    return HTMLResponse(content=resp.text)


@app.get("/reports/{report_id}/download")
async def download_report(request: Request, report_id: str) -> Response:
    resp = await api(request, "GET", f"/api/v1/reports/{report_id}/download", raw=True)
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, "Report not available")
    return Response(
        content=resp.content,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": resp.headers.get("content-disposition", "attachment")},
    )


@app.post("/reports/{report_id}/delete")
async def delete_report(request: Request, report_id: str) -> Response:
    await api(request, "DELETE", f"/api/v1/reports/{report_id}")
    return RedirectResponse("/reports", status_code=status.HTTP_303_SEE_OTHER)


# --- drift -----------------------------------------------------------------
@app.get("/drift", response_class=HTMLResponse)
async def drift_page(request: Request) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    snapshots = await api(request, "GET", "/api/v1/snapshots?limit=200")
    connections = await api(request, "GET", "/api/v1/connections")
    drift_reports = await api(request, "GET", "/api/v1/reports?kind=drift")
    return render(
        request,
        "drift.html",
        snapshots=snapshots,
        connections=connections,
        reports=drift_reports,
    )


@app.post("/drift")
async def run_drift(
    request: Request, baseline_snapshot_id: str = Form(...), current_snapshot_id: str = Form(...)
) -> Response:
    result = await api(
        request,
        "POST",
        "/api/v1/drift",
        json={
            "baseline_snapshot_id": baseline_snapshot_id,
            "current_snapshot_id": current_snapshot_id,
        },
    )
    return RedirectResponse(f"/reports/{result['report_id']}", status_code=status.HTTP_303_SEE_OTHER)


# --- audit -----------------------------------------------------------------
@app.get("/audit", response_class=HTMLResponse)
async def audit_page(request: Request, actor: str = "", offset: int = 0) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    query = f"?limit=100&offset={offset}"
    if actor:
        query += f"&actor={actor}"
    events = await api(request, "GET", f"/api/v1/audit{query}")
    return render(request, "audit.html", events=events, actor=actor, offset=offset)


# --- account ---------------------------------------------------------------
@app.get("/account/password", response_class=HTMLResponse)
async def password_form(request: Request) -> Response:
    if not _token(request):
        return RedirectResponse("/login", status_code=status.HTTP_303_SEE_OTHER)
    return render(request, "change_password.html")


@app.post("/account/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
) -> Response:
    if new_password != confirm_password:
        return render(request, "change_password.html", error="The new passwords do not match")
    if len(new_password) < 12:
        return render(request, "change_password.html", error="Use at least 12 characters")

    resp = await api(
        request,
        "POST",
        "/api/v1/auth/change-password",
        json={"current_password": current_password, "new_password": new_password},
        raw=True,
    )
    if resp.status_code >= 400:
        return render(request, "change_password.html", error="Your current password is incorrect")

    request.session["must_change_password"] = False
    return render(request, "change_password.html", success="Password updated.")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
