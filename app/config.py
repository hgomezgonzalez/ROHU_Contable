"""Application configuration."""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


class BaseConfig:
    """Base configuration shared across all environments."""

    SECRET_KEY = os.getenv("SECRET_KEY", os.urandom(32).hex())
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    _db_url = os.getenv("DATABASE_URL", "")
    SQLALCHEMY_DATABASE_URI = _db_url.replace("postgres://", "postgresql://", 1)

    # Per-app Postgres schema (single shared DB, one schema per SaaS instance).
    # Default to "public" so local dev keeps working without env changes.
    DB_SCHEMA = os.getenv("DB_SCHEMA", "public")

    # Redis (shared across all SaaS instances; use rediss:// for TLS on Heroku).
    REDIS_URL = os.getenv("REDIS_URL", os.getenv("REDIS_TLS_URL", ""))

    # JWT
    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", os.urandom(32).hex())
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_ACCESS_TOKEN_EXPIRES", "900")))
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(seconds=int(os.getenv("JWT_REFRESH_TOKEN_EXPIRES", "2592000")))
    JWT_TOKEN_LOCATION = ["headers"]

    # Timezone
    TIMEZONE = os.getenv("TIMEZONE", "America/Bogota")

    # Heroku deploy integration
    HEROKU_API_KEY = os.getenv("ROHU_HEROKU_KEY", "")
    GITHUB_REPO = os.getenv("GITHUB_REPO", "hgomezgonzalez/ROHU_Contable")

    # Connection pool — critical for production stability.
    # connect_args pins the Postgres search_path to the per-app schema so every
    # query, relationship and migration lands in the correct namespace without
    # touching models. Fallback to "public" is intentional for OOB tables.
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_size": 3,
        "max_overflow": 3,
        "pool_timeout": 20,
        "pool_recycle": 300,  # Recycle connections every 5 min (avoids stale connections)
        "pool_pre_ping": True,  # Verify connection is alive before using (critical for cloud DBs)
        "connect_args": {
            "options": f"-csearch_path={DB_SCHEMA},public",
        },
    }


class DevelopmentConfig(BaseConfig):
    """Development configuration."""

    DEBUG = True
    SQLALCHEMY_ECHO = False


class TestingConfig(BaseConfig):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "TEST_DATABASE_URL",
        "postgresql://hfgomezgo:Exito2026$@localhost:5432/ROHU_test",
    )


class ProductionConfig(BaseConfig):
    """Production configuration."""

    DEBUG = False
    SQLALCHEMY_ECHO = False


config_by_name = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
