---
title: Home
layout: home
nav_order: 1
---

# Cisco Security Automation Platform
{: .no_toc }

Discover what your firewall is running, describe the change you want in a
spreadsheet, prove it is safe, then apply it — with a full record of who
changed what.
{: .fs-6 .fw-300 }

[Get started]({{ site.baseurl }}/customer-quickstart){: .btn .btn-primary .mr-2 }
[View on GitHub](https://github.com/ranilf2005/csap){: .btn }

---

{: .warning }
> **Prototype software — use at your own risk.**
>
> This is an unfinished prototype published for evaluation only. It is not a
> product, it is not supported, and it carries no warranty. It is **not
> affiliated with, endorsed by or supported by Cisco Systems, Inc.**
>
> **It makes changes to live network security devices.** A mistake can remove
> firewall rules or break connectivity. You are solely responsible for what you
> run it against, for taking backups, for reviewing every change, and for the
> outcome. Test against a laboratory device with a read-only account first.

## The problem

Firewall change management in most organisations looks like this: someone
emails a spreadsheet of requested rules, an engineer types them into the FMC by
hand, nobody is quite sure what the firewall looked like beforehand, and the
audit trail is a ticket number.

That is slow, it does not scale, and the mistakes it produces are the expensive
kind — a wrong subnet, a rule that shadows another, an object deleted while
still in use.

## What this does about it

| Problem | How CSAP addresses it |
|---|---|
| Nobody knows the current state | Every run captures an immutable **snapshot** of the device |
| Changes are typed by hand | You edit an **Excel export of the real configuration** |
| Mistakes are found by the device | **Validation** runs first, against that snapshot, and explains how to fix each finding |
| No idea what will happen | **Dry run** shows every API call without sending one |
| Changes are irreversible | **Rollback** reverts an applied change in reverse order |
| Someone changed it out-of-band | **Drift detection** compares any two snapshots |
| No audit trail | Every action is logged with user, outcome and source IP |

## The workflow

```
Connect ─► Discover ─► Snapshot
                          │
                          ▼
              Download current config (Excel)
                          │
                  Set the action column
                          │
                          ▼
    Upload ─► Validate ─► Change plan ─► Dry run ─► Report
                                            │
                                       Review, then
                                            ▼
                            Push to FMC ─► Deploy to FTD
                                            │
                                     (Roll back if needed)
                                            ▼
                          Re-discover ─► Drift report
```

**Nothing reaches a device until you explicitly choose to push, and confirm.**

## Built to grow beyond firewalls

Cisco Secure Firewall is the first product, not the only one. The core —
authentication, jobs, snapshots, the Excel engine, validation, reporting,
drift, audit — knows nothing about firewalls. Adding Cisco ISE, Umbrella, Duo,
XDR or Secure Access means writing one plugin, not changing the platform.

See [Plugin development]({{ site.baseurl }}/plugin-development).

## Where to go next

| I want to... | Read |
|---|---|
| Install it and try it end to end | [Quick start]({{ site.baseurl }}/customer-quickstart) |
| Understand every screen | [Web portal guide]({{ site.baseurl }}/user-guide) |
| Know what to type in the spreadsheet | [Workbook reference]({{ site.baseurl }}/workbook-reference) |
| Look up a command | [Command reference]({{ site.baseurl }}/commands) |
| Understand how it is built | [Architecture]({{ site.baseurl }}/architecture) |
| Find my way around the code | [Project structure]({{ site.baseurl }}/project-structure) |
| Drive it from a script | [API reference]({{ site.baseurl }}/api-reference) |
| Add another Cisco product | [Plugin development]({{ site.baseurl }}/plugin-development) |
| Know how it is developed and released | [SDLC]({{ site.baseurl }}/sdlc) |

## Current status

| Capability | State |
|---|---|
| Discovery, snapshots, inventory | Working |
| Dynamic Excel export and blank template | Working |
| Validation with remediation guidance | Working |
| Dry run, push to FMC, deploy to FTD, rollback | Working |
| Network objects, groups, ports, ranges | Deployable |
| Access control rules | Deployable |
| NAT rules | Discovery and export only |
| Ansible and Terraform | Generated for your pipeline, not executed |
| Multi-user, RBAC, SSO, approvals | Not yet — single administrator account |
