from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import Base, SessionLocal, apply_column_patches, engine
from app.deps import SYSTEM_USER_EMAIL
from app.models import User
from app.envelope import err_payload
from app.routers import api_router
from app.seed import seed_reference_data

app = FastAPI(title="India Payroll Validation API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_envelope(_, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, list):
        body = err_payload(detail)
    else:
        body = err_payload(detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "data": None, "error": body},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_envelope(_, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "data": None,
            "error": err_payload(exc.errors(), code="validation_error"),
        },
    )


def _ensure_system_user(db) -> None:
    """Create the built-in system user if it doesn't exist yet."""
    existing = db.query(User).filter(User.email == SYSTEM_USER_EMAIL).first()
    if existing:
        if getattr(existing, "role", None) != "system":
            existing.role = "system"
            db.add(existing)
            db.commit()
        return
    user = User(
        email=SYSTEM_USER_EMAIL,
        password_hash="__no_auth__",
        company_name="PayrollCheck",
        role="system",
    )
    db.add(user)
    db.commit()


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    apply_column_patches()
    db = SessionLocal()
    try:
        seed_reference_data(db)
        _ensure_system_user(db)
    finally:
        db.close()


@app.get("/api/health")
def health():
    from app.envelope import ok

    return ok({"status": "ok"})


app.include_router(api_router, prefix="/api")
