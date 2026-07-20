import base64
import threading
from pathlib import Path
from typing import Callable

from sqlalchemy import NullPool, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from local_worker.store.tables import Base

try:
    from sqlcipher3 import dbapi2 as sqlcipher
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
    sqlcipher = None
    _sqlcipher_import_error = exc
else:
    _sqlcipher_import_error = None
    
_lock = threading.RLock()
_engine: Engine | None = None
_SessionLocal: Callable[[], Session] | None = None

_connection_factory = None

def initialize(db_path: str, db_key: str) -> None:
    global _engine, _SessionLocal, _connection_factory

    if sqlcipher is None:
        raise RuntimeError("sqlcipher3-binary is required for encrypted local storage") from _sqlcipher_import_error

    key = base64.b64decode(db_key, validate=True)
    if len(key) != 32:
        raise ValueError("local worker database key must be 32 bytes")

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    key_hex = key.hex()

    def connect():
        conn = sqlcipher.connect(str(path), check_same_thread=False)
        try:
            cursor = conn.cursor()
            
            try:
                cursor.execute(f"PRAGMA key = \"x'{key_hex}'\"")
                cursor.execute("PRAGMA busy_timeout = 5000")
                cursor.execute("SELECT count(*) FROM sqlite_master")
            finally:
                cursor.close()
            return conn

        except Exception:
            conn.close()
            raise

    _connection_factory = connect


    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = create_engine("sqlite://", creator=connect, future=True, poolclass=NullPool)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
        Base.metadata.create_all(_engine)


def _reset_for_tests() -> None:
    global _engine, _SessionLocal
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionLocal = None


def _session() -> Session:
    if _SessionLocal is None:
        raise RuntimeError("local worker store is not initialized")
    return _SessionLocal()

