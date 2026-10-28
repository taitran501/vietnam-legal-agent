# Git history secret scan

**Date:** 2026-10-28
**Scanner:** Gitleaks 8.30.1 (Windows release; SHA-256 checksum verified)
**History boundary:** 216 commits reachable from the refs present at scan time, starting from `b5d56d0555ba77b796e8e947220f41296d9089dc`.

| Scope | Command scope | Findings |
| --- | --- | ---: |
| Reachable Git history | `git --all --full-history` | 0 |
| Staged change set at scan time | `git --staged` | 0 |

The scanner ran with full redaction. No credential material was recorded in this report. This is a tool-detection result for the listed history and staged change set, not a guarantee that every possible secret format is detectable.
