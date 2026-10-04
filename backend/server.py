"""
LLMFlowAgent backend service entry point.

Responsibilities:
1. Create the FastAPI application and configure CORS.
2. Manage the database connection lifecycle.
3. Register domain-specific routers from the routes package.
4. Register LangServe model-chain routes directly on the application instance.
"""

# Set OpenBLAS thread limits before importing numpy or pm4py to avoid allocation failures on Windows.
import os
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

# Load backend/.env for local development. Deployed environments inject variables
# directly, so startup does not require an .env file.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from langserve import add_routes

from deps import db
from routes import (
    collection_router,
    workflow_router,
    rubric_router,
    chain_router,
    run_router,
)
from src.orchestration.storage import ensure_orchestration_schema

# LangServe model-chain routes must be bound directly to the app; chain definitions live in generation.chains.
from src.generation.chains.custom_api import custom_api_chain
from src.generation.chains.write_dag import write_dag_chain
from src.generation.chains.write_xml import write_xml_chain

# ----------------------------------------------------------------------
# Database lifecycle managed through lifespan instead of the deprecated on_event API.
# ----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prefer environment variables while retaining the existing local-development defaults.
    db_config = {
        "dbname": os.getenv("DB_NAME", "llmflowagent"),
        "user": os.getenv("DB_USER", "postgres"),
        "password": os.getenv("DB_PASSWORD", ""),
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "5432")),
    }
    db.connect(**db_config)
    ensure_orchestration_schema()
    try:
        yield
    finally:
        db.close()


app = FastAPI(title="Workflow Service", lifespan=lifespan)

# CORS defaults to "*" for local or internal use. For separate frontend and backend
# domains in production, provide a comma-separated allowlist, for example:
#   CORS_ORIGINS=https://your-domain.com,https://www.your-domain.com
_cors_origins = [
    _o.strip() for _o in os.getenv("CORS_ORIGINS", "*").split(",") if _o.strip()
] or ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Global exception handling
# ----------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc):
    body = await request.body()

    print("===== 422 Validation Error =====")
    print("URL:", request.url)
    print("Errors:", exc.errors())
    print("Body:", body.decode("utf-8", errors="ignore"))
    print("================================")

    return JSONResponse(
        status_code=422,
        content={
            "code": 422,
            "msg": "Request validation failed",
            "errors": exc.errors(),
            "body": body.decode("utf-8", errors="ignore"),
        },
    )


# ----------------------------------------------------------------------
# Route registration
# ----------------------------------------------------------------------
app.include_router(collection_router)
app.include_router(workflow_router)
app.include_router(chain_router)
app.include_router(rubric_router)
app.include_router(run_router)

# LangServe model-chain routes must be bound directly to the app instance.
add_routes(app, custom_api_chain, path="/workflow/api/custom")
add_routes(app, write_dag_chain, path="/workflow/write_dag")
add_routes(app, write_xml_chain, path="/workflow/write_xml")


@app.get("/")
async def redirect_root_to_docs():
    return RedirectResponse("/docs")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=os.getenv("RELOAD", "false").lower() == "true",
    )
