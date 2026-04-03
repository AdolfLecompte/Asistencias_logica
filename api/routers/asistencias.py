import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from api.core.config import settings
from api.core.database import get_conn
from api.dependencies.auth import get_current_profesor
from api.schemas.asistencias import (
    AsistenciaDetalleResponse,
    AsistenciaResponse,
    ModificarEstadoRequest,
)

router = APIRouter(tags=["Asistencias"])


@router.get("/sesiones/{sesion_id}/asistencias", response_model=list[AsistenciaResponse])
async def listar_asistencias(sesion_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        rows = await conn.fetch(
            """
            SELECT
                a.id, a.sesion_id, a.estudiante_id,
                e.nombre || COALESCE(' ' || e.apellido, '')  AS estudiante_nombre,
                e.username                                    AS estudiante_username,
                a.asistio, a.estado, a.registrado_en,
                a.modificado_en,
                pm.nombre || COALESCE(' ' || pm.apellido, '') AS modificado_por_nombre,
                ev.id           AS ev_id,
                ev.archivo_path AS ev_archivo_path,
                ev.resultado_ia AS ev_resultado_ia,
                ev.respuesta_ia AS ev_respuesta_ia,
                ev.analizado_en AS ev_analizado_en,
                ev.creado_en    AS ev_creado_en
            FROM asistencias a
            JOIN estudiantes e ON e.id = a.estudiante_id
            LEFT JOIN profesores pm ON pm.id = a.modificado_por
            LEFT JOIN evidencias ev ON ev.asistencia_id = a.id
            WHERE a.sesion_id = $1
            ORDER BY e.nombre
            """,
            sesion_id,
        )

    return [_map_asistencia(r) for r in rows]


@router.get("/asistencias/{asistencia_id}", response_model=AsistenciaDetalleResponse)
async def obtener_asistencia(asistencia_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                a.id, a.sesion_id, a.estudiante_id,
                e.nombre || COALESCE(' ' || e.apellido, '')   AS estudiante_nombre,
                e.username                                     AS estudiante_username,
                a.asistio, a.estado, a.registrado_en,
                a.modificado_en,
                pm.nombre || COALESCE(' ' || pm.apellido, '') AS modificado_por_nombre,
                ev.id           AS ev_id,
                ev.archivo_path AS ev_archivo_path,
                ev.resultado_ia AS ev_resultado_ia,
                ev.respuesta_ia AS ev_respuesta_ia,
                ev.analizado_en AS ev_analizado_en,
                ev.creado_en    AS ev_creado_en
            FROM asistencias a
            JOIN estudiantes e ON e.id = a.estudiante_id
            LEFT JOIN profesores pm ON pm.id = a.modificado_por
            LEFT JOIN evidencias ev ON ev.asistencia_id = a.id
            WHERE a.id = $1
            """,
            asistencia_id,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Asistencia no encontrada.")

        historial_rows = await conn.fetch(
            """
            SELECT hm.id, hm.estado_anterior, hm.estado_nuevo, hm.motivo, hm.modificado_en,
                   p.nombre || COALESCE(' ' || p.apellido, '') AS profesor_nombre
            FROM historial_modificaciones hm
            JOIN profesores p ON p.id = hm.profesor_id
            WHERE hm.asistencia_id = $1
            ORDER BY hm.modificado_en
            """,
            asistencia_id,
        )

    base = _map_asistencia(row)
    base["historial"] = [dict(h) for h in historial_rows]
    return base


@router.patch("/asistencias/{asistencia_id}/estado", response_model=AsistenciaResponse)
async def modificar_estado(
    asistencia_id: int,
    body: ModificarEstadoRequest,
    profesor: dict = Depends(get_current_profesor),
):
    async with get_conn() as conn:
        # Verificar que existe y obtener estado actual
        actual = await conn.fetchrow(
            "SELECT id, estado FROM asistencias WHERE id = $1",
            asistencia_id,
        )
        if not actual:
            raise HTTPException(status_code=404, detail="Asistencia no encontrada.")

        if actual["estado"] == body.estado_nuevo:
            raise HTTPException(status_code=400, detail="El estado nuevo es igual al actual.")

        asistio_nuevo = body.estado_nuevo == "asistio"

        async with conn.transaction():
            await conn.execute(
                """
                UPDATE asistencias
                SET estado = $1, asistio = $2, modificado_en = NOW(), modificado_por = $3
                WHERE id = $4
                """,
                body.estado_nuevo,
                asistio_nuevo,
                profesor["id"],
                asistencia_id,
            )
            await conn.execute(
                """
                INSERT INTO historial_modificaciones
                    (asistencia_id, profesor_id, estado_anterior, estado_nuevo, motivo)
                VALUES ($1, $2, $3, $4, $5)
                """,
                asistencia_id,
                profesor["id"],
                actual["estado"],
                body.estado_nuevo,
                body.motivo,
            )

        # Retornar el registro actualizado
        row = await conn.fetchrow(
            """
            SELECT
                a.id, a.sesion_id, a.estudiante_id,
                e.nombre || COALESCE(' ' || e.apellido, '')   AS estudiante_nombre,
                e.username                                     AS estudiante_username,
                a.asistio, a.estado, a.registrado_en,
                a.modificado_en,
                pm.nombre || COALESCE(' ' || pm.apellido, '') AS modificado_por_nombre,
                ev.id           AS ev_id,
                ev.archivo_path AS ev_archivo_path,
                ev.resultado_ia AS ev_resultado_ia,
                ev.respuesta_ia AS ev_respuesta_ia,
                ev.analizado_en AS ev_analizado_en,
                ev.creado_en    AS ev_creado_en
            FROM asistencias a
            JOIN estudiantes e ON e.id = a.estudiante_id
            LEFT JOIN profesores pm ON pm.id = a.modificado_por
            LEFT JOIN evidencias ev ON ev.asistencia_id = a.id
            WHERE a.id = $1
            """,
            asistencia_id,
        )
    return _map_asistencia(row)


@router.get("/evidencias/{asistencia_id}/archivo")
async def descargar_evidencia(asistencia_id: int, profesor: dict = Depends(get_current_profesor)):
    async with get_conn() as conn:
        row = await conn.fetchrow(
            "SELECT archivo_path FROM evidencias WHERE asistencia_id = $1",
            asistencia_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Evidencia no encontrada.")

    path = row["archivo_path"]
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Archivo no encontrado en disco.")

    return FileResponse(path, media_type="image/jpeg")


# ── Helpers ───────────────────────────────────────────────────

def _map_asistencia(row) -> dict:
    d = dict(row)
    evidencia = None
    if d.get("ev_id"):
        evidencia = {
            "id": d.pop("ev_id"),
            "archivo_path": d.pop("ev_archivo_path"),
            "resultado_ia": d.pop("ev_resultado_ia"),
            "respuesta_ia": d.pop("ev_respuesta_ia"),
            "analizado_en": d.pop("ev_analizado_en"),
            "creado_en": d.pop("ev_creado_en"),
        }
    else:
        for k in ("ev_id", "ev_archivo_path", "ev_resultado_ia", "ev_respuesta_ia", "ev_analizado_en", "ev_creado_en"):
            d.pop(k, None)
    d["evidencia"] = evidencia
    return d
