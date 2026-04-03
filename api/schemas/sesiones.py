from datetime import datetime

from pydantic import BaseModel


class SesionCreate(BaseModel):
    descripcion: str | None = None


class SesionResponse(BaseModel):
    id: int
    grupo_id: int
    descripcion: str | None
    automatica: bool
    activa: bool
    abierta_en: datetime
    cerrada_en: datetime | None
    creada_por: int | None

    # Stats calculadas en la query
    total_asistencias: int = 0
    total_ausentes: int = 0
    total_pendientes: int = 0
