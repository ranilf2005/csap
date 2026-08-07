# CSAP documentation

Cisco Security Automation Platform — plugin-based automation for the Cisco security portfolio.

| Guide | Read this if you want to... |
|---|---|
| [**Quick start**](customer-quickstart.md) | **Install and test it yourself, start to finish** |
| [Installation](installation.md) | Stand the platform up on an Ubuntu server |
| [Testing on Ubuntu](testing-on-ubuntu.md) | Run a full end-to-end test, with or without a real FMC |
| [Web UI guide](user-guide.md) | Learn every screen and the day-to-day workflow |
| [Workbook reference](workbook-reference.md) | Know exactly what to put in each Excel column |
| [Administration](administration.md) | Back up, upgrade, rotate secrets, fix problems |
| [API reference](api-reference.md) | Drive CSAP from scripts or CI |
| [Plugin development](plugin-development.md) | Add ISE, Umbrella, Duo, XDR or another product |

## The workflow in one picture

```
Add system ──► Test connection ──► Discover ──► Snapshot
                                                  │
                          ┌───────────────────────┘
                          ▼
              Download dynamic Excel template
                          │
                   Fill in the actions
                          │
                          ▼
     Upload ──► Validate ──► Change plan ──► Dry run ──► Report
                                                │
                                          Review, then
                                                ▼
                                             Apply ──► Report
                                                │
                                          (Roll back if needed)
                                                ▼
                              Re-discover ──► Drift report
```

Nothing is written to a device until you explicitly choose **Apply** and confirm.
