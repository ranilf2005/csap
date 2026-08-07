---
title: Workbook reference
nav_order: 5
---

# Workbook reference

CSAP generates the workbook dynamically from what discovery actually found, so your file will
only contain sheets relevant to that device. Every sheet shares the same rules.

## Universal rules

| Rule | Detail |
|---|---|
| `action` column | `create`, `update` or `delete`. **Blank rows are ignored** — leave `action` empty to skip a row. |
| `name` column | Always required when `action` is set. Matching is case-insensitive. |
| Duplicates | Two rows with the same name in the same sheet is an error. |
| `create` | Fails validation if an object with that name already exists on the device. |
| `update` / `delete` | Fails validation if the object does **not** exist on the device. |
| Column order | Irrelevant. CSAP matches by header name, so you can reorder or hide columns. |
| Extra sheets | Ignored. The `README` sheet is always skipped. |
| Row limit | 20,000 rows per sheet. |
| File size | 25 MB, `.xlsx` or `.xlsm`. |

Row numbers in validation messages refer to the **Excel row number**, so row 2 is the first data row.

---

## Hosts

A single IP address.

| Column | Required | Example | Rules |
|---|---|---|---|
| `action` | yes | `create` | |
| `name` | yes | `WEB01` | |
| `value` | yes (not for delete) | `10.1.1.20` | Must be a valid IPv4 or IPv6 address. No prefix. |
| `description` | no | `Primary web server` | |

## Networks

A subnet.

| Column | Required | Example | Rules |
|---|---|---|---|
| `action` | yes | `create` | |
| `name` | yes | `DMZ-NET` | |
| `value` | yes (not for delete) | `10.2.0.0/24` | **A prefix length is required.** `10.2.0.0` alone is an error. |
| `description` | no | | Host bits set (e.g. `10.2.0.5/24`) produces a warning, not an error. |

## Ranges

A contiguous address range.

| Column | Required | Example | Rules |
|---|---|---|---|
| `action` | yes | `create` | |
| `name` | yes | `DHCP-POOL` | |
| `value` | yes (not for delete) | `10.1.1.10-10.1.1.50` | Format `start-end`. Both must be valid IPs and end must not precede start. |
| `description` | no | | |

## Ports

A TCP or UDP service.

| Column | Required | Example | Rules |
|---|---|---|---|
| `action` | yes | `create` | |
| `name` | yes | `HTTP-ALT` | |
| `protocol` | yes | `TCP` | `TCP` or `UDP` only. Case-insensitive. |
| `port` | yes | `8080` or `8080-8090` | 1–65535. For a range, start must not exceed end. |
| `description` | no | | |

## NetworkGroups

A group of hosts, networks, ranges or other groups.

| Column | Required | Example | Rules |
|---|---|---|---|
| `action` | yes | `create` | |
| `name` | yes | `WEB-TIER` | |
| `members` | yes (not for delete) | `WEB01, WEB02, DMZ-NET` | Comma or semicolon separated. |
| `description` | no | | |

Each member must either already exist on the device **or** be created by a `create` row
elsewhere in the same workbook. CSAP orders the deployment so members are created before the group.

## AccessRules

Present in the template for planning purposes. Validation and deployment of access rules
are not implemented yet — rows in this sheet are read but produce no operations.

---

## Deletion behaviour

- Deleting an object that is still a member of a network group produces a **warning**, not an error.
  The FMC will reject the delete if the reference is still live, so remove it from the group first.
- Deletes are executed in reverse order of the apply list, so groups are removed before their members.

## Worked example

`Hosts`

| action | name | value | description |
|---|---|---|---|
| create | APP01 | 10.1.1.30 | App server 1 |
| create | APP02 | 10.1.1.31 | App server 2 |
| | OLD-HOST | | *(blank action — ignored)* |
| delete | RETIRED-01 | | |

`NetworkGroups`

| action | name | members | description |
|---|---|---|---|
| create | APP-TIER | APP01, APP02 | Application tier |
| update | WEB-TIER | WEB01, WEB02, WEB03 | Added WEB03 |

This produces five operations: three creates (APP01, APP02, then APP-TIER),
one update (WEB-TIER) and one delete (RETIRED-01).

`update` replaces the whole object, so list **every** member you want the group to end up with,
not just the new ones.
