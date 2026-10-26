# Security policy

This is a public repository for a personal research tool maintained by one person. There are no releases, hosted deployments or users other than the maintainer. The repository contains code and documentation only; collected data never leaves the maintainer's machine ([ADR 0005](docs/engineering/decisions/0005-public-repository.md)).

## Reporting

Report vulnerabilities privately through the GitHub **Security** tab → **Report a vulnerability**. Do not open a public issue for a vulnerability. Use synthetic data in the report; do not attach a database, collected data or credentials.

## Scope

- The CLI collectors: handling of downloaded HTML, PDFs, RSS and bulk files (parsing untrusted input, paths, archive handling).
- The local dashboard: it must listen on localhost only and must not expose collected data on the network.
- The Docker setup: the dashboard port is published on the host loopback only.
- The repository's CI workflow, hooks and dependency setup.

Out of scope: wrong or outdated market data that matches the source, and vulnerabilities in the third-party sources themselves.
