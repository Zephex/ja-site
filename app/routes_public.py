"""Public routes: landing, invite redemption, personal page, image serving."""

import os
import re
import time
from datetime import datetime, timezone

from . import config, db, http, markdown, render, security
from .render import e


def index(req):
    if req.session.get("account_id"):
        return http.redirect("/page")
    body = ""
    return http.html(render.layout("Welcome", body, req=req))


def _find_invite(req, token):
    token = token.strip().lstrip("/")
    if token.startswith("i/"):
        token = token[2:]
    if not token or len(token) > 128:
        return None, ""
    return db.one(
        req.conn, "SELECT * FROM invites WHERE token_hash = ?", (security.token_hash(token),)
    ), token


def invite(req, token):
    row, clean_token = _find_invite(req, token)
    now = int(time.time())
    usable = bool(
        row
        and not row["revoked"]
        and (row["expires_at"] is None or row["expires_at"] > now)
        and (row["max_uses"] is None or row["uses"] < row["max_uses"])
    )
    account = (
        db.one(req.conn, "SELECT name, active FROM accounts WHERE id = ?", (row["account_id"],))
        if row
        else None
    )

    if req.method == "POST":
        if not security.csrf_ok(req.session, req):
            return _invite_message(req, "That form expired. Please refresh and try again.")
        if not usable or not account or not account["active"]:
            return _invite_message(req, "This invite is no longer valid.")
        name = req.form.get("visitor_name", "").strip()[:120]
        if row["require_name"] and not name:
            return _invite_page(req, clean_token, row, account, "Please enter your name.")
        return _redeem(req, row, name)

    if not usable or not account or not account["active"]:
        return _invite_message(req, "This invite is no longer valid. Ask for a new one.")
    return _invite_page(req, clean_token, row, account, "")


def invite_query(req):
    return invite(req, req.query.get("t", ""))


def _invite_page(req, token, row, account, error):
    # The gate is intentionally bare: only the greeting and the lobster button.
    hidden_name = (
        '<input type="hidden" name="visitor_name" value="%s">' % e(account["name"])
        if row["require_name"]
        else ""
    )
    body = """
<section class="center invite-minimal">
  <h1 class="greeting">Hej %s</h1>
  <div class="lobster-hint-wrap">
    <form method="post" action="/i/%s" class="invite-form">
      %s
      <button class="lobster-button" type="submit" aria-label="Continue to my page">🦞</button>
    </form>
    <span class="lobster-hint" aria-hidden="true">klik på hummeren</span>
  </div>
</section>""" % (
        e(account["name"] or "there"),
        e(token),
        render.csrf_input(req) + hidden_name,
    )
    return http.html(render.layout("Hej", body, req=req, minimal=True))


def _invite_message(req, message):
    body = '<section class="center"><article class="card narrow"><h1>Link unavailable</h1><p class="muted">%s</p><a class="button" href="/">Back to start</a></article></section>' % e(
        message
    )
    return http.html(render.layout("Link unavailable", body, req=req))


def _redeem(req, invite, name):
    now = int(time.time())
    updated = req.conn.execute(
        """UPDATE invites SET uses = uses + 1
           WHERE id = ? AND revoked = 0
             AND (expires_at IS NULL OR expires_at > ?)
             AND (max_uses IS NULL OR uses < max_uses)""",
        (invite["id"], now),
    )
    if updated.rowcount != 1:
        req.conn.rollback()
        return _invite_message(req, "This invite was just used up. Ask for a new one.")
    req.conn.execute(
        """INSERT INTO redemptions (invite_id, account_id, visitor_name, created_at)
           VALUES (?, ?, ?, ?)""",
        (invite["id"], invite["account_id"], name, now),
    )
    req.conn.commit()
    req.session.set("account_id", invite["account_id"])
    req.session.set("visitor_name", name)
    req.session.regenerate()
    render.flash(req, "ok", "Welcome! This page is yours.")
    return http.redirect("/page")


def _active_account(req):
    account_id = req.session.get("account_id")
    if not account_id:
        return None
    account = db.one(
        req.conn, "SELECT * FROM accounts WHERE id = ? AND active = 1", (account_id,)
    )
    if not account:
        req.session.pop("account_id", None)
        req.session.pop("visitor_name", None)
    return account


