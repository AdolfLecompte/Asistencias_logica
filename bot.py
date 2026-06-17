"""
Bot de Telegram para registro de asistencias.
- Encuestas manuales y automáticas
- Validación de evidencias con Ollama (IA)
- Almacenamiento asíncrono en PostgreSQL
"""
import base64
import logging
import os
import asyncpg
from functools import wraps

import httpx
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

import config

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# DECORADOR: Proteger comandos de admins
# ─────────────────────────────────────────────

def solo_admin(func):
    """Decorator que restringe un comando solo a admins del grupo."""
    @wraps(func)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        chat = update.effective_chat

        # En chats privados o si ADMIN_IDS está vacío → se permite
        if chat.type == "private" or not config.ADMIN_IDS:
            return await func(update, ctx)

        if user.id not in config.ADMIN_IDS:
            await update.message.reply_text("⛔ Solo los administradores pueden usar este comando.")
            return
        return await func(update, ctx)
    return wrapper

# ─────────────────────────────────────────────
# BASE DE DATOS
# ─────────────────────────────────────────────

# Mapeo de estados internos del bot → enum estado_asistencia de la BD
_ESTADO_MAP = {
    "asistio":             "asistio",
    "ausente_valido":      "ausente_justificado",
    "ausente_invalido":    "ausente_injustificado",
    "pendiente_revision":  "pendiente_revision",
}

# Mapeo resultado Ollama → enum resultado_ia de la BD
_RESULTADO_IA_MAP = {
    "ausente_valido":     "valido",
    "ausente_invalido":   "invalido",
    "pendiente_revision": "sin_analisis",
}

async def init_db() -> None:
    """Verifica la conexión con PostgreSQL al arrancar."""
    conn = await asyncpg.connect(config.DATABASE_URL)
    await conn.close()

async def _get_grupo_id(conn) -> int | None:
    """Devuelve el id interno del grupo por su telegram_chat_id."""
    row = await conn.fetchrow(
        "SELECT id FROM grupos WHERE telegram_chat_id = $1",
        str(config.GRUPO_ID),
    )
    return row["id"] if row else None

async def _get_or_create_estudiante(
    conn, user_id: int, username: str | None, nombre: str
) -> int:
    """Busca o crea un estudiante por su telegram_user_id."""
    row = await conn.fetchrow(
        "SELECT id FROM estudiantes WHERE telegram_user_id = $1", str(user_id)
    )
    if row:
        return row["id"]
    return await conn.fetchval(
        "INSERT INTO estudiantes (telegram_user_id, username, nombre) VALUES ($1, $2, $3) RETURNING id",
        str(user_id), username, nombre,
    )

async def get_sesion_activa() -> int | None:
    """Busca el ID de la sesión activa del grupo configurado."""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        grupo_id = await _get_grupo_id(conn)
        if not grupo_id:
            return None
        row = await conn.fetchrow(
            "SELECT id FROM sesiones WHERE grupo_id = $1 AND activa = TRUE ORDER BY id DESC LIMIT 1",
            grupo_id,
        )
        return row["id"] if row else None
    finally:
        await conn.close()

async def crear_sesion(descripcion: str) -> int:
    """Cierra sesiones anteriores, crea una nueva y pre-registra a todos
    los estudiantes del grupo como 'pendiente_revision'."""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        grupo_id = await _get_grupo_id(conn)
        if not grupo_id:
            raise RuntimeError(
                f"El grupo con telegram_chat_id={config.GRUPO_ID} no existe en la BD. "
                "Agrégalo desde el panel de administración."
            )
        await conn.execute(
            "UPDATE sesiones SET activa = FALSE WHERE grupo_id = $1", grupo_id
        )
        sesion_id = await conn.fetchval(
            """INSERT INTO sesiones (grupo_id, descripcion, automatica, activa)
               VALUES ($1, $2, TRUE, TRUE) RETURNING id""",
            grupo_id, descripcion,
        )
        # Pre-registrar a todos los inscritos en el grupo como pendiente_revision
        await conn.execute(
            """INSERT INTO asistencias (sesion_id, estudiante_id, asistio, estado)
               SELECT $1, ge.estudiante_id, FALSE, 'pendiente_revision'::estado_asistencia
               FROM grupo_estudiantes ge
               WHERE ge.grupo_id = $2 AND ge.activo = TRUE
               ON CONFLICT (sesion_id, estudiante_id) DO NOTHING""",
            sesion_id, grupo_id,
        )
        pre = await conn.fetchval(
            "SELECT COUNT(*) FROM asistencias WHERE sesion_id = $1", sesion_id
        )
        logger.info(f"Sesión {sesion_id} creada. {pre} estudiante(s) pre-registrados.")
        return sesion_id
    finally:
        await conn.close()

