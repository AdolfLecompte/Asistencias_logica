"""
Punto de entrada del bot de asistencias.
Inicializa la base de datos, configura el programador y arranca el bot.
"""
import logging
import os

import config
from bot import create_app, init_db, lanzar_asistencia_automatica

# Configurar logging ANTES de importar cualquier módulo que lo use
logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    # 1. Preparar el entorno
    init_db()
    os.makedirs(config.EVIDENCIAS_DIR, exist_ok=True)

    logger.info("Base de datos y directorios inicializados ✔")
    logger.info(f"Ollama: {config.OLLAMA_URL} | Modelo: {config.OLLAMA_MODEL}")

    if config.ADMIN_IDS:
        logger.info(f"Admins configurados: {sorted(config.ADMIN_IDS)}")
    else:
        logger.warning("ADMIN_IDS no configurado — cualquier usuario puede usar los comandos de admin.")

    # 2. Crear la aplicación
    app = create_app()

    # 3. Programador nativo de PTB (JobQueue)
    if config.GRUPO_ID != 0:
        app.job_queue.run_daily(
            callback=lanzar_asistencia_automatica,
            time=config.HORA_INICIO,
            days=config.DIAS_CLASE,
            name="encuesta_asistencia",
        )
        dias_str = ", ".join(
            ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][d]
            for d in config.DIAS_CLASE
        )
        logger.info(
            f"⏰ Encuesta automática: {config.NOMBRE_MATERIA} | "
            f"{dias_str} a las {config.HORA_INICIO.strftime('%H:%M %Z')}"
        )
    else:
        logger.info("⏸  Encuestas automáticas desactivadas (GRUPO_ID=0 o no definido).")

    # 4. Iniciar el bot
    logger.info("Bot iniciado. Esperando mensajes... 🤖")
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
