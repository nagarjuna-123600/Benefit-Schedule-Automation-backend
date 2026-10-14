
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db
from routers.documents import router as documents_router
from routers.benefits import router as benefits_router
from routers.search import router as search_router


app = FastAPI(
    title="Benefit Schedule Automation API",
    description=(
        "Upload insurance benefit schedules, extract structured "
        "benefits with Ollama, and store documents and embeddings "
        "in PostgreSQL."
    ),
    version="1.0.0",
)


# CORS configuration for the React/Vite frontend
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


@app.on_event("startup")
def startup():
    init_db()


app.include_router(documents_router)
app.include_router(benefits_router)
app.include_router(search_router)


# @app.get("/health", tags=["Health"])
# def health():
#     return {
#         "status": "ok",
#         "service": "Benefit Schedule Automation API",
#     }
