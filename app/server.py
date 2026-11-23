"""Threaded HTTP server. Put Caddy in front of this on port 8080."""

import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, db, http, security

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    ),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ja-site"

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_HEAD(self):
        self._handle("GET", head_only=True)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, resp, head_only=False):
        self.send_response(resp.status)
        for key, value in resp.headers.items():
            self.send_header(key, value)
        for key, value in SECURITY_HEADERS.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(resp.body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(resp.body)

    def _handle(self, method, head_only=False):
        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
        except ValueError:
            length = -1
        if length < 0 or length > http.MAX_BODY:
            self._send(http.Response(413, "Request too large", {"Content-Type": "text/plain"}), head_only)
            return
        body = self.rfile.read(length) if length else b""

        from .app import dispatch

        req = http.Request(method, self.path, dict(self.headers.items()), body, self.client_address[0])
        conn = db.connect()
        req.conn = conn
        req.session = security.load_session(conn, req.cookies.get(config.SESSION_COOKIE))
        try:
            resp = dispatch(req)
        except Exception:
            traceback.print_exc()
            resp = http.html("<h1>Something went wrong</h1><p>Try again in a moment.</p>", 500)
        try:
            security.save_session(conn, req.session)
            if req.session.dirty:
                cookie = "%s=%s; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=%d" % (
                    config.SESSION_COOKIE,
                    req.session.token,
                    config.SESSION_TTL,
                )
                resp.set("Set-Cookie", cookie)
        except Exception:
            traceback.print_exc()
        finally:
            conn.close()
        self._send(resp, head_only)


def main():
    db.connect()
    server = ThreadingHTTPServer((config.HOST, config.PORT), Handler)
    print("ja-site listening on %s:%d" % (config.HOST, config.PORT), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
