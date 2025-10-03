import os
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import create_engine # For sync engine if needed for migrations later
from sqlalchemy.sql import text

# Import Base from models within the same package
# Ensure models are imported somewhere before init_db is called so Base is populated.
from .models import Base 

logger = logging.getLogger("shared_models.database")

# --- Database Configuration ---
DB_HOST = os.environ.get("DB_HOST")
DB_PORT = os.environ.get("DB_PORT")
DB_NAME = os.environ.get("DB_NAME")
DB_USER = os.environ.get("DB_USER")
DB_PASSWORD = os.environ.get("DB_PASSWORD")

# --- Validation at startup ---
if not all([DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD]):
    missing_vars = [
        var_name
        for var_name, var_value in {
            "DB_HOST": DB_HOST,
            "DB_PORT": DB_PORT,
            "DB_NAME": DB_NAME,
            "DB_USER": DB_USER,
            "DB_PASSWORD": DB_PASSWORD,
        }.items()
        if not var_value
    ]
    raise ValueError(f"Missing required database environment variables: {', '.join(missing_vars)}")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
DATABASE_URL_SYNC = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

def _ensure_database_exists():
    """Best‑effort create the target database if it does not exist.

    This is safe to run concurrently across multiple containers; a race
    resulting in 'already exists' is ignored. Controlled by DB_AUTO_CREATE=1
    (defaults to enabled). If disabled we simply assume the database is there.
    """
    if os.environ.get("DB_AUTO_CREATE", "1") != "1":
        logger.info("DB_AUTO_CREATE disabled; skipping database existence check.")
        return
    admin_url = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    try:
        admin_engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": DB_NAME}).scalar()
            if not exists:
                logger.warning(f"Database '{DB_NAME}' not found. Creating it now...")
                conn.execute(text(f"CREATE DATABASE {DB_NAME}"))
                logger.info(f"Database '{DB_NAME}' created.")
            else:
                logger.debug(f"Database '{DB_NAME}' already exists.")
    except Exception as e:
        logger.error(f"Database auto-create check failed (continuing anyway): {e}", exc_info=True)

# Perform existence check before creating async engine
_ensure_database_exists()

# --- SQLAlchemy Async Engine & Session ---
engine = create_async_engine(
    DATABASE_URL,
    echo=os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG",
    pool_size=10,
    max_overflow=20
)
async_session_local = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# --- Sync Engine (For Alembic migrations) ---
sync_engine = create_engine(DATABASE_URL_SYNC)

# --- FastAPI Dependency --- 
async def get_db() -> AsyncSession:
    """FastAPI dependency to get an async database session."""
    async with async_session_local() as session:
        try:
            yield session
        finally:
            # Ensure session is closed, though context manager should handle it
            await session.close()

# --- Initialization Function --- 
async def init_db():
    """Creates database tables based on shared models' metadata."""
    logger.info(f"Initializing database tables at {DB_HOST}:{DB_PORT}/{DB_NAME}")
    try:
        async with engine.begin() as conn:
            # This relies on all SQLAlchemy models being imported 
            # somewhere before this runs, so Base.metadata is populated.
            # Add checkfirst=True to prevent errors if tables already exist
            await conn.run_sync(Base.metadata.create_all, checkfirst=True)
        logger.info("Database tables checked/created successfully.")
    except Exception as e:
        logger.error(f"Error initializing database tables: {e}", exc_info=True)
        raise 

# --- DANGEROUS: Recreate Function ---
async def recreate_db():
    """
    DANGEROUS: Drops all tables and recreates them based on shared models' metadata.
    THIS WILL RESULT IN COMPLETE DATA LOSS. USE WITH EXTREME CAUTION.
    """
    logger.warning(f"!!! DANGEROUS OPERATION: Dropping and recreating all tables in {DB_NAME} at {DB_HOST}:{DB_PORT} !!!")
    try:
        async with engine.begin() as conn:
            # Instead of drop_all, use raw SQL to drop the schema with cascade
            logger.warning("Dropping public schema with CASCADE...")
            await conn.execute(text("DROP SCHEMA public CASCADE;"))
            logger.warning("Public schema dropped.")
            logger.info("Recreating public schema...")
            await conn.execute(text("CREATE SCHEMA public;"))
            # Optional: Grant permissions if needed (often handled by default roles)
            # await conn.execute(text("GRANT ALL ON SCHEMA public TO public;")) 
            # await conn.execute(text("GRANT ALL ON SCHEMA public TO postgres;")) 
            logger.info("Public schema recreated.")
            
            logger.info("Recreating all tables based on models...")
            await conn.run_sync(Base.metadata.create_all)
            logger.info("All tables recreated successfully.")
        logger.warning(f"!!! DANGEROUS OPERATION COMPLETE for {DB_NAME} at {DB_HOST}:{DB_PORT} !!!")
    except Exception as e:
        logger.error(f"Error recreating database tables: {e}", exc_info=True)
        raise 