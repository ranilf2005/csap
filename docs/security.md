---
title: Security
nav_order: 14
---

# Security

CSAP stores credentials for your firewalls and can push configuration to them. Treat the
server that runs it as a privileged management host.

The full policy, including the list of known prototype limitations, lives in
[SECURITY.md](https://github.com/ranilf2005/csap/blob/main/SECURITY.md).

## Hardening checklist before you let anyone else use it

1. **Change the installation password.** CSAP now refuses every other API call until you
   do. Changing it also signs out every existing session.
2. **Replace the certificate.** Drop your own `csap.crt` and `csap.key` into `nginx/certs/`,
   then `docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs`
   and `docker compose restart nginx`. nginx runs as uid 101 and cannot read root-owned keys.
3. **Keep it off the internet.** Bind it to a management network. The login endpoint is rate
   limited to 10 attempts per minute per IP, which slows brute force but is not a substitute
   for network access control.
4. **Protect `.env` and `backups/`.** Both contain `CREDENTIAL_ENCRYPTION_KEY`, which decrypts
   every stored device password. `scripts/backup.sh` sets mode 600, but the directory is only
   as safe as the host.
5. **Restrict the `docker` group.** Membership is equivalent to root on the host and exposes
   every container's environment variables.
6. **Leave `ENABLE_API_DOCS=false`.** The interactive docs enumerate every endpoint to anyone
   who can reach the port. Turn them on only in a lab.
7. **Use a read-only FMC account for discovery.** Give the deployment account write access
   only when you are ready to push.

## Reporting an issue

Open a GitHub issue labelled `security`. This is a prototype with no commercial support and
no guaranteed response time.
