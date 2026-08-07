# CSAP documentation

The full documentation site, with navigation and search, is published at
**<https://ranilf2005.github.io/csap/>**

These files are its source. Reading them here on GitHub works too.

| Guide | Read this if you want to... |
|---|---|
| [**Quick start**](customer-quickstart.md) | **Install and test it yourself, start to finish** |
| [Installation](installation.md) | Stand the platform up on an Ubuntu server |
| [Web portal guide](user-guide.md) | Learn every screen and the day-to-day workflow |
| [Workbook reference](workbook-reference.md) | Know exactly what to put in each Excel column |
| [Command reference](commands.md) | Look up any command, status check or troubleshooting step |
| [Architecture](architecture.md) | Understand the data model, caching and security |
| [Project structure](project-structure.md) | Find your way around the code |
| [API reference](api-reference.md) | Drive CSAP from scripts or CI |
| [Plugin development](plugin-development.md) | Add ISE, Umbrella, Duo, XDR or another product |
| [SDLC](sdlc.md) | See how this is built, tested and released |
| [Administration](administration.md) | Back up, upgrade, rotate secrets, fix problems |
| [Test plan](testing-on-ubuntu.md) | Run a full end-to-end test, with or without a real FMC |

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