def _comments_section(req, comments):
    items = ""
    for comment in comments:
        when = datetime.fromtimestamp(comment["created_at"], timezone.utc).strftime(
            "%d %b %Y %H:%M UTC"
        )
        items += """<article class="card comment">
  <div class="comment-head"><strong>%s</strong><span class="muted small">%s</span></div>
  <p class="comment-body">%s</p>
  <form method="post" action="/page/comment/%d/delete" class="inline">%s<button class="button tiny danger" type="submit" data-confirm="Delete your comment?">Delete</button></form>
</article>""" % (
            e(comment["author_name"] or "You"),
            e(when),
            e(comment["body"]).replace("\n", "<br>"),
            comment["id"],
            render.csrf_input(req),
        )
    if not items:
        items = '<p class="muted">No comments yet. Be the first to leave one.</p>'
    return """<section id="comments" class="comments">
  <p class="eyebrow">comments</p>
  <h2>A place for your thoughts</h2>
  <form method="post" action="/page/comment" class="stack comment-form">
    %s
    <label class="field">Your comment<textarea name="body" rows="4" maxlength="10000" required placeholder="Write anything you like..."></textarea></label>
    <button class="button primary" type="submit">Add comment</button>
  </form>
  <div class="comment-list">%s</div>
</section>""" % (render.csrf_input(req), items)


def page(req):
    account = _active_account(req)
    if not account:
        return http.redirect("/")
    account_id = account["id"]

    comments = db.all_rows(
        req.conn,
        "SELECT * FROM comments WHERE account_id = ? ORDER BY id",
        (account_id,),
    )

    images = db.all_rows(
        req.conn,
        "SELECT id, caption FROM images WHERE account_id = ? ORDER BY position, id",
        (account_id,),
    )
    links = db.all_rows(
        req.conn,
        "SELECT title, url, description FROM links WHERE account_id = ? ORDER BY position, id",
        (account_id,),
    )

    greeting = e(account["greeting"] or ("Hi " + (req.session.get("visitor_name") or account["name"])))
    message = markdown.render(account["message"])

    gallery = ""
    if images:
        figures = ""
        for image in images:
            caption = '<figcaption>%s</figcaption>' % e(image["caption"]) if image["caption"] else ""
            figures += '<figure class="card shot"><img src="/img/%d" alt="%s" loading="lazy">%s</figure>' % (
                image["id"],
                e(image["caption"] or "Image"),
                caption,
            )
        gallery = '<section><p class="eyebrow">pictures</p><h2>A few things to look at</h2><div class="gallery">%s</div></section>' % figures

    link_cards = ""
    if links:
        cards = ""
        for link in links:
            desc = '<span>%s</span>' % e(link["description"]) if link["description"] else ""
            cards += """<a class="card link-card" href="%s" target="_blank" rel="noopener noreferrer">
<span class="link-text"><strong>%s</strong>%s</span><span class="arrow" aria-hidden="true">↗</span></a>""" % (
                e(link["url"]),
                e(link["title"]),
                desc,
            )
        link_cards = '<section><p class="eyebrow">links</p><h2>Places to go</h2><div class="links-grid">%s</div></section>' % cards

    body = """
<section class="hero personal">
  <p class="eyebrow">a message for you</p>
  <h1 class="title greeting">%s</h1>
  <div class="card message">%s</div>
</section>
%s
%s
%s""" % (
        greeting,
        message or '<p class="muted">Nothing here yet.</p>',
        gallery,
        link_cards,
        _comments_section(req, comments),
    )
    return http.html(render.layout("Your page", body, req=req))


def add_comment(req):
    account = _active_account(req)
    if not account:
        return http.redirect("/")
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/page")
    body = req.form.get("body", "").strip()[:10000]
    if not body:
        render.flash(req, "error", "Write a comment before submitting.")
        return http.redirect("/page#comments")
    author = (req.session.get("visitor_name") or account["name"]).strip()[:120] or "You"
    req.conn.execute(
        """INSERT INTO comments (account_id, author_name, body, created_at)
           VALUES (?, ?, ?, ?)""",
        (account["id"], author, body, int(time.time())),
    )
    req.conn.commit()
    render.flash(req, "ok", "Your comment was added.")
    return http.redirect("/page#comments")