async def registrar_asistencia(
    sesion_id: int,
    user_id: int,
    username: str | None,
    nombre: str,
    estado: str,
    evidencia_path: str | None = None,
) -> bool:
    """Registra o actualiza la respuesta de un alumno.

    - Si no hay registro previo: INSERT normal.
    - Si el registro existe con estado 'pendiente_revision' (pre-registro
      automático): UPDATE con la respuesta real del alumno.
    - Si el registro existe con otro estado: retorna False (ya respondió).
    """
    estado_db = _ESTADO_MAP.get(estado, "pendiente_revision")
    asistio = estado == "asistio"

    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        est_id = await _get_or_create_estudiante(conn, user_id, username, nombre)

        row = await conn.fetchrow(
            "SELECT id, estado FROM asistencias WHERE sesion_id=$1 AND estudiante_id=$2",
            sesion_id, est_id,
        )

        if row:
            # Ya respondió con un estado real → no se puede modificar
            if row["estado"] != "pendiente_revision":
                return False
            # Era un pre-registro → actualizar con la respuesta real
            asistencia_id = row["id"]
            await conn.execute(
                """UPDATE asistencias
                   SET asistio=$1, estado=$2::estado_asistencia, registrado_en=NOW()
                   WHERE id=$3""",
                asistio, estado_db, asistencia_id,
            )
        else:
            # Estudiante nuevo (no estaba en el roster): INSERT
            asistencia_id = await conn.fetchval(
                """INSERT INTO asistencias (sesion_id, estudiante_id, asistio, estado)
                   VALUES ($1, $2, $3, $4::estado_asistencia) RETURNING id""",
                sesion_id, est_id, asistio, estado_db,
            )
            # Vincularlo al grupo para futuras sesiones
            grupo_row = await conn.fetchrow(
                "SELECT grupo_id FROM sesiones WHERE id = $1", sesion_id
            )
            if grupo_row and grupo_row["grupo_id"]:
                await conn.execute(
                    """INSERT INTO grupo_estudiantes (grupo_id, estudiante_id)
                       VALUES ($1, $2) ON CONFLICT DO NOTHING""",
                    grupo_row["grupo_id"], est_id,
                )

        # Guardar evidencia (reemplaza la anterior si ya existía)
        if evidencia_path:
            resultado_ia = _RESULTADO_IA_MAP.get(estado, "sin_analisis")
            await conn.execute(
                "DELETE FROM evidencias WHERE asistencia_id=$1", asistencia_id
            )
            await conn.execute(
                """INSERT INTO evidencias (asistencia_id, archivo_path, resultado_ia)
                   VALUES ($1, $2, $3::resultado_ia)""",
                asistencia_id, evidencia_path, resultado_ia,
            )

        return True
    finally:
        await conn.close()

# ─────────────────────────────────────────────
# OLLAMA
# ─────────────────────────────────────────────

async def consultar_ollama(prompt: str, imagen_b64: str | None = None) -> str:
    """Se comunica con la API de Ollama de forma asíncrona."""
    payload = {
        "model": config.OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2},
    }
    if imagen_b64:
        payload["images"] = [imagen_b64]

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            r = await client.post(f"{config.OLLAMA_URL}/api/generate", json=payload)
            r.raise_for_status()
            return r.json().get("response", "").strip()
    except httpx.TimeoutException:
        logger.error("Ollama tardó demasiado en responder (timeout).")
        return "TIMEOUT"
    except Exception as e:
        logger.error(f"Error conectando con Ollama: {e}")
        return "ERROR"

async def analizar_evidencia(imagen_b64: str) -> bool | None:
    """
    Pide a la IA que valide si la imagen es una justificación válida.
    Retorna True, False, o None si Ollama no está disponible.
    """
    prompt = (
        "Determina si esta imagen es una evidencia válida de inasistencia "
        "(cita médica, permiso oficial, etc). "
        "Responde SOLO 'VALIDO' o 'INVALIDO' seguido de una razón muy breve."
    )
    respuesta = await consultar_ollama(prompt, imagen_b64)
    logger.info(f"IA analizó evidencia: {respuesta}")

    if respuesta in ("ERROR", "TIMEOUT"):
        return None  # Indica fallo de servicio, no decisión
    return "VALIDO" in respuesta.upper()

