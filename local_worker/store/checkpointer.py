import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from local_worker.store import database


_checkpoint_connection = None
_checkpointer = None


async def initialize_checkpointer():
    global _checkpoint_connection, _checkpointer
    
    if database._connection_factory is None:
        raise RuntimeError("local worker store is not initialized")
    
    connection = aiosqlite.Connection(database._connection_factory, iter_chunk_size=64)
    await connection
    
    _checkpoint_connection = connection
    _checkpointer = AsyncSqliteSaver(connection)
    
    await _checkpointer.setup()


def get_checkpointer() -> AsyncSqliteSaver:
    if _checkpointer is None:
        raise RuntimeError("local checkpointer is not initialized")
    return _checkpointer


async def close_checkpointer() -> None:
    global _checkpoint_connection, _checkpointer

    if _checkpoint_connection is not None:
        await _checkpoint_connection.close()

    _checkpoint_connection = None
    _checkpointer = None
