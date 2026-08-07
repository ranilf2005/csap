# Security Policy

CSAP is a **prototype**. It holds credentials for, and can push configuration to, your
security infrastructure. Treat it as a highly privileged system and read this before
you deploy it anywhere that matters. See [NOTICE](NOTICE) for the warranty disclaimer.

## Reporting a vulnerability

Open a GitHub issue with the label `security`, or contact the maintainer privately if
the issue is exploitable. There is no commercial support and no guaranteed response time.

## Deployment guidance

CSAP is designed to run on a **management network**, not on the internet.

| Control | Why it matters |
| --- | --- |
| Put CSAP behind your normal management-network access controls | Anyone who reaches the login page can attempt to reach your firewalls |
| Replace the self-signed certificate with one your clients trust | The default certificate cannot be validated, so TLS gives you encryption but not authentication |
| Change the installation password at first login | This is now enforced: no other API call succeeds until you do |
| Keep `.env` at mode 600 and back it up separately | It holds `CREDENTIAL_ENCRYPTION_KEY`, which decrypts every stored device password |
| Restrict membership of the host `docker` group | Membership is equivalent to root, and exposes container environment variables |
| Restrict access to `backups/` | Backups contain the encryption key and the encrypted credentials together |

## What CSAP does to protect you

- Device passwords are encrypted at rest with Fernet (AES-128-CBC + HMAC); the key never
  enters the database.
- Passwords are hashed with bcrypt. The login endpoint spends the same time on unknown
  accounts as on real ones, so it does not reveal which addresses exist.
- Login is rate limited at the reverse proxy (10 requests/minute/IP) on both the web form
  and the API endpoint.
- Changing a password immediately invalidates every token issued before the change.
- All queries use parameterised SQLAlchemy; no user input reaches raw SQL or a shell.
- Device data written into Excel exports is forced to text, so a maliciously named object
  cannot become a live formula on the workstation that opens the file.
- Device addresses that resolve to loopback, link-local (including `169.254.169.254`) or
  multicast are refused, so the platform cannot be aimed at itself or at cloud metadata.
- Every response carries HSTS, `X-Frame-Options`, `X-Content-Type-Options`, a strict
  `Content-Security-Policy`, and `frame-ancestors 'none'`.
- Containers run as non-root. The Docker socket is never mounted. PostgreSQL and Redis are
  not published to the host in the production compose file.
- Configuration changes, logins and deployments are recorded in an append-only audit log.

## Known limitations of this prototype

These are accepted for a prototype and **must** be addressed before production use.

| Limitation | Impact | Mitigation today |
| --- | --- | --- |
| Single admin role; no per-user RBAC | Every user can change every device | Issue one account per operator and rely on the audit log |
| Secrets are passed to containers as environment variables | Visible via `docker inspect` to the `docker` group | Restrict `docker` group membership; use a secrets manager in production |
| No CSRF tokens on forms | Cross-site form submission | Session cookie is `SameSite=Lax`, which blocks cross-site POST in current browsers |
| Uploaded workbooks are parsed with openpyxl | A crafted `.xlsx` could consume excessive memory | Only upload workbooks you produced; the API requires authentication |
| Schema is created with `create_all`, not Alembic | Upgrades cannot alter existing tables automatically | Additive columns are applied explicitly at bootstrap; full migrations are a 1.0 requirement |
| `install.sh` prints the generated admin password | It lands in shell history and terminal scrollback | The password must be changed at first login, which invalidates it |
| No multi-factor authentication | A stolen password is enough to reach the firewalls | Restrict network access to the platform |

## Supported versions

Only the latest release receives fixes. There are no backports.
