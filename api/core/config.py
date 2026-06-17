from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Base de datos
    DATABASE_URL: str = "postgresql://bot_asistencias:password@localhost:5432/asistencias_db"

    # JWT
    JWT_SECRET: str = "cambia_este_secreto_en_produccion"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_EXPIRE_DAYS: int = 7

    # CORS — formato JSON en .env: ["https://ejemplo.com"]
    CORS_ORIGINS: list[str] = ["*"]

    # Archivos de evidencias (compartido con el bot)
    EVIDENCIAS_DIR: str = "evidencias"


settings = Settings()
