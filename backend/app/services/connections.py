from app.core.crypto import decrypt
from app.models import Connection
from app.plugins.base import ConnectionContext


def to_context(conn: Connection) -> ConnectionContext:
    return ConnectionContext(
        host=conn.host,
        port=conn.port,
        username=conn.username,
        password=decrypt(conn.encrypted_password),
        verify_tls=conn.verify_tls,
    )
