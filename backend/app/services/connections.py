import ipaddress
import socket

from app.core.crypto import decrypt
from app.models import Connection
from app.plugins.base import ConnectionContext


class UnsafeTargetError(ValueError):
    pass


def assert_target_allowed(host: str) -> None:
    """Refuse addresses that make the platform attack itself or its cloud metadata.

    A managed device lives on a routable or private network. Loopback, link-local
    and multicast addresses only make sense to an attacker trying to reach
    169.254.169.254 or a service bound inside the container network.
    """
    candidate = host.strip().strip("[]")
    if not candidate:
        raise UnsafeTargetError("a hostname or IP address is required")

    try:
        resolved = {info[4][0] for info in socket.getaddrinfo(candidate, None)}
    except socket.gaierror:
        # Unresolvable now is a connectivity problem, reported by the test button.
        return

    for address in resolved:
        ip = ipaddress.ip_address(address)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise UnsafeTargetError(
                f"'{host}' resolves to {ip}, which is not a valid device address. "
                "Loopback, link-local and multicast addresses are refused because "
                "they point back at the platform or at cloud metadata services."
            )


def to_context(conn: Connection) -> ConnectionContext:
    return ConnectionContext(
        host=conn.host,
        port=conn.port,
        username=conn.username,
        password=decrypt(conn.encrypted_password),
        verify_tls=conn.verify_tls,
    )
