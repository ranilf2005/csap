---
title: Installation
nav_order: 3
---

# Installation

## Requirements

| | Minimum | Recommended |
|---|---|---|
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| vCPU | 2 | 4 |
| RAM | 4 GB | 8 GB |
| Disk | 40 GB | 100 GB SSD |
| Software | Docker Engine 24+, Docker Compose v2, openssl, python3, curl | |

Outbound HTTPS access to `ghcr.io` (to pull images) and to your FMC management address.
Inbound 443 from your administrators.

## Install Docker

> **Run the whole block in order.** `docker-ce` and `docker-compose-plugin` live in Docker's own
> APT repository, not Ubuntu's. Jumping straight to the install line fails with
> `Package 'docker-ce' has no installation candidate`.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg git make openssl python3

# Docker's GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo tee /etc/apt/keyrings/docker.asc > /dev/null
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Docker's repository
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Only now do the packages exist
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
```

Verify before continuing:

```bash
docker --version
docker compose version   # must be v2.x -- CSAP does not work with docker-compose v1
docker run --rm hello-world
```

## Install CSAP

```bash
git clone https://github.com/ranilf2005/csap.git
cd csap
./scripts/install.sh --hostname csap.example.com
```

The installer:
1. Checks Docker, Compose and openssl are present
2. Generates `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, database and Redis passwords, and an admin password into `.env` (mode `0600`)
3. Creates a self-signed TLS certificate for the hostname you passed
4. Pulls the published images (falls back to a local build)
5. Starts the stack and waits for health
6. Prints the URL, admin address and admin password

Save the admin password. Then browse to `https://csap.example.com` and sign in.

### Build from source instead of pulling

```bash
./scripts/install.sh --build
```

Use this if the GHCR packages are private, or you have local modifications.

## Use a real TLS certificate

```bash
sudo cp fullchain.pem nginx/certs/csap.crt
sudo cp privkey.pem  nginx/certs/csap.key

# nginx runs as uid 101 inside the container and must own the key to read it
docker run --rm -v "$PWD/nginx/certs:/certs" alpine:3.20 chown -R 101:101 /certs

docker compose restart nginx
```

If you skip the `chown`, nginx cannot read the key and the container enters a restart loop.
Check with `docker compose logs nginx`.

## Firewall

```bash
sudo ufw allow 443/tcp
sudo ufw allow 80/tcp     # only redirects to 443
sudo ufw enable
```

## Verify

```bash
docker compose ps                                   # all services up, healthy
curl -k https://localhost/api/v1/health/ready        # {"status":"ready", ...}
docker compose logs -f backend
```

## Changing ports

If 80/443 are already in use, edit `.env`:

```
HTTP_PORT=8080
HTTPS_PORT=8443
PUBLIC_URL=https://csap.example.com:8443
```

Then `docker compose up -d`.

## Uninstall

```bash
./scripts/uninstall.sh           # stop, keep all data
./scripts/uninstall.sh --purge   # stop and delete the database and artifacts (takes a backup first)
```