# ─────────────────────────────────────────────
# COMANDOS Y HANDLERS
# ─────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *Bot de Asistencia Activo.*\n\n"
        "👤 /unirse — Registrarte como estudiante en este grupo\n"
        "📋 /asistencia [descripción] — Abrir nueva encuesta\n"
        "📊 /reporte — Ver asistencias de la sesión actual\n"
        "🔒 /cerrar — Cerrar la sesión activa\n"
        "🚫 /cancelar — Cancelar envío de justificante en curso\n\n"
        "_Administradores:_\n"
        "📢 /registro — Publicar invitación de registro para el grupo\n"
        "👥 /sync — Ver estudiantes registrados en el grupo",
        parse_mode="Markdown",
    )

async def _registrar_estudiante_en_grupo(user_id: int, username: str | None, nombre: str) -> str:
    """Registra al usuario en estudiantes y lo vincula al grupo configurado.
    Retorna 'nuevo', 'ya_registrado' o 'sin_grupo'."""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        grupo_id = await _get_grupo_id(conn)
        if not grupo_id:
            return "sin_grupo"

        est_id = await _get_or_create_estudiante(conn, user_id, username, nombre)

        row = await conn.fetchrow(
            "SELECT 1 FROM grupo_estudiantes WHERE grupo_id=$1 AND estudiante_id=$2",
            grupo_id, est_id,
        )
        if row:
            return "ya_registrado"

        await conn.execute(
            """INSERT INTO grupo_estudiantes (grupo_id, estudiante_id, activo)
               VALUES ($1, $2, TRUE) ON CONFLICT DO NOTHING""",
            grupo_id, est_id,
        )
        return "nuevo"
    finally:
        await conn.close()


