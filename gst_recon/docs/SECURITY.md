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

Permissions are enforced where the user acts: in the desktop app (buttons are disabled
and actions refused) and in the CLI (checked before the command runs). A future web API
must call `services.auth.require()` on every request.

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

## Privacy

* The application works fully offline and makes no network calls.
* It never asks for GST portal user names, passwords or OTPs.
* No client data is sent to any external service, AI or otherwise.
