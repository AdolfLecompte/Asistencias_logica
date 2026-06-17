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
                COUNT(*) FILTER (WHERE a.estado::text LIKE 'ausente_%')  AS total_ausentes
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


@router.get("/contexto-ia")
async def contexto_ia(profesor: dict = Depends(get_current_profesor)):
    """Resumen completo de datos reales inyectado como contexto al asistente IA."""
    async with get_conn() as conn:
        grupos = await conn.fetch(
            """
            SELECT DISTINCT g.id, g.nombre, g.materia
            FROM grupos g
            WHERE g.id IN (
                SELECT gp.grupo_id FROM grupo_profesores gp WHERE gp.profesor_id = $1
                UNION
                SELECT p.grupo_id FROM profesores p WHERE p.id = $1 AND p.grupo_id IS NOT NULL
            )
            AND g.activo = TRUE
            ORDER BY g.nombre
            """,
            profesor["id"],
        )

        grupos_data = []
        for g in grupos:
            gid = g["id"]

            # ── Resumen acumulado por estudiante ─────────────────────────────
            stats = await conn.fetch(
                """
                SELECT
                    e.id AS estudiante_id,
                    e.nombre || COALESCE(' ' || e.apellido, '') AS nombre,
                    e.username,
                    COUNT(a.id)                                                    AS total_sesiones,
                    COUNT(*) FILTER (WHERE a.estado = 'asistio')                   AS asistieron,
                    COUNT(*) FILTER (WHERE a.estado = 'ausente_justificado')       AS justificados,
                    COUNT(*) FILTER (WHERE a.estado = 'ausente_injustificado')     AS injustificados,
                    COUNT(*) FILTER (WHERE a.estado = 'pendiente_revision')        AS pendientes
                FROM estudiantes e
                JOIN grupo_estudiantes ge ON ge.estudiante_id = e.id AND ge.grupo_id = $1 AND ge.activo = TRUE
                LEFT JOIN asistencias a
                    ON a.estudiante_id = e.id
                    AND a.sesion_id IN (SELECT id FROM sesiones WHERE grupo_id = $1)
                GROUP BY e.id, e.nombre, e.apellido, e.username
                ORDER BY e.nombre
                """,
                gid,
            )

            # ── Detalle por sesión (todas, no solo 5) ────────────────────────
            sesiones = await conn.fetch(
                """
                SELECT s.id, s.descripcion, s.abierta_en, s.activa
                FROM sesiones s
                WHERE s.grupo_id = $1
                ORDER BY s.abierta_en DESC
                """,
                gid,
            )

            total_inscritos = len(stats)
            estudiantes_detalle = []
            en_riesgo = []

            for st in stats:
                total = st["total_sesiones"] or 0
                asist = st["asistieron"] or 0
                pct = round((asist / total * 100) if total else 0, 1)
                detalle = {
                    "nombre": st["nombre"],
                    "username": st["username"],
                    "porcentaje_asistencia": pct,
                    "sesiones_asistidas": asist,
                    "total_sesiones": total,
                    "ausentes_justificados": st["justificados"] or 0,
                    "ausentes_injustificados": st["injustificados"] or 0,
                    "pendientes_revision": st["pendientes"] or 0,
                }
                estudiantes_detalle.append(detalle)
                if pct < 75 and total > 0:
                    en_riesgo.append(st["nombre"])

            # ── Detalle por sesión: quién asistió / faltó ────────────────────
            sesiones_detalle = []
            for s in sesiones:
                sid = s["id"]
                asistencias = await conn.fetch(
                    """
                    SELECT
                        e.nombre || COALESCE(' ' || e.apellido, '') AS nombre,
                        a.estado,
                        ev.resultado_ia AS evidencia_ia
                    FROM asistencias a
                    JOIN estudiantes e ON e.id = a.estudiante_id
                    LEFT JOIN evidencias ev ON ev.asistencia_id = a.id
                    WHERE a.sesion_id = $1
                    ORDER BY e.nombre
                    """,
                    sid,
                )

                por_estado: dict = {
                    "asistio": [],
                    "ausente_justificado": [],
                    "ausente_injustificado": [],
                    "pendiente_revision": [],
                }
                for a in asistencias:
                    estado = a["estado"]
                    entrada = a["nombre"]
                    if a["evidencia_ia"]:
                        entrada += f" (evidencia: {a['evidencia_ia']})"
                    por_estado.setdefault(estado, []).append(entrada)

                sesiones_detalle.append({
                    "id": sid,
                    "descripcion": s["descripcion"],
                    "fecha": s["abierta_en"].isoformat() if s["abierta_en"] else None,
                    "activa": s["activa"],
                    "total_inscritos": total_inscritos,
                    "asistieron": por_estado["asistio"],
                    "ausentes_justificados": por_estado["ausente_justificado"],
                    "ausentes_injustificados": por_estado["ausente_injustificado"],
                    "pendientes_revision": por_estado["pendiente_revision"],
                })

            # ── Evidencias pendientes de revisión ────────────────────────────
            evidencias_pendientes = await conn.fetch(
                """
                SELECT
                    e.nombre || COALESCE(' ' || e.apellido, '') AS estudiante,
                    s.descripcion AS sesion,
                    s.abierta_en AS fecha,
                    ev.resultado_ia,
                    ev.respuesta_ia
                FROM evidencias ev
                JOIN asistencias a ON a.id = ev.asistencia_id
                JOIN estudiantes e ON e.id = a.estudiante_id
                JOIN sesiones s ON s.id = a.sesion_id
                WHERE s.grupo_id = $1 AND a.estado = 'pendiente_revision'
                ORDER BY ev.creado_en DESC
                """,
                gid,
            )

            grupos_data.append({
                "id": gid,
                "nombre": g["nombre"],
                "materia": g["materia"],
                "total_inscritos": total_inscritos,
                "estudiantes": estudiantes_detalle,
                "en_riesgo": en_riesgo,
                "sesiones": sesiones_detalle,
                "evidencias_pendientes": [
                    {
                        "estudiante": ep["estudiante"],
                        "sesion": ep["sesion"],
                        "fecha": ep["fecha"].isoformat() if ep["fecha"] else None,
                        "resultado_ia": ep["resultado_ia"],
                        "respuesta_ia": ep["respuesta_ia"],
                    }
                    for ep in evidencias_pendientes
                ],
            })

    return {"profesor": profesor["nombre"], "grupos": grupos_data}


@router.get("/grupo/{grupo_id}/evidencias")
async def evidencias_grupo(grupo_id: int, profesor: dict = Depends(get_current_profesor)):
    """Retorna todas las evidencias (justificantes) enviadas en un grupo."""
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                ev.id               AS ev_id,
                ev.asistencia_id,
                ev.resultado_ia,
                ev.respuesta_ia,
                ev.creado_en,
                a.estado,
                a.estudiante_id,
                e.nombre || COALESCE(' ' || e.apellido, '') AS estudiante_nombre,
                e.username          AS estudiante_username,
                s.id                AS sesion_id,
                s.descripcion       AS sesion_descripcion,
                s.abierta_en        AS fecha_sesion
            FROM evidencias ev
            JOIN asistencias a ON a.id = ev.asistencia_id
            JOIN estudiantes e ON e.id = a.estudiante_id
            JOIN sesiones s ON s.id = a.sesion_id
            WHERE s.grupo_id = $1
            ORDER BY ev.creado_en DESC
            """,
            grupo_id,
        )
    return [dict(r) for r in rows]


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