def delete_comment(req, comment_id):
    account = _active_account(req)
    if not account:
        return http.redirect("/")
    if req.method == "POST" and security.csrf_ok(req.session, req):
        req.conn.execute(
            "DELETE FROM comments WHERE id = ? AND account_id = ?",
            (comment_id, account["id"]),
        )
        req.conn.commit()
        render.flash(req, "ok", "Comment deleted.")
    return http.redirect("/page#comments")


def theme_css(req):
    """Dynamic stylesheet for the site-wide background chosen in the admin panel."""
    kind = db.get_setting(req.conn, "bg_type", "default")
    css = ""
    if kind == "color":
        color = db.get_setting(req.conn, "bg_color", "#05060d")
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#05060d"
        css = ":root{--custom-bg:%s;}\nbody.has-custom-bg .backdrop{background:var(--custom-bg);}" % color
    elif kind == "gradient":
        key = db.get_setting(req.conn, "bg_gradient", "aurora")
        gradient = config.GRADIENTS.get(key, config.GRADIENTS["aurora"])
        css = "body.has-custom-bg .backdrop{background:%s;}" % gradient
    elif kind == "image":
        media_id = db.get_setting(req.conn, "bg_media_id", "")
        row = None
        if media_id.isdigit():
            row = db.one(req.conn, "SELECT * FROM media WHERE id = ?", (int(media_id),))
        if row and row["kind"] == "video":
            css = "body.has-custom-bg .backdrop{background:transparent;}"
        elif row:
            css = (
                "body.has-custom-bg .backdrop{background:url('/media/%d') "
                "center/cover no-repeat fixed;}" % row["id"]
            )
        else:
            css = "body.has-custom-bg .backdrop{background:url('/background') center/cover no-repeat fixed;}"
    if kind != "default":
        css += (
            "\nbody.has-custom-bg .aurora{opacity:.12}"
            "\nbody.has-custom-bg .grid{opacity:.08}"
            "\nbody.has-custom-bg .vignette{opacity:.3}"
        )
    return http.Response(
        200, css,
        {"Content-Type": "text/css; charset=utf-8", "Cache-Control": "no-store"},
    )


def background_image(req):
    if db.get_setting(req.conn, "bg_type", "default") != "image":
        return http.not_found()
    filename = db.get_setting(req.conn, "bg_image", "")
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return http.not_found()
    path = os.path.join(config.BACKGROUND_DIR, filename)
    if not os.path.isfile(path):
        return http.not_found()
    with open(path, "rb") as handle:
        data = handle.read()
    return http.binary(
        data,
        db.get_setting(req.conn, "bg_image_mime", "image/jpeg"),
        extra={"X-Content-Type-Options": "nosniff"},
    )


def media_file(req, media_id):
    """Public: site backgrounds must load on the landing page for visitors."""
    row = db.one(req.conn, "SELECT * FROM media WHERE id = ?", (media_id,))
    if not row:
        return http.not_found()
    filename = row["filename"]
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return http.not_found()
    path = os.path.join(config.MEDIA_DIR, filename)
    if not os.path.isfile(path):
        return http.not_found()
    with open(path, "rb") as handle:
        data = handle.read()
    return http.binary(
        data, row["mime"], extra={"X-Content-Type-Options": "nosniff"}
    )


def image(req, image_id):
    row = db.one(req.conn, "SELECT * FROM images WHERE id = ?", (image_id,))
    if not row:
        return http.not_found()
    allowed = req.session.get("account_id") == row["account_id"] or bool(
        req.session.get("admin_id")
    )
    if not allowed:
        return http.not_found()
    filename = row["filename"]
    if not filename or "/" in filename or "\\" in filename or ".." in filename:
        return http.not_found()
    path = os.path.join(config.UPLOAD_DIR, filename)
    if not os.path.isfile(path):
        return http.not_found()
    with open(path, "rb") as handle:
        data = handle.read()
    return http.binary(
        data, row["mime"], extra={"X-Content-Type-Options": "nosniff"}
    )


def logout(req):
    if req.method == "POST" and security.csrf_ok(req.session, req):
        req.session.clear()
        req.session.regenerate()
        render.flash(req, "ok", "You have been logged out.")
    return http.redirect("/")
