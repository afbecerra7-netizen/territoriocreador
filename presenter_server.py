#!/usr/bin/env python3
import argparse
import json
import os
import subprocess
import threading
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
LOCK = threading.Lock()
SESSIONS = {}


def clamp(value, total):
    return max(0, min(value, max(total - 1, 0)))


def get_session_state(session):
    with LOCK:
        state = SESSIONS.setdefault(session, {"index": 0, "total": 1})
        return dict(state)


def update_session_state(session, action, index=None, total=None):
    with LOCK:
        state = SESSIONS.setdefault(session, {"index": 0, "total": 1})

        if isinstance(total, int) and total > 0:
            state["total"] = total

        total_value = state["total"]
        current = state["index"]

        if action == "set" and isinstance(index, int):
            current = clamp(index, total_value)
        elif action == "next":
            current = clamp(current + 1, total_value)
        elif action == "prev":
            current = clamp(current - 1, total_value)

        state["index"] = current
        return dict(state)


class PresenterHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        if self.path.startswith("/api/"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.send_header("Pragma", "no-cache")
        super().end_headers()

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/state":
            session = parse_qs(parsed.query).get("session", ["clase"])[0]
            self.send_json(get_session_state(session))
            return

        if parsed.path == "/api/health":
            self.send_json({"ok": True})
            return

        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/control":
            self.send_error(HTTPStatus.NOT_FOUND, "Ruta no encontrada")
            return

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b"{}"

        try:
            payload = json.loads(raw_body.decode("utf-8"))
        except json.JSONDecodeError:
            self.send_error(HTTPStatus.BAD_REQUEST, "JSON invalido")
            return

        session = payload.get("session") or "clase"
        action = payload.get("action") or "set"
        index = payload.get("index")
        total = payload.get("total")

        if not isinstance(index, int):
            index = None
        if not isinstance(total, int):
            total = None

        state = update_session_state(session, action, index=index, total=total)
        self.send_json(state)


def guess_local_ips():
    candidates = []
    for interface in ("en0", "en1"):
        try:
            value = subprocess.check_output(
                ["ipconfig", "getifaddr", interface],
                stderr=subprocess.DEVNULL,
                text=True
            ).strip()
        except Exception:
            value = ""
        if value:
            candidates.append(value)

    if not candidates:
        candidates.append("127.0.0.1")

    seen = []
    for ip in candidates:
        if ip not in seen:
            seen.append(ip)
    return seen


def main():
    parser = argparse.ArgumentParser(description="Servidor local para presentar y controlar diapositivas desde el celular.")
    parser.add_argument("--host", default="0.0.0.0", help="Host de escucha. Default: 0.0.0.0")
    parser.add_argument("--port", type=int, default=8000, help="Puerto HTTP. Default: 8000")
    parser.add_argument("--session", default="clase", help="Sesion sugerida para compartir entre pantalla y celular.")
    args = parser.parse_args()

    os.chdir(ROOT)
    server = ThreadingHTTPServer((args.host, args.port), PresenterHandler)

    print("")
    print("Servidor de presentacion listo.")
    print("")
    print("Usa la misma sesion en ambas URLs:")
    print(f"  sesion: {args.session}")
    print("")
    print("En este equipo:")
    print(f"  presentacion: http://127.0.0.1:{args.port}/?session={args.session}")
    print(f"  control:      http://127.0.0.1:{args.port}/remote.html?session={args.session}")
    print("")
    print("En la red local:")
    for ip in guess_local_ips():
        print(f"  presentacion: http://{ip}:{args.port}/?session={args.session}")
        print(f"  control:      http://{ip}:{args.port}/remote.html?session={args.session}")
    print("")
    print("Deja esta terminal abierta mientras presentas.")
    print("")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
