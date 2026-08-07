# Web UI guide

Every screen in CSAP, in the order you will use them.

---

## 1. Signing in

Open `https://<server>` and sign in with the address and password printed by `install.sh`
(also stored in `.env`).

On first login a banner reminds you that the installation password is still in use.
Click **Change password**, or use the user menu at the top right → **Change password**.
Passwords must be at least 12 characters.

Sessions last 60 minutes. If a page bounces you back to the sign-in screen, your token expired.

---

## 2. Dashboard

The landing page after sign-in.

**Top cards**
| Card | Meaning |
|---|---|
| Managed systems | How many devices are registered |
| Connected | How many last reported a successful connection test |
| Snapshots | Total discovery snapshots stored |
| Objects captured | Sum of all objects across snapshots |

**Managed systems** — name, product, host, live status, and a **Discover** button per system.

**Recent snapshots** — click a snapshot label to browse its inventory, or use
**Template** to download the Excel workbook and **Report** to generate a shareable HTML inventory report.

**Recent jobs** — the last ten discovery, dry-run, deployment and rollback jobs with live progress bars.
Click a job ID to open its detail page.

---

## 3. Systems

Register and manage the devices CSAP talks to.

### Adding a system

| Field | Notes |
|---|---|
| Display name | Free text, must be unique. Used throughout the UI and in reports. |
| Product | Which plugin handles this device. Today: Cisco Secure Firewall (FMC). |
| Hostname / IP | The FMC management address. |
| Port | 443 unless your FMC uses a custom port. |
| Username / Password | An FMC account with REST API access. Encrypted at rest; never returned by the API. |
| Verify TLS certificate | Leave **on** in production. Turn off only for lab FMCs with self-signed certificates. |

Give the account the least privilege that still works. Read-only is enough for discovery;
you only need write permission when you intend to apply changes.

### Actions on each system

- **Test** — authenticates and reads the FMC version. The result appears inline; the status badge and detected version update.
- **Discover** — queues a discovery job and takes you to its progress page.
- **Delete** — removes the system *and all of its snapshots, changes and reports*. You are asked to confirm.

---

## 4. Discovery and jobs

Discovery runs in the background worker so large FMCs do not block the UI.

The job page polls every three seconds and shows a progress bar and the current step
("reading networkgroups", "reading access control policies", ...).

On success you get:
- **View inventory** — browse everything that was found
- **Download Excel template** — the workbook generated for this exact snapshot
- A per-entity count table (hosts, networks, groups, ports, devices, policies, rules, NAT)

If it fails, the red banner shows the reason — usually bad credentials, an unreachable host,
or a TLS certificate that cannot be verified.

Discovery is throttled to respect the FMC limit of roughly 120 requests per minute,
so a large deployment can take several minutes. That is expected.

---

## 5. Inventory

Reached by clicking a snapshot.

- Filter by **entity type** using the dropdown (only types present in this snapshot are listed).
- Search by **name** (case-insensitive, partial match).
- Page through results 100 at a time.
- **Excel template** downloads the change workbook for this snapshot.

A snapshot is immutable. Every discovery creates a new one, which is what makes drift detection possible.

---

## 6. Changes

This is where configuration actually gets made.

### Uploading

1. Pick the **target system**. Systems without a snapshot are disabled — discover first.
2. Choose your filled-in `.xlsx` (max 25 MB).
3. Click **Upload and validate**.

Validation runs immediately against the most recent snapshot, so you get results in seconds
without touching the FMC.

### Change status

| Status | Meaning |
|---|---|
| `invalid` | Errors found. Deployment is blocked. |
| `planned` | Valid, and a change plan was built. Ready to deploy. |
| `deploying` | A deployment is in flight. |
| `deployed` | Applied successfully. |
| `failed` | One or more operations failed. |
| `rolled_back` | A previous deployment was reverted. |

### The change detail page

**Counters** — errors, warnings, planned changes, applied operations.

**Validation findings** — one row per issue with severity, sheet, row number, field and message.
Errors block deployment; warnings do not.

**Change plan** — exactly what CSAP intends to do, colour-coded: green create, blue update, red delete.
Creates are ordered so plain objects land before the groups that reference them; deletes run in reverse.

**Deploy panel** (only shown when there are no errors)
- **Dry run** — contacts nothing, produces a report of every operation that *would* run. Always do this first.
- **Apply** — writes to the device. You must confirm a dialog naming the system and the operation count.

**Roll back** — appears after a successful apply. Reverts every applied operation in reverse order:
created objects are deleted, updated objects are restored to their previous values, deleted objects are recreated.

**Re-validate** — re-runs validation against the newest snapshot. Use this after someone else
changed the device, or after a fresh discovery.

---

## 7. Drift

Compare any two snapshots of the same system.

1. Pick a **baseline** (older) and a **current** (newer) snapshot.
2. Click **Compare**.

The report opens automatically and shows objects **added**, **removed** and **modified**,
with the exact fields that changed and their before/after values.

Volatile FMC bookkeeping fields (`metadata`, `links`, `version`, `timestamp`, `lastUser`)
are ignored so they do not show up as false drift.

Typical use: snapshot before a change window, snapshot after, and prove exactly what moved.

---

## 8. Reports

Every report CSAP has generated, filterable by type.

| Type | Produced by |
|---|---|
| `inventory` | The **Report** button on a snapshot |
| `validation` | Every workbook upload or re-validation |
| `dry_run` | A dry-run deployment |
| `deployment` | An applied deployment |
| `drift` | A snapshot comparison |

Reports are **self-contained HTML** — no external stylesheets or scripts — so you can email them,
archive them, or open them on an air-gapped machine. **View** opens in a new tab; **Download** saves the file.
They print cleanly to PDF from the browser.

---

## 9. Audit

An append-only record of who did what.

Columns: timestamp, user, action, target, outcome, source IP.
Filter by user, page 100 events at a time.

Logged actions include `auth.login` (success *and* failure), `auth.change_password`,
`connection.create/update/delete/test`, `discovery.start`, `change.upload/revalidate/dry_run/deploy/rollback/delete`,
`report.delete` and `drift.compare`.

---

## Tips

- **Always dry run first.** It costs nothing and produces the same report format as a real deployment.
- **Re-discover after deploying** so your baseline reflects reality, then run a drift report to confirm only the intended changes landed.
- **Snapshots are cheap; keep them.** They are the only way to detect drift and the only baseline validation can use.
- **Leave TLS verification on** except in a lab.
- **One change window per workbook.** Small, reviewable workbooks are far easier to roll back than one large one.
