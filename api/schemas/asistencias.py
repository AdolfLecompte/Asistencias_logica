from datetime import datetime
from typing import Literal

from pydantic import BaseModel

EstadoAsistencia = Literal[
    "asistio",
    "ausente_justificado",
    "ausente_injustificado",
    "pendiente_revision",
]


class EvidenciaResponse(BaseModel):
    id: int
    archivo_path: str
    resultado_ia: str
    respuesta_ia: str | None
    analizado_en: datetime | None
    creado_en: datetime


class HistorialItem(BaseModel):
    id: int
    profesor_nombre: str
    estado_anterior: str
    estado_nuevo: str
    motivo: str | None
    modificado_en: datetime


class AsistenciaResponse(BaseModel):
    id: int
    sesion_id: int
    estudiante_id: int
    estudiante_nombre: str
    estudiante_username: str | None
    asistio: bool
    estado: str
    registrado_en: datetime
    modificado_en: datetime | None
    modificado_por_nombre: str | None
    evidencia: EvidenciaResponse | None = None


class AsistenciaDetalleResponse(AsistenciaResponse):
    historial: list[HistorialItem] = []


class ModificarEstadoRequest(BaseModel):
    estado_nuevo: EstadoAsistencia
    motivo: str | None = None
