from fastapi import APIRouter, Depends, HTTPException, Query

from api.core.database import get_conn
from api.dependencies.auth import get_current_profesor
from api.schemas.reportes import (
    ReporteEstudianteResponse,
    ReporteGrupoResponse,
    ReporteSesionResponse,
)

router = APIRouter(prefix="/reportes", tags=["Reportes"])


@router.get("/sesion/{sesion_id}", response_model=ReporteSesionResponse)
async def reporte_sesion(sesion_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        sesion = await conn.fetchrow(
            "SELECT id, grupo_id, descripcion, abierta_en, cerrada_en FROM sesiones WHERE id = $1",
            sesion_id,
        )
        if not sesion:
            raise HTTPException(status_code=404, detail="Sesión no encontrada.")

        # Total de inscritos en el grupo de la sesión
        total_inscritos = await conn.fetchval(
            "SELECT COUNT(*) FROM grupo_estudiantes WHERE grupo_id = $1 AND activo = TRUE",
            sesion["grupo_id"],
        )

        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE estado = 'asistio')               AS asistieron,
                COUNT(*) FILTER (WHERE estado = 'ausente_justificado')   AS justificados,
                COUNT(*) FILTER (WHERE estado = 'ausente_injustificado') AS injustificados,
                COUNT(*) FILTER (WHERE estado = 'pendiente_revision')    AS pendientes
            FROM asistencias WHERE sesion_id = $1
            """,
            sesion_id,
        )

        asistencias_rows = await conn.fetch(
            """
            SELECT
                a.id, a.estado, a.asistio, a.registrado_en,
                e.nombre || COALESCE(' ' || e.apellido, '') AS nombre,
                e.username
            FROM asistencias a
            JOIN estudiantes e ON e.id = a.estudiante_id
            WHERE a.sesion_id = $1
            ORDER BY e.nombre
            """,
            sesion_id,
        )

    total_asistieron = stats["asistieron"] or 0
    porcentaje = round((total_asistieron / total_inscritos * 100) if total_inscritos else 0, 1)

    return ReporteSesionResponse(
        sesion_id=sesion["id"],
        descripcion=sesion["descripcion"],
        abierta_en=sesion["abierta_en"],
        cerrada_en=sesion["cerrada_en"],
        total_inscritos=total_inscritos,
        total_asistieron=total_asistieron,
        total_ausentes_justificados=stats["justificados"] or 0,
        total_ausentes_injustificados=stats["injustificados"] or 0,
        total_pendientes=stats["pendientes"] or 0,
        porcentaje_asistencia=porcentaje,
        asistencias=[dict(r) for r in asistencias_rows],
    )


@router.get("/grupo/{grupo_id}", response_model=ReporteGrupoResponse)
async def reporte_grupo(grupo_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        grupo = await conn.fetchrow(
            "SELECT id, nombre, materia FROM grupos WHERE id = $1",
            grupo_id,
        )
        if not grupo:
            raise HTTPException(status_code=404, detail="Grupo no encontrado.")

        total_inscritos = await conn.fetchval(
            "SELECT COUNT(*) FROM grupo_estudiantes WHERE grupo_id = $1 AND activo = TRUE",
            grupo_id,
        )

        rows = await conn.fetch(
            """
            SELECT
                s.id            AS sesion_id,
                s.descripcion,
                s.abierta_en    AS fecha,
                COUNT(*) FILTER (WHERE a.estado = 'asistio')       AS total_asistieron,
                COUNT(*) FILTER (WHERE a.estado LIKE 'ausente_%')  AS total_ausentes
            FROM sesiones s
            LEFT JOIN asistencias a ON a.sesion_id = s.id
            WHERE s.grupo_id = $1
            GROUP BY s.id
            ORDER BY s.abierta_en
            """,
            grupo_id,
        )

    sesiones = []
    for r in rows:
        asistieron = r["total_asistieron"] or 0
        porcentaje = round((asistieron / total_inscritos * 100) if total_inscritos else 0, 1)
        sesiones.append({
            "sesion_id": r["sesion_id"],
            "descripcion": r["descripcion"],
            "fecha": r["fecha"],
            "total_asistieron": asistieron,
            "total_ausentes": r["total_ausentes"] or 0,
            "porcentaje_asistencia": porcentaje,
        })

    return ReporteGrupoResponse(
        grupo_id=grupo["id"],
        grupo_nombre=grupo["nombre"],
        materia=grupo["materia"],
        sesiones=sesiones,
    )


@router.get("/estudiante/{estudiante_id}", response_model=ReporteEstudianteResponse)
async def reporte_estudiante(
    estudiante_id: int,
    grupo_id: int = Query(..., description="ID del grupo para filtrar"),
    profesor: dict = Depends(get_current_profesor),
):
    async with get_conn() as conn:
        estudiante = await conn.fetchrow(
            "SELECT id, nombre, apellido FROM estudiantes WHERE id = $1",
            estudiante_id,
        )
        if not estudiante:
            raise HTTPException(status_code=404, detail="Estudiante no encontrado.")

        grupo = await conn.fetchrow(
            "SELECT id, nombre FROM grupos WHERE id = $1",
            grupo_id,
        )
        if not grupo:
            raise HTTPException(status_code=404, detail="Grupo no encontrado.")

        stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*)                                                   AS total_sesiones,
                COUNT(*) FILTER (WHERE a.estado = 'asistio')              AS asistieron,
                COUNT(*) FILTER (WHERE a.estado = 'ausente_justificado')  AS justificados,
                COUNT(*) FILTER (WHERE a.estado = 'ausente_injustificado') AS injustificados,
                COUNT(*) FILTER (WHERE a.estado = 'pendiente_revision')   AS pendientes
            FROM asistencias a
            JOIN sesiones s ON s.id = a.sesion_id
            WHERE a.estudiante_id = $1 AND s.grupo_id = $2
            """,
            estudiante_id,
            grupo_id,
        )

    total = stats["total_sesiones"] or 0
    asistieron = stats["asistieron"] or 0
    porcentaje = round((asistieron / total * 100) if total else 0, 1)
    nombre_completo = f"{estudiante['nombre']} {estudiante['apellido'] or ''}".strip()

    return ReporteEstudianteResponse(
        estudiante_id=estudiante_id,
        nombre=nombre_completo,
        grupo_id=grupo_id,
        grupo_nombre=grupo["nombre"],
        total_sesiones=total,
        total_asistieron=asistieron,
        total_ausentes_justificados=stats["justificados"] or 0,
        total_ausentes_injustificados=stats["injustificados"] or 0,
        total_pendientes=stats["pendientes"] or 0,
        porcentaje_asistencia=porcentaje,
    )
