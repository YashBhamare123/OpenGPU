import select
import socket
import threading

from config import settings
from database import get_connection


def active_ssh_backend() -> tuple[str, int] | None:
    conn = get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT t.ssh_port FROM reservations r JOIN teams t ON t.id=r.team_id
                WHERE r.start_time<=NOW() AND r.end_time>NOW() AND NOT r.cancelled
                  AND t.enabled AND t.provisioning_state='ready' AND t.ssh_port IS NOT NULL
                ORDER BY r.start_time,r.id LIMIT 1
                """
            )
            row = cursor.fetchone()
    finally:
        conn.close()
    if not row:
        return None
    return settings.docker_bind_ip, int(row[0])


def _pipe(left: socket.socket, right: socket.socket) -> None:
    sockets = [left, right]
    try:
        while True:
            readable, _, errored = select.select(sockets, [], sockets, 60)
            if errored:
                break
            if not readable:
                continue
            for source in readable:
                destination = right if source is left else left
                data = source.recv(65536)
                if not data:
                    return
                destination.sendall(data)
    except OSError:
        return
    finally:
        left.close()
        right.close()


def handle_client(client: socket.socket) -> None:
    backend = active_ssh_backend()
    if backend is None:
        client.close()
        return
    host, port = backend
    upstream = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        upstream.settimeout(10)
        upstream.connect((host, port))
        upstream.settimeout(None)
    except OSError:
        client.close()
        upstream.close()
        return
    _pipe(client, upstream)


def serve_gateway(stop: threading.Event) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((settings.ssh_gateway_bind, settings.ssh_public_port))
    server.listen(32)
    server.settimeout(0.5)
    try:
        while not stop.is_set():
            try:
                client, _address = server.accept()
            except TimeoutError:
                continue
            except OSError:
                if stop.is_set():
                    break
                raise
            threading.Thread(target=handle_client, args=(client,), daemon=True).start()
    finally:
        server.close()
