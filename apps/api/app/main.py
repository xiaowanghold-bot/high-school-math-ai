from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routes.curriculum import router as curriculum_router
from app.routes.exam_papers import router as exam_papers_router
from app.routes.imports import router as imports_router
from app.routes.lesson_plans import router as lesson_plans_router
from app.routes.library import router as library_router
from app.routes.model_operations import router as model_operations_router
from app.routes.questions import router as questions_router
from app.routes.question_similarity import router as question_similarity_router
from app.routes.solutions import router as solutions_router


settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "environment": settings.environment}


app.include_router(curriculum_router, prefix="/api/v1")
app.include_router(imports_router, prefix="/api/v1")
app.include_router(questions_router, prefix="/api/v1")
app.include_router(question_similarity_router, prefix="/api/v1")
app.include_router(lesson_plans_router, prefix="/api/v1")
app.include_router(exam_papers_router, prefix="/api/v1")
app.include_router(solutions_router, prefix="/api/v1")
app.include_router(library_router, prefix="/api/v1")
app.include_router(model_operations_router, prefix="/api/v1")
