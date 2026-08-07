---
title: SDLC
nav_order: 11
---

# Software development lifecycle
{: .no_toc }

How this project is built, tested and released — and the reasoning behind it.
{: .fs-5 .fw-300 }

1. TOC
{:toc}

---

## Principles

**Correct beats complete.** A feature that half works is worse than one that
isn't there, because it teaches people to distrust the tool. Access rules were
export-only for several releases rather than shipping a version that appeared
to deploy them and didn't.

**Fail loudly and early.** Every guard exists because a silent failure wasted
someone's time: rows ignored without explanation, an upgrade that upgraded
nothing, a five-minute health-check timeout that reported "database never
became available" when the real answer was "wrong password".

**Tests are named for behaviour.** `test_edited_row_without_an_action_is_flagged`
tells you what breaks. `test_validate_2` does not.

**No private API.** The web portal calls the same REST endpoints you can call.
If the UI can do it, a script can.

---

## Branching and releases

`main` is always releasable. Work happens on short-lived branches; CI must be
green to merge.

Versioning is semantic:

| Change | Bump | Example |
|---|---|---|
| Bug fix, docs, internal | patch | `0.6.0 → 0.6.1` |
| New capability, backwards compatible | minor | `0.7.0 → 0.8.0` |
| Breaking change | major | reserved for `1.0` |

Cutting a release:

```bash
echo 0.9.0 > VERSION      # and the four other declaration points
git commit -am "Release 0.9.0"
git push origin main
git tag -a v0.9.0 -m "CSAP 0.9.0"
git push origin v0.9.0
```

The tag triggers the release workflow.

{: .important }
> **Never move a published tag.** `v0.3.7` was once created before its fix was
> committed, so its images contained the previous release. The tag was abandoned
> and `0.3.8` cut instead. Retagging would have made one version number mean two
> different builds — far worse than skipping a number.

---

## Testing strategy

Four layers, all running in CI:

### 1. Unit and behaviour tests — `backend/tests`

Over 120 tests, none of which need a firewall. Validation, planning, ordering,
dry-run behaviour, credential encryption, JWT handling, path traversal, workbook
parsing, generated Ansible and Terraform, and the FMC deployment handshake
against a stubbed client.

### 2. Template render tests — `frontend/tests`

Every UI template is **rendered** with realistic API-shaped data, not merely
compiled.

This layer exists because of a specific bug. A template did
`{% raw %}{% for item in page.items %}{% endraw %}` where `page` was a dict from
JSON. Jinja resolves attributes with `getattr()` first, so `page.items` returned
the dict's built-in `.items` **method**, and iterating it raised `TypeError` —
but only at render time. Compilation was clean. It shipped twice.

### 3. Linting

`ruff` with pycodestyle, pyflakes, isort, pyupgrade, bugbear, comprehensions,
simplify and **flake8-bandit** for security patterns.

### 4. Stack smoke test

CI builds all three images, starts the full six-service stack with generated
secrets and a TLS certificate, waits for `/health/ready`, and logs in over
HTTPS. This catches wiring that unit tests never see — and would have caught the
nginx certificate permission bug before it reached a server.

Running them locally:

```bash
docker compose run --rm --entrypoint sh backend -c "pip install -q pytest && pytest -q"
docker compose run --rm --entrypoint sh backend -c "pip install -q ruff  && ruff check app"
```

---

## CI/CD

### On every push and pull request — `ci.yml`

1. Backend lint and tests against a real Postgres service
2. Frontend template render tests
3. Build all three images
4. Full stack smoke test, then tear down

### On a `v*` tag — `release.yml`

1. Build `linux/amd64` and `linux/arm64`
2. Push to GHCR as `csap-backend`, `csap-frontend`, `csap-nginx`
3. Assemble a customer bundle: compose file, `.env.example`, scripts, README
4. Publish a GitHub release with generated notes

Images must be made **public** once in GitHub → Packages, or customers cannot
pull without a token.

---

## Definition of done

A change is not finished until:

- [ ] It does what it claims, with no silent no-ops
- [ ] Failure modes name the cause and the fix
- [ ] Tests are named for the behaviour they protect
- [ ] Lint passes
- [ ] The relevant guide is updated
- [ ] The version is bumped in all five places
- [ ] The commit message explains **why**, not just what

---

## Roadmap

| Version | Scope | State |
|---|---|---|
| 0.1 | Login, discovery, inventory, Excel template | done |
| 0.2 | Upload, validation, HTML reports | done |
| 0.3 | REST deployment, dry run, rollback, drift, audit | done |
| 0.4 | Remediation guidance, findings export | done |
| 0.5 | Stale-export guard, command preview, guided workbook | done |
| 0.6 | Access control rules deployable | done |
| 0.7 | Push to FMC separated from deploy to FTD | done |
| 0.8 | Ansible and Terraform generation | done |
| 0.9 | NAT rules, scheduled discovery and drift | planned |
| 1.0 | RBAC, SSO, multi-user, approval workflow | planned |
| Beyond | Security Cloud Control, ISE, Secure Access, Umbrella, Duo, XDR plugins | planned |

---

## Contributing

The plugin contract is the extension point — adding a Cisco product should
never require changing the core. See
[Plugin development]({{ site.baseurl }}/plugin-development).

If you change validation or deployment behaviour, add a test that fails without
your change. If you fix a bug, name the test after the bug.
