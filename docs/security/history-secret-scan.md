# Git history secret scan

**Date:** 2026-10-28
**Scanner:** Gitleaks 8.30.1 (Windows release; SHA-256 checksum verified)
**History boundary:** 216 commits reachable from the refs present at scan time, starting from `b5d56d0555ba77b796e8e947220f41296d9089dc`.

| Scope | Command scope | Findings |
| --- | --- | ---: |
| Reachable Git history | `git --all --full-history` | 0 |
| Staged change set at scan time | `git --staged` | 0 |

The scanner ran with full redaction. No credential material was recorded in this report. This is a tool-detection result for the listed history and staged change set, not a guarantee that every possible secret format is detectable.

## Agent-ready branch follow-up

**Date:** 2026-10-28  
**Head:** `2ddb823e16b6f661f825dc0a1a378a4c0d2741d5`  
**Scanner:** Gitleaks 8.30.1; official Windows release asset SHA-256: `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.  
**History boundary:** 224 commits reachable from the local refs (`--all`) at the scan head.

| Scope | Command scope | Findings |
| --- | --- | ---: |
| Reachable Git history | `gitleaks git --redact=100 --log-opts=--all` | 0 |

The follow-up scan used full redaction. Only the finding count and scan metadata were retained.

## Agent-ready final head follow-up

- Date: 2026-10-28
- Head: `0fd66c752254687e1994dd799ebc13f5fdb5d862`
- Scanner: Gitleaks 8.30.1; official Windows x64 release archive SHA-256: `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.
- History boundary: 227 commits reachable from the local refs (`--all`) at the scan head.

| Scope | Command scope | Findings |
| --- | --- | ---: |
| Reachable Git history | `gitleaks git --redact=100 --log-opts=--all --report-format=json --report-path=<outside repository>` | 0 |

The scan ran at the final agent-ready code head with full redaction. The output and JSON report were kept outside the repository; only the finding count, history boundary, scanner version, checksum, and scanned head are recorded here.

## Full remote-ref audit

- Date: 2026-10-28
- Head at scan time: `1d5a7218ab67740f40e8b88edd3ac607a52dc6bc`
- Scanner: Gitleaks 8.30.1; official Windows x64 release archive SHA-256: `d29144deff3a68aa93ced33dddf84b7fdc26070add4aa0f4513094c8332afc4e`.
- Ref scope: all local refs after fetching the remote branches `main`, `chore/agent-ready-repo`, `fix/backend-runtime-contracts`, and `fix/browser-auth-regressions`.
- History boundary: 228 reachable commits.

| Scope | Command scope | Findings |
| --- | --- | ---: |
| Reachable Git history across fetched refs | `gitleaks git --redact=100 --log-opts=--all --report-format=json --report-path=<outside repository>` | 0 |

After the scan, the two old `fix/*` refs were removed from GitHub after confirming that neither had an associated pull request and that their changes were obsolete or superseded in `main`. Their commit SHAs remain available in local backup branches. The current GitHub remote has only `main` and `chore/agent-ready-repo`.
