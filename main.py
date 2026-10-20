
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers.underwriting import router as underwriting_router
from routers.documents import (
    router as documents_router,
    projects_router,
)

from routers.benefits import router as benefits_router
from routers.search import router as search_router
from routers.proposals import router as proposals_router


# =====================================================
# 1. FASTAPI APPLICATION
# =====================================================

app = FastAPI(
    title="CANOPY - Benefit Schedule Automation API",
    description=(
        "Manage insurance benefit schedule projects, "
        "upload and version documents, extract structured "
        "benefits using Ollama, and store documents and "
        "embeddings in PostgreSQL with pgvector."
    ),
    version="1.1.0",
)


# =====================================================
# 2. CORS CONFIGURATION
# =====================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================
# 3. DATABASE INITIALIZATION
# =====================================================

@app.on_event("startup")
def startup():
    init_db()
    print("CANOPY database initialized successfully.")


# =====================================================
# 4. REGISTER API ROUTERS
# =====================================================

# Document upload, extraction, preview and download
app.include_router(documents_router)

# Project listing, reopening and version management
app.include_router(projects_router)

# Extracted benefits and validations
app.include_router(benefits_router)

# Semantic document search
app.include_router(search_router)

app.include_router(underwriting_router)
app.include_router(proposals_router)
# =====================================================
# 5. HEALTH CHECK
# =====================================================

@app.get("/health", tags=["Health"])
def health():
    return {
        "status": "ok",
        "service": "CANOPY - Benefit Schedule Automation API",
        "version": "1.1.0",
        "database": "PostgreSQL",
        "vector_store": "pgvector",
    }