async def cmd_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Permite a un estudiante registrarse escribiendo /unirse."""
    user = update.effective_user
    nombre = f"{user.first_name} {user.last_name or ''}".strip()
    resultado = await _registrar_estudiante_en_grupo(user.id, user.username, nombre)

    if resultado == "nuevo":
        await update.message.reply_text(
            f"✅ ¡Bienvenido, *{nombre}*! Quedaste registrado en el grupo. "
            "A partir de ahora aparecerás en las listas de asistencia.",
            parse_mode="Markdown",
        )
    elif resultado == "ya_registrado":
        await update.message.reply_text(
            f"ℹ️ *{nombre}*, ya estás registrado en el grupo.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "⚠️ No se encontró el grupo en la base de datos. "
            "Pide al administrador que configure el bot."
        )


@solo_admin
async def cmd_registro(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Publica un mensaje con botón inline para que los estudiantes se registren."""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 Registrarme en el grupo", callback_data="registro_unirse")]
    ])
    await update.message.reply_text(
        "📢 *Registro de estudiantes*\n\n"
        "Si eres parte de este grupo y aún no estás registrado, "
        "haz clic en el botón de abajo para que el bot pueda registrar tu asistencia "
        "en las próximas clases.\n\n"
        "_Solo necesitas hacerlo una vez._",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def callback_registro_unirse(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Maneja el clic en el botón de registro."""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    nombre = f"{user.first_name} {user.last_name or ''}".strip()
    resultado = await _registrar_estudiante_en_grupo(user.id, user.username, nombre)

    if resultado == "nuevo":
        await query.message.reply_text(
            f"✅ ¡Listo, *{nombre}*! Quedaste registrado. "
            "Aparecerás en todas las listas de asistencia desde ahora.",
            parse_mode="Markdown",
        )
    elif resultado == "ya_registrado":
        await query.message.reply_text(
            f"ℹ️ *{nombre}*, ya estabas registrado. No se hizo ningún cambio.",
            parse_mode="Markdown",
        )
    else:
        await query.message.reply_text(
            "⚠️ Ocurrió un error al registrarte. Contacta al administrador."
        )


@solo_admin
async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Lista todos los estudiantes registrados en el grupo."""
    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        grupo_id = await _get_grupo_id(conn)
        if not grupo_id:
            await update.message.reply_text("⚠️ El grupo no está configurado en la BD.")
            return

        filas = await conn.fetch(
            """SELECT e.nombre, e.apellido, e.username, ge.inscrito_en
               FROM grupo_estudiantes ge
               JOIN estudiantes e ON e.id = ge.estudiante_id
               WHERE ge.grupo_id = $1 AND ge.activo = TRUE
               ORDER BY e.nombre""",
            grupo_id,
        )
    finally:
        await conn.close()

    if not filas:
        await update.message.reply_text(
            "👥 No hay estudiantes registrados aún.\n"
            "Usa /registro para publicar el botón de inscripción."
        )
        return

    lineas = []
    for f in filas:
        apellido = f["apellido"] or ""
        nombre_completo = f"{f['nombre']} {apellido}".strip()
        user_part = f"@{f['username']}" if f["username"] else "sin @"
        lineas.append(f"• {nombre_completo} ({user_part})")

    texto = "\n".join(lineas)
    await update.message.reply_text(
        f"👥 *Estudiantes registrados ({len(filas)}):*\n\n{texto}",
        parse_mode="Markdown",
    )


async def cmd_cancelar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "esperando_sesion" in ctx.user_data:
        del ctx.user_data["esperando_sesion"]
        await update.message.reply_text("❎ Envío de justificante cancelado.")
    else:
        await update.message.reply_text("No tienes ningún envío pendiente.")

@solo_admin
async def cmd_asistencia(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    descripcion = " ".join(ctx.args) if ctx.args else "Clase del día"
    sesion_id = await crear_sesion(descripcion)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Asistiré", callback_data="si"),
            InlineKeyboardButton("❌ No asistiré", callback_data="no"),
        ]
    ])

    await update.message.reply_text(
        f"📋 *Nueva Sesión:* {descripcion}\nID: `{sesion_id}`\n\n¿Vas a asistir?",
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

async def callback_respuesta(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    # Responder inmediatamente para evitar el timeout de 30 s de Telegram
    await query.answer()

    user = query.from_user
    nombre = f"{user.first_name} {user.last_name or ''}".strip()

    sesion_id = await get_sesion_activa()

    if not sesion_id:
        await query.message.reply_text("⚠️ No hay ninguna sesión abierta ahora mismo.")
        return

    if query.data == "si":
        registrado = await registrar_asistencia(sesion_id, user.id, user.username, nombre, "asistio")
        if registrado:
            await query.message.reply_text(f"✅ Asistencia registrada para *{nombre}*", parse_mode="Markdown")
        else:
            await query.message.reply_text("⚠️ Ya tienes un registro en esta sesión. No se puede modificar.")
    else:
        # Iniciar flujo de justificante solo si no hay registro real previo
        conn = await asyncpg.connect(config.DATABASE_URL)
        try:
            est = await conn.fetchrow(
                "SELECT id FROM estudiantes WHERE telegram_user_id = $1", str(user.id)
            )
            registro = (
                await conn.fetchrow(
                    "SELECT id, estado FROM asistencias WHERE sesion_id=$1 AND estudiante_id=$2",
                    sesion_id, est["id"],
                )
                if est else None
            )
        finally:
            await conn.close()

        # Bloquear solo si ya tiene un estado real (no el pre-registro automático)
        if registro and registro["estado"] != "pendiente_revision":
            await query.message.reply_text("⚠️ Ya tienes un registro en esta sesión. No se puede modificar.")
            return

        ctx.user_data["esperando_sesion"] = sesion_id
        await query.message.reply_text(
            f"📎 *{nombre}*, por favor envía una foto de tu justificante para validar tu ausencia.",
            parse_mode="Markdown",
        )

async def recibir_imagen(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user

    # Solo procesar si el usuario está en flujo de justificante
    if "esperando_sesion" not in ctx.user_data:
        return

    sesion_id = ctx.user_data["esperando_sesion"]
    nombre = f"{user.first_name} {user.last_name or ''}".strip()

    msg = await update.message.reply_text("⌛ Analizando evidencia con IA...")

    # Descargar y codificar la imagen (resolución más alta)
    foto = await update.message.photo[-1].get_file()
    bytes_img = await foto.download_as_bytearray()
    img_b64 = base64.b64encode(bytes_img).decode("utf-8")

    es_valida = await analizar_evidencia(img_b64)

    if es_valida is None:
        # Ollama no disponible
        await msg.edit_text(
            "⚠️ El servicio de validación no está disponible. "
            "Tu evidencia fue guardada y será revisada manualmente."
        )
        estado = "pendiente_revision"
    else:
        estado = "ausente_valido" if es_valida else "ausente_invalido"

    # Guardar archivo localmente
    path = os.path.join(config.EVIDENCIAS_DIR, f"{sesion_id}_{user.id}.jpg")
    with open(path, "wb") as f:
        f.write(bytes_img)

    registrado = await registrar_asistencia(sesion_id, user.id, user.username, nombre, estado, path)

    if not registrado:
        await msg.edit_text("⚠️ Ya tienes un registro en esta sesión. No se puede modificar.")
        del ctx.user_data["esperando_sesion"]
        return

    if es_valida is not None:
        texto_res = (
            "✅ Justificante *aceptado*. Tu ausencia quedó registrada como justificada."
            if es_valida
            else "❌ Justificante *no válido*. Se registró como falta injustificada."
        )
        await msg.edit_text(texto_res, parse_mode="Markdown")

    # Limpiar estado del usuario
    del ctx.user_data["esperando_sesion"]

@solo_admin
async def cmd_reporte(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sesion_id = await get_sesion_activa()
    if not sesion_id:
        await update.message.reply_text("❌ No hay sesión activa.")
        return

    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        filas = await conn.fetch(
            """SELECT e.nombre, a.estado
               FROM asistencias a
               JOIN estudiantes e ON e.id = a.estudiante_id
               WHERE a.sesion_id = $1
               ORDER BY e.nombre""",
            sesion_id,
        )
    finally:
        await conn.close()

    if not filas:
        await update.message.reply_text("Nadie ha respondido aún.")
        return

    # Agrupar por estado para lectura más clara
    lineas = [f"• {f[0]}: `{f[1]}`" for f in filas]
    reporte = "\n".join(lineas)
    await update.message.reply_text(
        f"📊 *Reporte — Sesión {sesion_id}:*\n\n{reporte}",
        parse_mode="Markdown",
    )

@solo_admin
async def cmd_cerrar(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    sesion_id = await get_sesion_activa()
    if not sesion_id:
        await update.message.reply_text("⚠️ No hay ninguna sesión activa que cerrar.")
        return

    conn = await asyncpg.connect(config.DATABASE_URL)
    try:
        await conn.execute(
            "UPDATE sesiones SET activa = FALSE, cerrada_en = NOW() WHERE id = $1",
            sesion_id,
        )
    finally:
        await conn.close()

    await update.message.reply_text(
        f"🔒 Sesión {sesion_id} cerrada. No se aceptan más registros."
    )

# ─────────────────────────────────────────────
# PROGRAMADOR (JobQueue nativo de PTB)
# ─────────────────────────────────────────────

async def lanzar_asistencia_automatica(context: ContextTypes.DEFAULT_TYPE):
    """Función disparada por el scheduler automático."""
    descripcion = f"Clase Automática: {config.NOMBRE_MATERIA}"
    sesion_id = await crear_sesion(descripcion)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Asistiré", callback_data="si"),
            InlineKeyboardButton("❌ No asistiré", callback_data="no"),
        ]
    ])

    await context.bot.send_message(
        chat_id=config.GRUPO_ID,
        text=(
            f"⏰ *ENCUESTA AUTOMÁTICA*\n"
            f"Sesión: {descripcion}\n"
            f"ID: `{sesion_id}`\n\n"
            "¿Asistirás a clase hoy?"
        ),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )

# ─────────────────────────────────────────────
# CONSTRUCCIÓN DE LA APP
# ─────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Loguea todos los errores del bot, incluyendo fallos de jobs."""
    logger.error("Excepción no controlada:", exc_info=context.error)


def create_app() -> Application:
    """Construye y configura la aplicación."""
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("unirse",     cmd_unirse))
    app.add_handler(CommandHandler("registro",   cmd_registro))
    app.add_handler(CommandHandler("sync",       cmd_sync))
    app.add_handler(CommandHandler("asistencia", cmd_asistencia))
    app.add_handler(CommandHandler("reporte",    cmd_reporte))
    app.add_handler(CommandHandler("cerrar",     cmd_cerrar))
    app.add_handler(CommandHandler("cancelar",   cmd_cancelar))
    app.add_handler(CallbackQueryHandler(callback_registro_unirse, pattern="^registro_unirse$"))
    app.add_handler(CallbackQueryHandler(callback_respuesta,       pattern="^(si|no)$"))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_imagen))
    app.add_error_handler(error_handler)

    return app
