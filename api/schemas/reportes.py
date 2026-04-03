from datetime import datetime

from pydantic import BaseModel


class ReporteSesionResponse(BaseModel):
    sesion_id: int
    descripcion: str | None
    abierta_en: datetime
    cerrada_en: datetime | None
    total_inscritos: int
    total_asistieron: int
    total_ausentes_justificados: int
    total_ausentes_injustificados: int
    total_pendientes: int
    porcentaje_asistencia: float
    asistencias: list[dict]


class PuntoReporteGrupo(BaseModel):
    sesion_id: int
    descripcion: str | None
    fecha: datetime
    total_asistieron: int
    total_ausentes: int
    porcentaje_asistencia: float


class ReporteGrupoResponse(BaseModel):
    grupo_id: int
    grupo_nombre: str
    materia: str | None
    sesiones: list[PuntoReporteGrupo]


class ReporteEstudianteResponse(BaseModel):
    estudiante_id: int
    nombre: str
    grupo_id: int
    grupo_nombre: str
    total_sesiones: int
    total_asistieron: int
    total_ausentes_justificados: int
    total_ausentes_injustificados: int
    total_pendientes: int
    porcentaje_asistencia: float
