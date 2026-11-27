# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| `0.3.x` | Yes |
| `< 0.3.0` | No |

## Reporting a Vulnerability

Please **do not** open a public GitHub issue for security vulnerabilities.
Instead, use GitHub's [Private Vulnerability Reporting](https://github.com/aebayav/platypus-server/security/advisories/new) on the repository so we can coordinate a fix and release before disclosure.

## Operational Security Notes

- **Dashboard credentials**: Always set `DASHBOARD_USER` and `DASHBOARD_PASSWORD_HASH` (or `DASHBOARD_PASSWORD`) plus `DASHBOARD_SECRET_KEY` in production. Never expose port `5050` directly to the public internet without TLS (use Caddy or Tailscale).
- **SSH hardening**: Before running `platypus setup` or `bootstrap.sh` on a remote VPS, verify your SSH public key is present in `~/.ssh/authorized_keys`, as password and root SSH logins are disabled.
