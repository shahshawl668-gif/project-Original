from fastapi import FastAPI, Request
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

# ✅ FINAL CORS CONFIG (STRICT + WORKING)
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "https://peopleopslab.in",
    "https://www.peopleopslab.in",
    "https://project-original.vercel.app",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,  # 🔥 IMPORTANT FIX
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ FIX: Handle OPTIONS (preflight) explicitly (prevents 403)
@app.middleware("http")
async def handle_preflight(request: Request, call_next):
    if request.method == "OPTIONS":
        return JSONResponse(content={"ok": True})
    response = await call_next(request)
    return response

# ------------------ EXCEPTION HANDLING ------------------

@app.exception_handler(HTTPException)
async def http_exception_envelope(_, exc: HTTPException):
    body = err_payload(exc.detail)
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

# ------------------ STARTUP ------------------

def _ensure_system_user(db) -> None:
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

# ------------------ HEALTH ------------------

@app.get("/api/health")
def health():
    from app.envelope import ok
    return ok({"status": "ok"})

# ------------------ ROUTES ------------------

app.include_router(api_router, prefix="/api")
