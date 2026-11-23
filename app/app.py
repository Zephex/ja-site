"""Route table and dispatch."""

import os
import re

from . import config, http, routes_admin as admin, routes_public as public
from .render import e

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

ROUTES = [
    ("GET", r"^/static/(style\.css|app\.js)$", "static"),
    ("GET", r"^/theme\.css$", public.theme_css),
    ("GET", r"^/background$", public.background_image),
    ("GET", r"^/media/(\d+)$", public.media_file),
    ("GET", r"^/$", public.index),
    ("GET", r"^/i/([^/]+)$", public.invite),
    ("POST", r"^/i/([^/]+)$", public.invite),
    ("GET", r"^/invite$", public.invite_query),
    ("POST", r"^/invite$", public.invite_query),
    ("GET", r"^/page$", public.page),
    ("GET", r"^/img/(\d+)$", public.image),
    ("POST", r"^/logout$", public.logout),
    ("GET", r"^/admin/setup$", admin.setup),
    ("POST", r"^/admin/setup$", admin.setup),
    ("GET", r"^/admin/login$", admin.login),
    ("POST", r"^/admin/login$", admin.login),
    ("POST", r"^/admin/logout$", admin.logout),
    ("GET", r"^/admin$", admin.dashboard),
    ("POST", r"^/admin/background$", admin.save_background),
    ("POST", r"^/admin/background/upload$", admin.upload_background),
    ("POST", r"^/admin/media/upload$", admin.upload_media),
    ("POST", r"^/admin/media/(\d+)/choose$", admin.choose_media),
    ("POST", r"^/admin/media/(\d+)/delete$", admin.delete_media),
    ("POST", r"^/admin/account$", admin.create_account),
    ("GET", r"^/admin/account/(\d+)$", admin.account),
    ("POST", r"^/admin/account/(\d+)/details$", admin.update_details),
    ("POST", r"^/admin/account/(\d+)/invite$", admin.create_invite),
    ("POST", r"^/admin/account/(\d+)/invite/(\d+)/revoke$", admin.revoke_invite),
    ("POST", r"^/admin/account/(\d+)/image/upload$", admin.upload_image),
    ("POST", r"^/admin/account/(\d+)/image/(\d+)$", admin.update_image),
    ("POST", r"^/admin/account/(\d+)/link$", admin.add_link),
    ("POST", r"^/admin/account/(\d+)/link/(\d+)$", admin.update_link),
    ("POST", r"^/admin/account/(\d+)/delete$", admin.delete_account),
]

COMPILED = [(method, re.compile(pattern), handler) for method, pattern, handler in ROUTES]


def serve_static(req, filename):
    path = os.path.join(STATIC_DIR, filename)
    if not os.path.isfile(path):
        return http.not_found()
    with open(path, "rb") as handle:
        data = handle.read()
    mime = "text/css; charset=utf-8" if filename.endswith(".css") else "text/javascript; charset=utf-8"
    return http.Response(
        200, data, {"Content-Type": mime, "Cache-Control": "public, max-age=60"}
    )


def dispatch(req):
    for method, pattern, handler in COMPILED:
        if method != req.method:
            continue
        match = pattern.match(req.path)
        if not match:
            continue
        args = [int(x) if x.isdigit() else x for x in match.groups()]
        if handler == "static":
            return serve_static(req, args[0])
        return handler(req, *args)
    return http.not_found()
