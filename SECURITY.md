# Security policy

Athena runs with high privileges: root on Linux, and it can control containers, install packages and open a shell. Security reports are taken seriously.

## Reporting a vulnerability

**Please don't open public issues for security problems.**

Report privately through GitHub: [**Report a vulnerability**](https://github.com/Promethean-Works/athena/security/advisories/new). Include:

- the affected version or commit, and the OS;
- steps to reproduce, or a proof of concept;
- the impact as you understand it.

You'll get an acknowledgement within 7 days. A fix and an advisory will be coordinated with you before anything is published. Credit is given unless you prefer otherwise.

## Supported versions

Athena is pre-1.0. Only the latest release gets security fixes.

## Scope

In scope: the Athena server and web UI, the install scripts, and the default configuration.

Out of scope: vulnerabilities in third-party apps installed from app catalogs, and in upstream dependencies (report those upstream; tell us too if Athena's use of them makes things worse).

## Known-vulnerability monitoring

Dependabot opens weekly update PRs. A weekly workflow (`.github/workflows/cve-scan.yml`, also `scripts/cve-scan.sh` locally) runs `pnpm audit`, `pip-audit` and Trivy over every store-app image, and records HIGH/CRITICAL findings that have a fix in one open "Weekly CVE scan" issue. It never blocks a PR.
