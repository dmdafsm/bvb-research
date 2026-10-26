# Security policy

This is a private repository for a personal research tool maintained by one person. There are no releases, hosted deployments or users other than the maintainer.

## Reporting

If you have access to the repository and find a vulnerability, report it privately to the maintainer (GitHub **Security** tab → **Report a vulnerability**, or directly). Do not open a public issue. Use synthetic data in the report; do not attach the database, collected data or credentials.

## Scope

- The CLI collectors: handling of downloaded HTML, PDFs, RSS and bulk files (parsing untrusted input, paths, archive handling).
- The local dashboard: it must listen on localhost only and must not expose collected data on the network.
- The repository's CI workflow, hooks and dependency setup.

Out of scope: wrong or outdated market data that matches the source, and vulnerabilities in the third-party sources themselves.
