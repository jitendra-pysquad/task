"""FastAPI entry point for the dashboard and CSV download."""

import logging
import re
from hmac import compare_digest
from secrets import token_urlsafe
from threading import Lock
from typing import Callable
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .artifacts import employee_csv, load_result, save_result
from .automation import run_automation
from .config import ROOT, Settings
from .models import FIELD_LIMITS, RunInput, RunResult, validate_form

LOGGER = logging.getLogger("uvicorn.error.orangehrm")
COOKIE_NAME = "hrm_dashboard"
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")
PREVIEW_ROWS = 8
PACKAGE = ROOT / "app"


def create_app(
    settings: Settings | None = None,
    runner: Callable[[RunInput, Settings], RunResult] = run_automation,
) -> FastAPI:
    """Create the dashboard with an injectable automation runner for tests."""
    config = settings or Settings.from_environment()
    run_lock = Lock()
    app = FastAPI(
        title="OrangeHRM Automation", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=PACKAGE / "templates")

    def browser_token(request: Request) -> str | None:
        token = request.cookies.get(COOKIE_NAME, "")
        return token if TOKEN_PATTERN.fullmatch(token) else None

    def dashboard(
        request: Request,
        status_code: int = 200,
        **context: object,
    ) -> HTMLResponse:
        token = browser_token(request) or token_urlsafe(32)
        response = templates.TemplateResponse(
            request=request,
            name="index.html",
            context={
                "csrf": token,
                "values": {},
                "errors": {},
                "limits": FIELD_LIMITS,
                "preview_rows": PREVIEW_ROWS,
                **context,
            },
            status_code=status_code,
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'self'; object-src 'none'; base-uri 'none'; "
                    "frame-ancestors 'none'; form-action 'self'"
                ),
                "Referrer-Policy": "no-referrer",
            },
        )
        if browser_token(request) is None:
            response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="strict")
        return response

    def result_for(request: Request, run_id: UUID) -> RunResult:
        owner = browser_token(request)
        result = load_result(config.run_directory, owner, run_id) if owner else None
        if result is None:
            raise HTTPException(status_code=404, detail="Run not found.")
        return result

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> Response:
        return dashboard(request)

    async def handle_submission(request: Request, retry_id: UUID | None) -> Response:
        previous = (
            await run_in_threadpool(result_for, request, retry_id) if retry_id else None
        )
        if previous is not None and (previous.employee is None or previous.rows):
            raise HTTPException(
                status_code=409, detail="This run has no pending export."
            )
        context = {"result": previous, "run_id": retry_id}

        content_type = request.headers.get("content-type", "").partition(";")[0]
        if content_type.strip().lower() != "application/x-www-form-urlencoded":
            return dashboard(
                request, 415, message="Submit using the dashboard form.", **context
            )
        length = request.headers.get("content-length", "")
        if not length.isdecimal() or len(length) > 5 or int(length) > 16_384:
            return dashboard(request, 413, message="The form is too large.", **context)
        async with request.form() as form:
            owner = browser_token(request)
            csrf = form.get("csrf", "")
            if (
                owner is None
                or not isinstance(csrf, str)
                or not TOKEN_PATTERN.fullmatch(csrf)
                or not compare_digest(owner, csrf)
            ):
                return dashboard(
                    request,
                    403,
                    message="Reload the dashboard and try again.",
                    **context,
                )
            run_input, values, errors = validate_form(
                form, previous.employee if previous else None
            )
        if run_input is None:
            return dashboard(request, 422, values=values, errors=errors, **context)

        def execute() -> tuple[UUID | None, RunResult | None]:
            if not run_lock.acquire(blocking=False):
                return None, None
            try:
                run_id = uuid4()
                LOGGER.info("Run %s started", run_id)
                result = runner(run_input, config)
                try:
                    save_result(config.run_directory, owner, run_id, result)
                except OSError:
                    LOGGER.error("Could not store run %s", run_id)
                    result.errors.append(
                        "Could not save this result to the local run history."
                    )
                    return None, result
                LOGGER.info("Run %s completed (success=%s)", run_id, result.successful)
                return run_id, result
            finally:
                run_lock.release()

        run_id, result = await run_in_threadpool(execute)
        if result is None:
            return dashboard(
                request,
                409,
                values=values,
                message="An automation is running. Try again after it finishes.",
                **context,
            )
        if run_id is None:
            return dashboard(request, 500, result=result)
        return RedirectResponse(request.url_for("run_detail", run_id=run_id), 303)

    @app.post("/runs", response_class=HTMLResponse)
    async def submit_run(request: Request) -> Response:
        return await handle_submission(request, None)

    @app.post("/runs/{retry_id}/retry", response_class=HTMLResponse)
    async def retry_export(request: Request, retry_id: UUID) -> Response:
        return await handle_submission(request, retry_id)

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_detail(request: Request, run_id: UUID) -> Response:
        return dashboard(request, result=result_for(request, run_id), run_id=run_id)

    @app.get("/runs/{run_id}/employees.csv")
    def download(request: Request, run_id: UUID) -> Response:
        result = result_for(request, run_id)
        if not result.rows:
            raise HTTPException(
                status_code=404, detail="No employee list for this run."
            )
        return Response(
            employee_csv(result),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="employees.csv"',
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()
