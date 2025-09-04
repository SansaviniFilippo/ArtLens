import os
import time
import re
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import OperationalError
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database URL resolution and sanitization

def sanitize_db_url(url: str) -> str:
    # Force psycopg3 driver
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]

    # Remove a trailing slash just after the dbname (before ? or end)
    url = re.sub(r'(\/[^\/?#]+)\/(?=(\?|$))', r'\1', url)

    # Ensure sslmode present (default require)
    parsed = urlparse(url)
    q = dict(parse_qsl(parsed.query))
    if "sslmode" not in q:
        q["sslmode"] = os.getenv("PGSSLMODE", "require")
    parsed = parsed._replace(query=urlencode(q))
    return urlunparse(parsed)

raw_url = os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
if not raw_url:
    raise RuntimeError("DATABASE_URL or SUPABASE_DB_URL must be set")
DB_URL = sanitize_db_url(raw_url)


# Build connect args with SSL and keepalives for Render/Supabase/PgBouncer compatibility
_connect_args = {
    "prepare_threshold": None,  # disable prepared statements (PgBouncer safe)
    "sslmode": os.getenv("PGSSLMODE", "require"),
    "connect_timeout": int(os.getenv("PGCONNECT_TIMEOUT", "10")),
    # TCP keepalives (help avoid idle disconnects on Render/Supabase)
    "keepalives": 1,
    "keepalives_idle": int(os.getenv("PG_KEEPALIVES_IDLE", "30")),
    "keepalives_interval": int(os.getenv("PG_KEEPALIVES_INTERVAL", "10")),
    "keepalives_count": int(os.getenv("PG_KEEPALIVES_COUNT", "5")),
    "application_name": os.getenv("PGAPPNAME", "ArtLens"),
}

# Pool configuration (PgBouncer-friendly)
_use_nullpool_env = os.getenv("DB_USE_NULLPOOL", "true").strip().lower()
USE_NULLPOOL = _use_nullpool_env in ("1", "true", "yes", "y", "on")

# Diagnostics (redacted URL)
_parsed = urlparse(DB_URL)
_host = _parsed.hostname or "?"
_port = _parsed.port or 5432
_dbname = (_parsed.path or "/").lstrip("/")
_q = dict(parse_qsl(_parsed.query))
_sslmode = _q.get("sslmode", os.getenv("PGSSLMODE", "require"))

if USE_NULLPOOL:
    engine = create_engine(
        DB_URL,
        client_encoding="utf8",
        pool_pre_ping=True,
        poolclass=NullPool,
        connect_args=_connect_args,
    )
    logger.info(f"[DB] Engine: host={_host} port={_port} db={_dbname} sslmode={_sslmode} pool=NullPool")
else:
    engine = create_engine(
        DB_URL,
        client_encoding="utf8",
        pool_pre_ping=True,
        pool_recycle=int(os.getenv("DB_POOL_RECYCLE", "300")),
        pool_size=int(os.getenv("DB_POOL_SIZE", "3")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "2")),
        pool_timeout=int(os.getenv("DB_POOL_TIMEOUT", "10")),
        connect_args=_connect_args,
    )
    logger.info(f"[DB] Engine: host={_host} port={_port} db={_dbname} sslmode={_sslmode} pool=QueuePool(size={os.getenv('DB_POOL_SIZE', '3')}, overflow={os.getenv('DB_MAX_OVERFLOW', '2')})")



def run_with_retry(sql: str, params=None, max_retries=3, retry_delay=1):
    """Execute SQL with retry logic for connection issues."""
    last_exception = None

    for attempt in range(max_retries):
        try:
            with engine.begin() as conn:
                return conn.execute(text(sql), params or {})
        except OperationalError as e:
            last_exception = e
            e_orig = getattr(e, "orig", None)
            raw_msg = str(e_orig) if e_orig else str(e)
            error_msg = raw_msg.lower()

            # Retry solo per errori di connessione specifici
            should_retry = any([
                "server closed the connection unexpectedly" in error_msg,
                "connection failed" in error_msg,
                "could not connect to server" in error_msg,
                "connection timeout expired" in error_msg,
                "timeout expired" in error_msg,
                "connection reset by peer" in error_msg,
                "terminating connection" in error_msg,
                ("connection to server" in error_msg and "failed" in error_msg),
            ])

            if should_retry and attempt < max_retries - 1:
                logger.warning(f"Connection failed on attempt {attempt + 1}/{max_retries}: {raw_msg[:200]}...")
                logger.warning(f"Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
                continue
            else:
                # Se non è un errore di connessione, non fare retry
                logger.error(f"Database error (no retry): {raw_msg[:200]}...")
                raise
        except Exception as e:
            # Per altri tipi di errori, non fare retry
            logger.error(f"Unexpected database error: {str(e)[:200]}...")
            raise

    # Se arriviamo qui, tutti i retry sono falliti
    logger.error(f"All {max_retries} connection attempts failed. Last error: {str(last_exception)[:200]}...")
    raise last_exception

def run(sql: str, params=None):
    """Execute a SQL statement with automatic retry on connection failures."""
    return run_with_retry(sql, params)

def run_simple(sql: str, params=None, max_retries=2):
    """Execute simple SQL with fewer retries for faster operations."""
    return run_with_retry(sql, params, max_retries=max_retries, retry_delay=0.5)