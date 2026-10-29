# Security and data protection

## Login, users and roles

* Passwords are stored as salted **scrypt** hashes (n=2¹⁴, r=8, p=1), never in plain text.
  A password needs at least 8 characters, with letters and digits.
* Five wrong passwords lock the account for 15 minutes. Every login, failure and lock is
  in the audit log.
* On first start the desktop app asks you to create the **administrator**. Until a user
  exists, the CLI runs in *setup mode* and prints a warning. After that, every CLI command
  needs `--login USER`; the password comes from `FINTAX_PASSWORD` or a prompt.
* The last active administrator cannot be demoted or disabled.

| Permission | Admin | Partner / Manager | Accountant | Viewer |
|---|:-:|:-:|:-:|:-:|
| view, export reports, export audit log | ✓ | ✓ | ✓ | ✓ |
| import, reconcile, review exceptions, ITC claims | ✓ | ✓ | ✓ | |
| manage clients, ITC rules, settings, backups | ✓ | ✓ | | |
| restore, delete client data, manage users | ✓ | | | |
| supplier letters, prepare working papers | ✓ | ✓ | ✓ | |
| sign off working papers (not one's own) | ✓ | ✓ | | |
| sync: record client authorisation, export, import | ✓ | ✓ | | |

Permissions are enforced where the user acts:

* in the desktop app, where buttons are disabled and actions refused;
* in the CLI, checked before the command runs;
* in the web view, checked on every request.

## Encryption and backups

* **Encrypted backup** (`FTPBK1` format): a consistent SQLite backup, encrypted with
  Fernet (AES-128-CBC with HMAC-SHA256). The key is derived from your password with scrypt
  and a random salt. A wrong password or a damaged file is detected and refused.
* **Restore** first saves the current database, then checks the backup's integrity.
* **Automatic backups** run when the app starts, at most once per interval (24 h by
  default). Retention keeps at most N copies (14) and none older than D days (90); the
  newest is always kept.
* The working database is **not encrypted**, because SQLite has no built-in encryption.
  Protect the PC with full-disk encryption (BitLocker), and use encrypted backups for
  anything that leaves it.

## Deletion and retention

* `PRAGMA secure_delete=ON`: deleted rows are overwritten in the database file.
* **Purge client** (administrator only) needs the client's GSTIN typed again. It deletes
  imports, documents, runs, reviews, claims, GSTR-3B data, vendors and decisions.
  Evidence files are overwritten with random bytes before they are deleted. The database
  is then VACUUMed. The audit log keeps the purge record but drops the details of that
  client's entries.
* On SSDs and journaling file systems, overwriting is best-effort. Full-disk encryption is
  the dependable protection.

## Sync packages

* Exporting needs an **active client authorisation**: the signatory, the reference of the
  signed consent, the scope and the validity, recorded and audited. A revoked or expired
  authorisation blocks exports, and an imported package with an expired authorisation is
  refused.
* Packages (`FTPSY1`) are encrypted like backups: scrypt key from a password of at least
  10 characters, then Fernet. Only ciphertext reaches the cloud folder.
* Replay protection works per origin computer and sequence number. Local changes since
  the last sync are a conflict and are never overwritten silently: replacing them needs
  an explicit choice and takes a database backup first.

## Web view

* Read-only. Login uses the same users, lockout and roles. The session cookie is
  HMAC-signed, HttpOnly and SameSite=Strict, expires after 30 minutes and is Secure over
  HTTPS.
* `Cache-Control: no-store`, a Content Security Policy without external sources, and
  `X-Frame-Options: DENY`. API documentation endpoints are disabled.
* By default the view is served only to this computer (127.0.0.1). Serving to other
  devices is refused until users exist. It also needs a TLS certificate and key, or an
  explicit `--allow-http-lan` for a trusted office network.
* Downloads need the *export* permission and are audited.
* **Uploads** are off unless an administrator or manager enables them (`web_uploads`). They
  then need the *import* permission and a CSRF token bound to the session. They are
  limited to Excel/CSV/JSON/ZIP files of up to 25 MB, and each one is previewed and saved
  only when the uploader confirms it, within 15 minutes. Saved uploads are audited and
  kept in the data folder as source files.

## PostgreSQL deployments

* Keep the database server on the office network or behind a VPN. Use TLS
  (`sslmode=require` in the URL) and a dedicated database user, and provide the password
  through `PGPASSWORD` or a `.pgpass` file rather than the command line. The application
  never displays it.
* Backups of a server database are SQLite snapshots, so the same encrypted backup and
  restore applies.
* PostgreSQL has no secure-delete setting. Encrypt the server's disk.

## Privacy

* The application works offline. It opens no outbound connection. The only listening
  socket is the web view, and only when a user starts it.
* It never asks for GST portal user names, passwords or OTPs.
* No client data is sent to any external service, AI or otherwise.
