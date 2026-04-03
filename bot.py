"""
Bot de Telegram para registro de asistencias.
- Encuestas manuales y automáticas
- Validación de evidencias con Ollama (IA)
- Almacenamiento asíncrono en SQLite
"""
import base64
import logging
import os
import sqlite3
import aiosqlite
from datetime import datetime
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

def init_db() -> None:
    """Crea las tablas de forma síncrona al arrancar."""
    conn = sqlite3.connect(config.DB_FILE)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha       TEXT NOT NULL,
            descripcion TEXT,
            activa      INTEGER DEFAULT 1
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS asistencias (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id      INTEGER NOT NULL,
            user_id        INTEGER NOT NULL,
            username       TEXT,
            nombre         TEXT,
            estado         TEXT NOT NULL,
            evidencia_path TEXT,
            timestamp      TEXT,
            FOREIGN KEY (sesion_id) REFERENCES sesiones(id)
        )
    """)
    conn.commit()
    conn.close()

async def get_sesion_activa() -> int | None:
    """Busca el ID de la sesión marcada como activa."""
    async with aiosqlite.connect(config.DB_FILE) as db:
        async with db.execute(
            "SELECT id FROM sesiones WHERE activa = 1 ORDER BY id DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else None

async def crear_sesion(descripcion: str) -> int:
    """Cierra sesiones anteriores y crea una nueva."""
    async with aiosqlite.connect(config.DB_FILE) as db:
        await db.execute("UPDATE sesiones SET activa = 0")
        cursor = await db.execute(
            "INSERT INTO sesiones (fecha, descripcion, activa) VALUES (?, ?, 1)",
            (datetime.now().strftime("%Y-%m-%d %H:%M"), descripcion),
        )
        sesion_id = cursor.lastrowid
        await db.commit()
        return sesion_id

async def registrar_asistencia(
    sesion_id: int,
    user_id: int,
    username: str | None,
    nombre: str,
    estado: str,
    evidencia_path: str | None = None,
) -> bool:
    """Inserta la respuesta de un alumno. Retorna False si ya existe un registro (no se modifica)."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    async with aiosqlite.connect(config.DB_FILE) as db:
        async with db.execute(
            "SELECT id FROM asistencias WHERE sesion_id=? AND user_id=?",
            (sesion_id, user_id),
        ) as cursor:
            row = await cursor.fetchone()

        if row:
            return False  # Ya registrado — no se permite modificar

        await db.execute(
            """INSERT INTO asistencias (sesion_id, user_id, username, nombre, estado, evidencia_path, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sesion_id, user_id, username, nombre, estado, evidencia_path, ts),
        )
        await db.commit()
        return True

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
        "📋 /asistencia [descripción] — Abrir nueva encuesta\n"
        "📊 /reporte — Ver asistencias de la sesión actual\n"
        "🔒 /cerrar — Cerrar la sesión activa\n"
        "🚫 /cancelar — Cancelar envío de justificante en curso",
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
    user = query.from_user
    sesion_id = await get_sesion_activa()

    if not sesion_id:
        await query.answer("⚠️ No hay ninguna sesión abierta ahora mismo.", show_alert=True)
        return

    await query.answer()

    nombre = f"{user.first_name} {user.last_name or ''}".strip()

    if query.data == "si":
        registrado = await registrar_asistencia(sesion_id, user.id, user.username, nombre, "asistio")
        if registrado:
            await query.message.reply_text(f"✅ Asistencia registrada para *{nombre}*", parse_mode="Markdown")
        else:
            await query.answer("⚠️ Ya tienes un registro en esta sesión. No se puede modificar.", show_alert=True)
    else:
        # Solo iniciar flujo si aún no hay registro para esta sesión
        async with aiosqlite.connect(config.DB_FILE) as db:
            async with db.execute(
                "SELECT id FROM asistencias WHERE sesion_id=? AND user_id=?",
                (sesion_id, user.id),
            ) as cursor:
                ya_existe = await cursor.fetchone()

        if ya_existe:
            await query.answer("⚠️ Ya tienes un registro en esta sesión. No se puede modificar.", show_alert=True)
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

    async with aiosqlite.connect(config.DB_FILE) as db:
        async with db.execute(
            "SELECT nombre, estado FROM asistencias WHERE sesion_id=? ORDER BY nombre",
            (sesion_id,),
        ) as cursor:
            filas = await cursor.fetchall()

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

    async with aiosqlite.connect(config.DB_FILE) as db:
        await db.execute("UPDATE sesiones SET activa = 0 WHERE id = ?", (sesion_id,))
        await db.commit()

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

def create_app() -> Application:
    """Construye y configura la aplicación."""
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("asistencia", cmd_asistencia))
    app.add_handler(CommandHandler("reporte", cmd_reporte))
    app.add_handler(CommandHandler("cerrar", cmd_cerrar))
    app.add_handler(CommandHandler("cancelar", cmd_cancelar))
    app.add_handler(CallbackQueryHandler(callback_respuesta, pattern="^(si|no)$"))
    app.add_handler(MessageHandler(filters.PHOTO, recibir_imagen))

    return app
