# invites.example.com — personal invite pages

A small, dependency-free Python app for private, personalised pages. You create the
accounts and the content; each person gets a secret invite link that opens **their**
page with a message, pictures and links.

No pip packages, no database server, no Node. Just Python 3 (stdlib) + SQLite,
running behind Caddy on the same server as your main site.

## What it does

- **Admin panel** at `/admin`: create accounts, write each person's message, upload
  pictures, add link cards, and create/revoke invite links.
- **Invite links** support all three safety options, in any combination:
  - one link per person (each account can have several links),
  - optionally ask the visitor to enter their name,
  - optionally set an expiry date and/or a maximum number of uses (e.g. one-time).
- **Login is the link itself.** No passwords for visitors. The link is a bearer
  credential — treat it like a password and send it privately.
- **Private images.** Uploads live outside the web root and are only served to that
  account's visitor or the admin.
- **Site-wide background picker** in `/admin`: solid color, preset gradients, or any
  picture/video from your uploaded media library, applied to every page. Uploads can
  be picked from the dropdown or the thumbnail menu; "Use" applies instantly.
- **Comments on each person’s page.** Active recipients can leave a comment under
  their own page, delete their own comments, and only they and you can read them.
  You can delete any comment from that account in `/admin`.
- **No visible branding.** A tiny 🐈‍⬛ button in the top-right opens the admin panel.
- Safe by default: CSRF tokens, hashed passwords, rate-limited admin login, strict
  session cookies, CSP, and HTML-escaped content with a limited Markdown subset.

## Deploy with one command

**Run this on your own computer, not in an SSH session on the server.** The folder
exists on your computer; `deploy.sh` copies it to the server over SSH.

The source lives on GitHub at <https://github.com/OWNER/ja-site>. Clone it, then
deploy from the clone:

```sh
gh repo clone OWNER/ja-site
cd ja-site
cp .deploy.env.example .deploy.env   # then set JA_SSH to your server
./deploy.sh
```

`deploy.sh` deploys the working tree it sits in and never uploads `storage/`, `.git/`,
`.deploy.env` or `.env` files. If the tree has uncommitted changes it says so first,
and on a clean checkout it prints the commit it is deploying.

The SSH target is not stored in the repo: put it in the gitignored `.deploy.env`
(an alias from `~/.ssh/config` or `user@host`), or pass it as the first argument.
Other defaults: remote folder `/opt/ja-site`, public URL `https://invites.example.com`,
local port `8080`. The script uploads the app (keeping any existing `storage/`
data), creates a `jasite` service user, installs and starts the systemd service,
and adds the Caddy block if it can find the Caddyfile. It prints anything still
left to do.

Override with `./deploy.sh user@server /opt/ja-site`, `JA_PORT=8090 ./deploy.sh`,
or `SKIP_CADDY=1 ./deploy.sh` to leave Caddy alone.

Need an SSH key on the server first? Run `ssh-copy-id user@server`.

### If you are already logged into the server

On your **own computer**, make a tarball and copy it up:

```sh
cd path/to/ja-site
tar czf /tmp/ja-site.tar.gz .
scp /tmp/ja-site.tar.gz user@server:/tmp/
```

Then on the **server**:

```sh
mkdir -p /tmp/ja-site
tar xzf /tmp/ja-site.tar.gz -C /tmp/ja-site
cd /tmp/ja-site
chmod +x install-server.sh
./install-server.sh
```

`install-server.sh` installs into `/opt/ja-site` by default, creates the service
user and systemd unit, starts the app, and adds the Caddy block.

## Manual install

1. Put this folder somewhere, e.g. `/srv/ja-site`:

   ```sh
   mkdir -p /srv/ja-site
   # copy the contents of ja-site/ into /srv/ja-site
   chmod +x /srv/ja-site/run.sh
   ```

2. Test it by hand (should print a listening line):

   ```sh
   cd /srv/ja-site && ./run.sh
   ```

   Then `curl -I http://127.0.0.1:8080/` from the server.

3. Run it as a service. Copy `ja-site.service` into
   `/etc/systemd/system/ja-site.service`, change `User=YOUR_USER` and make sure
   `WorkingDirectory=` and `ReadWritePaths=` match where you put the folder.
   Then:

   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable --now ja-site
   systemctl status ja-site
   ```

4. Add the block from `Caddyfile.example` to your Caddyfile and reload Caddy.
   DNS for `invites.example.com` must point at the server; Caddy gets the certificate.

5. Visit **https://invites.example.com/admin/setup** once to create your admin username and
   password. That page turns itself off afterwards. Then sign in at `/admin`.

## Using it

1. In `/admin`, create an account (a person).
2. Open the account and fill in the greeting headline and message. Formatting:
   `# heading`, `**bold**`, `*italic*`, `- bullet`, `[text](https://example.com)`.
3. Upload pictures and add link cards. Use the "Order" numbers to arrange them.
4. Under "Invite links", pick a preset or set the options yourself, create the link,
   click it once to copy it, and send it privately to that person.
5. Revoke a link any time — the visitor keeps their current session until it expires,
   but the link can no longer be used to log in again.
6. When an active recipient opens their page, they can add a comment under the
   message, pictures and links. Comments are private to that person and to you.
   They can delete their own; you can delete any from the account’s admin page.

The three invite options can be combined. "All options" means: ask for a name,
expires at the chosen time, single use. Times are entered in UTC.

## Configuration

Environment variables (set them in the systemd unit):

| Variable | Default | Purpose |
|---|---|---|
| `JA_BASE_URL` | `https://invites.example.com` | Used when showing/copying invite links |
| `JA_SITE_NAME` | `invites.example.com` | Title/footer text |
| `JA_HOST` | `127.0.0.1` | Listen address (keep loopback behind Caddy) |
| `JA_PORT` | `8080` | Listen port |
| `JA_STORAGE` | `./storage` | Database, uploads and private files |

## Backups

Back up `storage/ja.db`, `storage/uploads/`, `storage/backgrounds/` and
`storage/media/`. That is the whole site. With the
default WAL mode, back up `ja.db`, `ja.db-wal` and `ja.db-shm` together, or use
`sqlite3 storage/ja.db ".backup /path/to/backup.db"`.

## Files

```
app/            Python source (routes, security, rendering) and static CSS/JS
storage/        created at runtime: SQLite DB, private uploads, backgrounds,
                background media library (not web-served directly)
Caddyfile.example
ja-site.service
run.sh
```
