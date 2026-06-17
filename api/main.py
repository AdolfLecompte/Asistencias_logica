from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.core.config import settings
from api.core.database import close_pool, create_pool
from api.routers import asistencias, auth, estudiantes, grupos, profesores, reportes, sesiones


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_pool()
    yield
    await close_pool()


app = FastAPI(
    title="Bot Asistencias API",
    version="1.0.0",
    description="API REST para el dashboard del bot de asistencias.",
    lifespan=lifespan,
)

_allow_all = settings.CORS_ORIGINS == ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=not _allow_all,  # credentials no puede usarse con "*"
    allow_methods=["*"],
    allow_headers=["*"],
)

PREFIX = "/api/v1"

app.include_router(auth.router,         prefix=PREFIX)
app.include_router(grupos.router,       prefix=PREFIX)
app.include_router(sesiones.router,     prefix=PREFIX)
app.include_router(asistencias.router,  prefix=PREFIX)
app.include_router(estudiantes.router,  prefix=PREFIX)
app.include_router(reportes.router,     prefix=PREFIX)
app.include_router(profesores.router,   prefix=PREFIX)
