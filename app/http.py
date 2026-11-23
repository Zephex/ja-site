"""Tiny request/response helpers."""

import json
from urllib.parse import parse_qs

MAX_BODY = 100 * 1024 * 1024 + 64 * 1024


class Request:
    def __init__(self, method, path, headers, body, remote_addr):
        self.method = method
        self.path = path
        self.headers = {k.lower(): v for k, v in headers.items()}
        self.body = body
        self.remote_addr = remote_addr
        self.query = {}
        if "?" in path:
            raw_query = path.split("?", 1)[1]
            self.path = path.split("?", 1)[0]
            for key, values in parse_qs(raw_query, keep_blank_values=True).items():
                self.query[key] = values[-1]
        self.form = {}
        content_type = self.headers.get("content-type", "")
        if method == "POST" and content_type.startswith("application/x-www-form-urlencoded"):
            for key, values in parse_qs(
                body.decode("utf-8", "replace"), keep_blank_values=True
            ).items():
                self.form[key] = values[-1]
        self.cookies = {}
        for part in self.headers.get("cookie", "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                self.cookies[key] = value
        self.session = None
        self.conn = None


class Response:
    def __init__(self, status=200, body=b"", headers=None):
        self.status = status
        self.body = body if isinstance(body, bytes) else body.encode("utf-8")
        self.headers = dict(headers or {})

    def set(self, key, value):
        self.headers[key] = value
        return self


def html(body, status=200):
    return Response(
        status, body, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}
    )


def redirect(location, status=303):
    return Response(status, b"", {"Location": location, "Cache-Control": "no-store"})


def as_json(data, status=200):
    return Response(
        status,
        json.dumps(data),
        {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
    )


def binary(data, mime, status=200, extra=None):
    headers = {
        "Content-Type": mime,
        "Content-Length": str(len(data)),
        "Cache-Control": "private, max-age=3600",
    }
    headers.update(extra or {})
    return Response(status, data, headers)


def not_found():
    return html(
        "<!doctype html><meta charset='utf-8'><title>Not found</title>"
        "<h1>Not found</h1><p>That page does not exist.</p>",
        404,
    )
