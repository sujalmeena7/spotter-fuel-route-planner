import socket

import pytest

_ORIGINAL_CONNECT = socket.socket.connect


@pytest.fixture(autouse=True)
def block_external_sockets(monkeypatch):
    """Prevent any external network calls during tests."""

    def guarded_connect(self, address):
        host = address[0] if isinstance(address, tuple) else address
        # Allow local loopback connections if needed by test servers
        if host in ("127.0.0.1", "localhost", "::1", "0.0.0.0"):
            return _ORIGINAL_CONNECT(self, address)
        raise RuntimeError(
            f"Blocked external network access to {address} during test execution. "
            "Use recorded fixtures or mock the network call."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
