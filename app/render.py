"""Shared HTML layout and small UI helpers."""

import html

from . import config, db, security


def e(value):
    return html.escape("" if value is None else str(value), quote=True)


def layout(title, body, *, req=None, admin=False, minimal=False):
    csrf = security.csrf_token(req.session) if req else ""
    bg_type = db.get_setting(req.conn, "bg_type", "default") if req else "default"
    body_class = "has-custom-bg" if bg_type in ("color", "gradient", "image") else ""
    bg_video = ""
    if req and bg_type == "image":
        media_id = db.get_setting(req.conn, "bg_media_id", "")
        if media_id.isdigit():
            row = db.one(req.conn, "SELECT * FROM media WHERE id = ?", (int(media_id),))
            if row and row["kind"] == "video":
                body_class += " has-video-bg"
                bg_video = (
                    '<video class="bg-video" autoplay muted loop playsinline aria-hidden="true">'
                    '<source src="/media/%d" type="%s"></video>'
                    % (row["id"], e(row["mime"]))
                )
    if admin:
        body_class = (body_class + " admin-page").strip()
    flashes = ""
    if req and not minimal:
        for item in req.session.pop("flash", []) or []:
            flashes += '<div class="flash %s">%s</div>' % (e(item[0]), e(item[1]))

    admin_url = "/admin" if (req and req.session.get("admin_id")) else "/admin/login"
    cat_button = (
        '<a class="cat-admin" href="%s" title="Admin" aria-label="Open admin panel">🐈‍⬛</a>'
        % admin_url
    )

    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="dark">
<meta name="csrf-token" content="%s">
<title>%s</title>
<link rel="stylesheet" href="/static/style.css?v=12">
<link rel="stylesheet" href="/theme.css">
<script src="/static/app.js?v=12" defer></script>
</head>
<body class="%s">
<div class="backdrop" aria-hidden="true"><div class="aurora a"></div><div class="aurora b"></div><div class="aurora c"></div><div class="grid"></div><div class="vignette"></div></div>
%s
%s
<div class="shell">
<main class="page">
%s
</main>
</div>
%s
</body>
</html>""" % (
        e(csrf),
        e(title),
        body_class,
        bg_video,
        flashes,
        body,
        cat_button,
    )


def flash(req, kind, text):
    req.session.set("flash", (req.session.get("flash") or []) + [(kind, text)])


def csrf_input(req):
    return '<input type="hidden" name="csrf" value="%s">' % e(security.csrf_token(req.session))


def invite_status(invite, now):
    if invite["revoked"]:
        return "revoked"
    if invite["expires_at"] and invite["expires_at"] <= now:
        return "expired"
    if invite["max_uses"] is not None and invite["uses"] >= invite["max_uses"]:
        return "used up"
    return "active"
