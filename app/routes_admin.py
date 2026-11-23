"""Admin routes: accounts, invites, images and links."""

import os
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import config, db, http, markdown, render, security
from .render import e, csrf_input, invite_status


def _admin(req):
    admin_id = req.session.get("admin_id")
    if not admin_id:
        return None
    return db.one(req.conn, "SELECT id, username FROM admins WHERE id = ?", (admin_id,))


def _need_admin(req):
    return _admin(req) is None


def _account(req, account_id):
    return db.one(req.conn, "SELECT * FROM accounts WHERE id = ?", (account_id,))


def _safe_url(value):
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return value.strip()


def _parse_expiry(value):
    value = (value or "").strip()
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return int(moment.timestamp())
    except ValueError:
        return None


def _sniff_image(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", "gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def _sniff_video(data, filename=""):
    name = (filename or "").lower()
    if len(data) >= 8 and data[4:8] == b"ftyp":  # ISO BMFF: mp4 / mov / m4v
        if name.endswith(".mov"):
            return "video/quicktime", "mov"
        return "video/mp4", "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":  # EBML: webm / mkv
        if name.endswith(".mkv"):
            return "video/x-matroska", "mkv"
        return "video/webm", "webm"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"AVI ":
        return "video/x-msvideo", "avi"
    return None


def _sniff_media(data, filename=""):
    image = _sniff_image(data)
    if image:
        return image[0], image[1], "image"
    video = _sniff_video(data, filename)
    if video:
        return video[0], video[1], "video"
    return None


def _safe_name(value, default="upload"):
    name = re.sub(r"[^.\w -]", "", value or "").strip()[:200]
    return name or default


# ---------------------------------------------------------------- admin auth


def setup(req):
    count = db.one(req.conn, "SELECT COUNT(*) AS n FROM admins")["n"]
    if count:
        return http.not_found()
    error = ""
    if req.method == "POST":
        if not security.csrf_ok(req.session, req):
            error = "That form expired. Please try again."
        else:
            username = req.form.get("username", "").strip()[:80]
            password = req.form.get("password", "")
            confirm = req.form.get("confirm", "")
            if len(username) < 3:
                error = "Choose a username of at least 3 characters."
            elif len(password) < 12:
                error = "Use a password of at least 12 characters."
            elif password != confirm:
                error = "The two passwords do not match."
            else:
                cursor = req.conn.execute(
                    "INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, security.hash_password(password), int(time.time())),
                )
                req.conn.commit()
                req.session.set("admin_id", cursor.lastrowid)
                req.session.regenerate()
                render.flash(req, "ok", "Admin account created.")
                return http.redirect("/admin")
    body = """
<section class="center"><article class="card narrow">
  <p class="eyebrow">one-time setup</p>
  <h1>Create your admin login</h1>
  <p class="muted">This page disappears once the admin account exists.</p>
  %s
  <form method="post" class="stack">
    %s
    <label class="field">Username<input name="username" autocomplete="username" required minlength="3" maxlength="80"></label>
    <label class="field">Password<input name="password" type="password" autocomplete="new-password" required minlength="12"></label>
    <label class="field">Confirm password<input name="confirm" type="password" autocomplete="new-password" required minlength="12"></label>
    <button class="button primary" type="submit">Create admin account</button>
  </form>
</article></section>""" % (
        ('<div class="flash error">%s</div>' % e(error)) if error else "",
        csrf_input(req),
    )
    return http.html(render.layout("Admin setup", body, req=req, admin=True))


def login(req):
    if req.session.get("admin_id"):
        return http.redirect("/admin")
    count = db.one(req.conn, "SELECT COUNT(*) AS n FROM admins")["n"]
    if not count:
        return http.redirect("/admin/setup")
    error = ""
    if req.method == "POST":
        if not security.csrf_ok(req.session, req):
            error = "That form expired. Please try again."
        elif security.login_blocked(req.conn, req):
            error = "Too many attempts. Wait a few minutes and try again."
        else:
            username = req.form.get("username", "").strip()
            password = req.form.get("password", "")
            row = db.one(req.conn, "SELECT * FROM admins WHERE username = ?", (username,))
            if not row or not security.verify_password(password, row["password_hash"]):
                time.sleep(0.25)
                security.login_failed(req.conn, req)
                error = "Wrong username or password."
            else:
                security.login_succeeded(req.conn, req)
                req.session.set("admin_id", row["id"])
                req.session.regenerate()
                render.flash(req, "ok", "Signed in.")
                return http.redirect("/admin")
    body = """
<section class="center"><article class="card narrow">
  <p class="eyebrow">admin</p>
  <h1>Sign in</h1>
  %s
  <form method="post" class="stack">
    %s
    <label class="field">Username<input name="username" autocomplete="username" required></label>
    <label class="field">Password<input name="password" type="password" autocomplete="current-password" required></label>
    <button class="button primary" type="submit">Sign in</button>
  </form>
</article></section>""" % (
        ('<div class="flash error">%s</div>' % e(error)) if error else "",
        csrf_input(req),
    )
    return http.html(render.layout("Admin sign in", body, req=req, admin=True))


def logout(req):
    if req.method == "POST" and security.csrf_ok(req.session, req):
        req.session.pop("admin_id", None)
        req.session.regenerate()
        render.flash(req, "ok", "Signed out.")
    return http.redirect("/admin/login")


# ---------------------------------------------------------------- dashboard


def dashboard(req):
    if _need_admin(req):
        return http.redirect("/admin/login")
    accounts = db.all_rows(
        req.conn,
        """SELECT a.*,
                  (SELECT COUNT(*) FROM invites i WHERE i.account_id = a.id AND i.revoked = 0) AS invite_count
           FROM accounts a ORDER BY a.id""",
    )
    cards = ""
    for account in accounts:
        cards += """<a class="card account-card" href="/admin/account/%d">
  <span class="tag">%s</span><strong>%s</strong>
  <span class="muted small">%d active invite link%s · created %s</span>
  <span class="arrow" aria-hidden="true">→</span>
</a>""" % (
            account["id"],
            "active" if account["active"] else "disabled",
            e(account["name"]),
            account["invite_count"],
            "" if account["invite_count"] == 1 else "s",
            e(datetime.fromtimestamp(account["created_at"], timezone.utc).strftime("%d %b %Y")),
        )
    if not cards:
        cards = '<p class="muted">No accounts yet. Create the first one below.</p>'

    bg_type = db.get_setting(req.conn, "bg_type", "default")
    bg_color = db.get_setting(req.conn, "bg_color", "#05060d")
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", bg_color):
        bg_color = "#05060d"
    bg_gradient = db.get_setting(req.conn, "bg_gradient", "aurora")
    bg_media_id = db.get_setting(req.conn, "bg_media_id", "")
    media = db.all_rows(req.conn, "SELECT * FROM media ORDER BY id DESC")
    type_options = "".join(
        '<option value="%s"%s>%s</option>'
        % (key, " selected" if key == bg_type else "", label)
        for key, label in [
            ("default", "Default glow"),
            ("color", "Solid color"),
            ("gradient", "Gradient"),
            ("image", "Picture / video from library"),
        ]
    )
    gradient_options = "".join(
        '<option value="%s"%s>%s</option>'
        % (key, " selected" if key == bg_gradient else "", key.capitalize())
        for key in config.GRADIENTS
    )
    media_options = '<option value=""%s>No media selected</option>' % (
        "" if bg_media_id else " selected"
    )
    media_grid = ""
    for item in media:
        selected = str(item["id"]) == bg_media_id
        label = ("🖼 " if item["kind"] == "image" else "🎬 ") + item["original_name"]
        media_options += '<option value="%d"%s>%s</option>' % (
            item["id"], " selected" if selected else "", e(label)
        )
        preview = (
            '<img class="preview" src="/media/%d" alt="">'
            if item["kind"] == "image"
            else '<video class="preview" src="/media/%d" muted playsinline></video>'
        ) % item["id"]
        csrf_field = '<input type="hidden" name="csrf" value="%s">' % e(
            security.csrf_token(req.session)
        )
        media_grid += """<div class="media-item%s">
  %s
  <span class="name" title="%s">%s</span>
  <div class="row">
    <form method="post" action="/admin/media/%d/choose" class="inline">%s<button class="button tiny" type="submit">Use</button></form>
    <form method="post" action="/admin/media/%d/delete" class="inline">%s<button class="button tiny danger" type="submit" data-confirm="Delete this file?">Delete</button></form>
  </div>
</div>""" % (
            " is-active" if selected else "",
            preview,
            e(item["original_name"]),
            e(item["original_name"]),
            item["id"], csrf_field,
            item["id"], csrf_field,
        )
    if not media_grid:
        media_grid = '<p class="muted small">Nothing uploaded yet. Add pictures or videos below.</p>'

    body = """
<section>
  <p class="eyebrow rainbow-text">overview</p>
  <h1 class="title">Accounts</h1>
  <div class="account-grid">%s</div>
</section>
<section class="narrow-left">
  <article class="card">
    <h2>Site background</h2>
    <p class="muted small">Applies to every page on the site, including your visitors' pages.</p>
    <form method="post" action="/admin/background" class="stack">
      %s
      <label class="field">Background style<select name="bg_type">%s</select></label>
      <label class="field">Solid color<input type="color" name="bg_color" value="%s"></label>
      <label class="field">Gradient<select name="bg_gradient">%s</select></label>
      <label class="field">Picture or video<select name="bg_media_id">%s</select></label>
      <label class="upload-box">Upload pictures or videos
        <input type="file" id="media-upload" accept="image/*,video/*" multiple
               data-url="/admin/media/upload" data-csrf="%s">
      </label>
      <p class="muted small" id="media-upload-status"></p>
      <button class="button primary" type="submit">Save background</button>
    </form>
    <h3>Uploaded media</h3>
    <div class="media-grid">%s</div>
  </article>
</section>
<section class="narrow-left">
  <article class="card">
    <h2>New account</h2>
    <p class="muted small">Create a person, then add a message, pictures, links and an invite link.</p>
    <form method="post" action="/admin/account" class="stack">
      %s
      <label class="field">Name<input name="name" maxlength="120" required placeholder="e.g. Emma"></label>
      <button class="button primary" type="submit">Create account</button>
    </form>
  </article>
</section>""" % (
        cards,
        csrf_input(req),
        type_options,
        bg_color,
        gradient_options,
        media_options,
        e(security.csrf_token(req.session)),
        media_grid,
        csrf_input(req),
    )
    return http.html(render.layout("Accounts", body, req=req, admin=True))


def create_account(req):
    if _need_admin(req):
        return http.redirect("/admin/login")
    if req.method != "POST":
        return http.not_found()
    if not security.csrf_ok(req.session, req):
        return http.redirect("/admin")
    name = req.form.get("name", "").strip()[:120]
    if not name:
        render.flash(req, "error", "A name is required.")
        return http.redirect("/admin")
    now = int(time.time())
    cursor = req.conn.execute(
        "INSERT INTO accounts (name, created_at, updated_at) VALUES (?, ?, ?)",
        (name, now, now),
    )
    req.conn.commit()
    render.flash(req, "ok", "Account created. Now add the content and an invite link.")
    return http.redirect("/admin/account/%d" % cursor.lastrowid)


# ---------------------------------------------------------------- edit page


def account(req, account_id):
    if _need_admin(req):
        return http.redirect("/admin/login")
    acc = _account(req, account_id)
    if not acc:
        return http.not_found()

    invites = db.all_rows(
        req.conn, "SELECT * FROM invites WHERE account_id = ? ORDER BY id DESC", (account_id,)
    )
    images = db.all_rows(
        req.conn,
        "SELECT * FROM images WHERE account_id = ? ORDER BY position, id",
        (account_id,),
    )
    links = db.all_rows(
        req.conn, "SELECT * FROM links WHERE account_id = ? ORDER BY position, id", (account_id,)
    )
    now = int(time.time())

    invite_rows = ""
    for inv in invites:
        status = invite_status(inv, now)
        limit = "∞" if inv["max_uses"] is None else str(inv["max_uses"])
        expiry = (
            datetime.fromtimestamp(inv["expires_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if inv["expires_at"]
            else "never"
        )
        url = config.BASE_URL + "/i/" + inv["token"]
        invite_rows += """<div class="row">
  <div class="row-main">
    <strong>%s</strong>
    <span class="muted small">%s · used %s/%s · expires %s</span>
    <code class="invite-url" data-copy="%s">%s</code>
  </div>
  <div class="row-actions">
    <span class="pill %s">%s</span>
    %s
  </div>
</div>""" % (
            e(inv["label"] or "Invite link"),
            "asks for name" if inv["require_name"] else "no name needed",
            inv["uses"],
            limit,
            e(expiry),
            e(url),
            e(url),
            e(status.replace(" ", "-")),
            e(status),
            ""
            if inv["revoked"]
            else '<form method="post" action="/admin/account/%d/invite/%d/revoke">%s<button class="button tiny danger" type="submit">Revoke</button></form>'
            % (account_id, inv["id"], csrf_input(req)),
        )
    if not invite_rows:
        invite_rows = '<p class="muted">No invite links yet. Create one below.</p>'

    image_rows = ""
    for img in images:
        image_rows += """<div class="row">
  <img class="thumb" src="/img/%d" alt="">
  <form method="post" action="/admin/account/%d/image/%d" class="row-form">
    %s
    <label class="field small-field">Caption<input name="caption" maxlength="200" value="%s"></label>
    <label class="field small-field order">Order<input name="position" type="number" value="%d"></label>
    <button class="button tiny" type="submit">Save</button>
  </form>
  <form method="post" action="/admin/account/%d/image/%d">
    %s<input type="hidden" name="action" value="delete">
    <button class="button tiny danger" type="submit">Delete</button>
  </form>
</div>""" % (
            img["id"],
            account_id,
            img["id"],
            csrf_input(req),
            e(img["caption"]),
            img["position"],
            account_id,
            img["id"],
            csrf_input(req),
        )
    if not image_rows:
        image_rows = '<p class="muted">No pictures yet. Upload one below.</p>'

    link_rows = ""
    for link in links:
        link_rows += """<div class="row">
  <form method="post" action="/admin/account/%d/link/%d" class="row-form">
    %s
    <label class="field small-field">Title<input name="title" maxlength="120" value="%s" required></label>
    <label class="field small-field">URL<input name="url" maxlength="500" value="%s" required></label>
    <label class="field small-field">Description<input name="description" maxlength="200" value="%s"></label>
    <label class="field small-field order">Order<input name="position" type="number" value="%d"></label>
    <button class="button tiny" type="submit">Save</button>
  </form>
  <form method="post" action="/admin/account/%d/link/%d">
    %s<input type="hidden" name="action" value="delete">
    <button class="button tiny danger" type="submit">Delete</button>
  </form>
</div>""" % (
            account_id,
            link["id"],
            csrf_input(req),
            e(link["title"]),
            e(link["url"]),
            e(link["description"]),
            link["position"],
            account_id,
            link["id"],
            csrf_input(req),
        )
    if not link_rows:
        link_rows = '<p class="muted">No links yet. Add one below.</p>'

    body = """
<section>
  <p class="eyebrow"><a class="accent rainbow-text" href="/admin">← all accounts</a></p>
  <h1 class="title">Editing %s</h1>
  <article class="card">
    <h2>Page content</h2>
    <form method="post" action="/admin/account/%d/details" class="stack">
      %s
      <label class="field">Display name<input name="name" maxlength="120" value="%s" required></label>
      <label class="field">Greeting headline<input name="greeting" maxlength="160" value="%s" placeholder="Leave blank to use their name"></label>
      <label class="field">Message<textarea name="message" rows="10" placeholder="Write the personal message here...">%s</textarea></label>
      <p class="muted small">Formatting: # heading, **bold**, *italic*, - bullet, [text](https://example.com). Keep it simple.</p>
      <label class="check"><input type="checkbox" name="active" value="1" %s> Account active</label>
      <button class="button primary" type="submit">Save content</button>
    </form>
  </article>
</section>

<section class="narrow-left">
  <article class="card">
    <h2>Invite links</h2>
    <p class="muted small">Mix and match all three safety options. A link with one-time use and an expiry date uses both.</p>
    <div class="presets">
      <button type="button" class="button tiny" data-preset="simple">Simple link</button>
      <button type="button" class="button tiny" data-preset="name">Ask for name</button>
      <button type="button" class="button tiny" data-preset="once">One-time link</button>
      <button type="button" class="button tiny" data-preset="full">All options</button>
    </div>
    <form method="post" action="/admin/account/%d/invite" class="stack" id="invite-form">
      %s
      <label class="field">Label<input name="label" maxlength="120" placeholder="e.g. Emma's link"></label>
      <label class="check"><input type="checkbox" name="require_name" value="1" id="invite-name"> Ask visitor to enter their name</label>
      <div class="two-col">
        <label class="field">Expires at (UTC)<input name="expires_at" type="datetime-local" id="invite-expiry"></label>
        <label class="field">Max uses<input name="max_uses" type="number" min="1" max="1000" placeholder="blank = unlimited" id="invite-uses"></label>
      </div>
      <button class="button primary" type="submit">Create invite link</button>
    </form>
    <div class="divider"></div>
    %s
  </article>
</section>

<section class="narrow-left">
  <article class="card">
    <h2>Pictures</h2>
    <p class="muted small">JPG, PNG, GIF or WebP, up to 10 MB each. Only this account and you can view them.</p>
    <label class="upload-box">
      <span>Choose pictures to upload</span>
      <input type="file" id="image-upload" accept="image/png,image/jpeg,image/gif,image/webp" multiple
             data-url="/admin/account/%d/image/upload" data-csrf="%s">
    </label>
    <p class="muted small" id="upload-status"></p>
    <div class="divider"></div>
    %s
  </article>
</section>

<section class="narrow-left">
  <article class="card">
    <h2>Links</h2>
    <form method="post" action="/admin/account/%d/link" class="stack">
      %s
      <div class="two-col">
        <label class="field">Title<input name="title" maxlength="120" required></label>
        <label class="field">URL<input name="url" maxlength="500" required placeholder="https://..."></label>
      </div>
      <label class="field">Description<input name="description" maxlength="200"></label>
      <label class="field small-field order">Order<input name="position" type="number" value="0"></label>
      <button class="button primary" type="submit">Add link</button>
    </form>
    <div class="divider"></div>
    %s
  </article>
</section>

<section class="narrow-left">
  <article class="card danger-zone">
    <h2>Danger zone</h2>
    <form method="post" action="/admin/account/%d/delete">
      %s<button class="button tiny danger" type="submit" data-confirm="Delete this account and all its content?">Delete account</button>
    </form>
  </article>
</section>""" % (
        e(acc["name"]),
        account_id,
        csrf_input(req),
        e(acc["name"]),
        e(acc["greeting"]),
        e(acc["message"]),
        "checked" if acc["active"] else "",
        account_id,
        csrf_input(req),
        invite_rows,
        account_id,
        e(security.csrf_token(req.session)),
        image_rows,
        account_id,
        csrf_input(req),
        link_rows,
        account_id,
        csrf_input(req),
    )
    return http.html(render.layout("Edit " + acc["name"], body, req=req, admin=True))


def update_details(req, account_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin/account/%d" % account_id)
    req.conn.execute(
        """UPDATE accounts SET name = ?, greeting = ?, message = ?, active = ?, updated_at = ?
           WHERE id = ?""",
        (
            req.form.get("name", "").strip()[:120] or "Unnamed",
            req.form.get("greeting", "").strip()[:160],
            req.form.get("message", "")[:20000],
            1 if req.form.get("active") == "1" else 0,
            int(time.time()),
            account_id,
        ),
    )
    req.conn.commit()
    render.flash(req, "ok", "Content saved.")
    return http.redirect("/admin/account/%d" % account_id)


def create_invite(req, account_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin/account/%d" % account_id)
    token = security.new_token()
    max_uses_raw = req.form.get("max_uses", "").strip()
    try:
        max_uses = int(max_uses_raw) if max_uses_raw else None
        if max_uses is not None and not 1 <= max_uses <= 1000:
            max_uses = None
    except ValueError:
        max_uses = None
    req.conn.execute(
        """INSERT INTO invites
           (account_id, token_hash, token, label, require_name, expires_at, max_uses, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            account_id,
            security.token_hash(token),
            token,
            req.form.get("label", "").strip()[:120],
            1 if req.form.get("require_name") == "1" else 0,
            _parse_expiry(req.form.get("expires_at")),
            max_uses,
            int(time.time()),
        ),
    )
    req.conn.commit()
    render.flash(req, "ok", "Invite link created. Copy it and send it privately.")
    return http.redirect("/admin/account/%d" % account_id)


def save_background(req):
    if _need_admin(req):
        return http.redirect("/admin/login")
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin")
    kind = req.form.get("bg_type", "default")
    if kind not in ("default", "color", "gradient", "image"):
        kind = "default"
    media_id = req.form.get("bg_media_id", "").strip()
    if media_id.isdigit():
        row = db.one(req.conn, "SELECT id FROM media WHERE id = ?", (int(media_id),))
        media_id = str(row["id"]) if row else ""
    else:
        media_id = ""
    if kind == "image" and not media_id and not db.get_setting(req.conn, "bg_image", ""):
        render.flash(req, "error", "Upload a picture or video first.")
        return http.redirect("/admin")
    if media_id:
        db.set_setting(req.conn, "bg_media_id", media_id)
    color = req.form.get("bg_color", "").strip()
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        color = "#05060d"
    gradient = req.form.get("bg_gradient", "aurora")
    if gradient not in config.GRADIENTS:
        gradient = "aurora"
    db.set_setting(req.conn, "bg_type", kind)
    db.set_setting(req.conn, "bg_color", color)
    db.set_setting(req.conn, "bg_gradient", gradient)
    render.flash(req, "ok", "Background saved.")
    return http.redirect("/admin")


def upload_media(req):
    if _need_admin(req):
        return http.as_json({"ok": False, "error": "Not authorised."}, 403)
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.as_json({"ok": False, "error": "Invalid request."}, 400)
    data = req.body
    if not data:
        return http.as_json({"ok": False, "error": "That file is empty."}, 400)
    original = _safe_name(req.headers.get("x-filename", ""), "upload")
    sniffed = _sniff_media(data, original)
    if not sniffed:
        return http.as_json(
            {"ok": False, "error": "Use a JPG, PNG, GIF, WebP, MP4, WebM, MOV or AVI file."},
            400,
        )
    mime, ext, kind = sniffed
    limit = config.MAX_VIDEO_UPLOAD if kind == "video" else config.MAX_UPLOAD
    if len(data) > limit:
        return http.as_json(
            {"ok": False, "error": "Images must be under 10 MB; videos under 100 MB."}, 400
        )
    filename = "%s.%s" % (os.urandom(16).hex(), ext)
    path = os.path.join(config.MEDIA_DIR, filename)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    cursor = req.conn.execute(
        """INSERT INTO media (filename, original_name, mime, kind, size, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (filename, original, mime, kind, len(data), int(time.time())),
    )
    req.conn.commit()
    db.set_setting(req.conn, "bg_media_id", str(cursor.lastrowid))
    db.set_setting(req.conn, "bg_type", "image")
    return http.as_json({"ok": True, "id": cursor.lastrowid, "kind": kind})


def upload_background(req):
    """Old upload endpoint, kept so existing bookmarks keep working."""
    return upload_media(req)


def choose_media(req, media_id):
    if _need_admin(req):
        return http.redirect("/admin/login")
    if not db.one(req.conn, "SELECT id FROM media WHERE id = ?", (media_id,)):
        return http.not_found()
    if req.method == "POST" and security.csrf_ok(req.session, req):
        db.set_setting(req.conn, "bg_media_id", str(media_id))
        db.set_setting(req.conn, "bg_type", "image")
        render.flash(req, "ok", "Background updated.")
    return http.redirect("/admin")


def delete_media(req, media_id):
    if _need_admin(req):
        return http.redirect("/admin/login")
    row = db.one(req.conn, "SELECT * FROM media WHERE id = ?", (media_id,))
    if not row:
        return http.not_found()
    if req.method == "POST" and security.csrf_ok(req.session, req):
        req.conn.execute("DELETE FROM media WHERE id = ?", (media_id,))
        req.conn.commit()
        try:
            os.remove(os.path.join(config.MEDIA_DIR, row["filename"]))
        except OSError:
            pass
        if db.get_setting(req.conn, "bg_media_id", "") == str(media_id):
            db.set_setting(req.conn, "bg_media_id", "")
            db.set_setting(req.conn, "bg_type", "default")
        render.flash(req, "ok", "File removed from the library.")
    return http.redirect("/admin")


def revoke_invite(req, account_id, invite_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method == "POST" and security.csrf_ok(req.session, req):
        req.conn.execute(
            "UPDATE invites SET revoked = 1 WHERE id = ? AND account_id = ?",
            (invite_id, account_id),
        )
        req.conn.commit()
        render.flash(req, "ok", "Invite link revoked.")
    return http.redirect("/admin/account/%d" % account_id)


def upload_image(req, account_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.as_json({"ok": False, "error": "Not authorised."}, 403)
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.as_json({"ok": False, "error": "Invalid request."}, 400)
    data = req.body
    if not data or len(data) > config.MAX_UPLOAD:
        return http.as_json({"ok": False, "error": "Image is empty or larger than 10 MB."}, 400)
    sniffed = _sniff_image(data)
    if not sniffed:
        return http.as_json({"ok": False, "error": "Use a JPG, PNG, GIF or WebP image."}, 400)
    mime, ext = sniffed
    original = re.sub(r"[^.\w -]", "", req.headers.get("x-filename", "image"))[:200] or "image"
    filename = "%s.%s" % (os.urandom(16).hex(), ext)
    path = os.path.join(config.UPLOAD_DIR, filename)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    req.conn.execute(
        """INSERT INTO images (account_id, filename, original_name, mime, size, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (account_id, filename, original, mime, len(data), int(time.time())),
    )
    req.conn.commit()
    return http.as_json({"ok": True})


def update_image(req, account_id, image_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin/account/%d" % account_id)
    row = db.one(
        req.conn, "SELECT * FROM images WHERE id = ? AND account_id = ?", (image_id, account_id)
    )
    if not row:
        return http.not_found()
    if req.form.get("action") == "delete":
        req.conn.execute("DELETE FROM images WHERE id = ?", (image_id,))
        try:
            os.remove(os.path.join(config.UPLOAD_DIR, row["filename"]))
        except OSError:
            pass
        render.flash(req, "ok", "Picture deleted.")
    else:
        try:
            position = int(req.form.get("position", "0"))
        except ValueError:
            position = 0
        req.conn.execute(
            "UPDATE images SET caption = ?, position = ? WHERE id = ?",
            (req.form.get("caption", "").strip()[:200], position, image_id),
        )
        render.flash(req, "ok", "Picture saved.")
    req.conn.commit()
    return http.redirect("/admin/account/%d" % account_id)


def add_link(req, account_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin/account/%d" % account_id)
    url = _safe_url(req.form.get("url", ""))
    title = req.form.get("title", "").strip()[:120]
    if not url or not title:
        render.flash(req, "error", "A title and a http(s) URL are required.")
        return http.redirect("/admin/account/%d" % account_id)
    try:
        position = int(req.form.get("position", "0"))
    except ValueError:
        position = 0
    req.conn.execute(
        "INSERT INTO links (account_id, title, url, description, position) VALUES (?, ?, ?, ?, ?)",
        (account_id, title, url, req.form.get("description", "").strip()[:200], position),
    )
    req.conn.commit()
    render.flash(req, "ok", "Link added.")
    return http.redirect("/admin/account/%d" % account_id)


def update_link(req, account_id, link_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method != "POST" or not security.csrf_ok(req.session, req):
        return http.redirect("/admin/account/%d" % account_id)
    if not db.one(req.conn, "SELECT 1 FROM links WHERE id = ? AND account_id = ?", (link_id, account_id)):
        return http.not_found()
    if req.form.get("action") == "delete":
        req.conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
        render.flash(req, "ok", "Link deleted.")
    else:
        url = _safe_url(req.form.get("url", ""))
        if not url:
            render.flash(req, "error", "Links must start with http:// or https://.")
            return http.redirect("/admin/account/%d" % account_id)
        try:
            position = int(req.form.get("position", "0"))
        except ValueError:
            position = 0
        req.conn.execute(
            """UPDATE links SET title = ?, url = ?, description = ?, position = ?
               WHERE id = ?""",
            (
                req.form.get("title", "").strip()[:120] or "Link",
                url,
                req.form.get("description", "").strip()[:200],
                position,
                link_id,
            ),
        )
        render.flash(req, "ok", "Link saved.")
    req.conn.commit()
    return http.redirect("/admin/account/%d" % account_id)


def delete_account(req, account_id):
    if _need_admin(req) or not _account(req, account_id):
        return http.not_found()
    if req.method == "POST" and security.csrf_ok(req.session, req):
        files = db.all_rows(req.conn, "SELECT filename FROM images WHERE account_id = ?", (account_id,))
        req.conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        req.conn.commit()
        for item in files:
            try:
                os.remove(os.path.join(config.UPLOAD_DIR, item["filename"]))
            except OSError:
                pass
        render.flash(req, "ok", "Account deleted.")
    return http.redirect("/admin")
