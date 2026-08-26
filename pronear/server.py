"""שרת HTTP (stdlib) שמגיש את ה-API ואת קבצי הממשק."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import api, config, db

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
MAX_BODY = 1 << 20  # 1MB


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "ProNear/1.0"
    protocol_version = "HTTP/1.1"

    # ----- עזרים -----
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("גוף הבקשה גדול מדי")
        raw = self.rfile.read(length)
        if not raw.strip():
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("גוף הבקשה חייב להיות אובייקט JSON")
        return data

    # ----- קבצים סטטיים -----
    def _serve_static(self, path: str):
        rel = path.lstrip("/") or "index.html"
        target = os.path.normpath(os.path.join(WEB_DIR, rel))
        if not target.startswith(WEB_DIR) or not os.path.isfile(target):
            # SPA fallback
            target = os.path.join(WEB_DIR, "index.html")
            if not os.path.isfile(target):
                return self._json(404, {"error": "לא נמצא"})
        ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        with open(target, "rb") as fh:
            self._send(200, fh.read(), ctype, {"Cache-Control": "no-cache"})

    # ----- מטפלים -----
    def _handle(self):
        path = self.path
        if not path.startswith("/api/"):
            if self.command in ("GET", "HEAD"):
                return self._serve_static(path.split("?")[0])
            return self._json(405, {"error": "המסלול לא נתמך"})
        try:
            body = self._read_body() if self.command in ("POST", "PUT", "PATCH") else {}
        except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as exc:
            return self._json(400, {"error": f"JSON לא תקין: {exc}"})
        try:
            status, payload = api.dispatch(self.command, path, body, self.headers)
        except Exception as exc:  # שגיאה לא צפויה - לא מפילים את השרת
            self.log_error("unhandled error: %r", exc)
            return self._json(500, {"error": "שגיאת שרת פנימית"})
        self._json(status, payload)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = _handle

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.log_date_time_string(), fmt % args))


def serve(host: str = None, port: int = None):
    host = host or config.HOST
    port = port or config.PORT
    db.init_db()
    httpd = ThreadingHTTPServer((host, port), RequestHandler)
    httpd.daemon_threads = True
    print(f"ProNear פועל בכתובת http://{host}:{port}  (DB: {config.DB_PATH})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nעצירה.")
    finally:
        httpd.server_close()


def main():
    parser = argparse.ArgumentParser(description="ProNear - איתור אנשי מקצוע פנויים באזור שלך")
    parser.add_argument("--host", default=config.HOST)
    parser.add_argument("--port", type=int, default=config.PORT)
    parser.add_argument("--db", default=None, help="נתיב לקובץ מסד הנתונים")
    args = parser.parse_args()
    if args.db:
        config.DB_PATH = args.db
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
