# Security

- This repository contains no credentials. The database connection string is
  supplied to workflows as the GitHub Actions secret `MONGO_URI` and is never
  printed.
- Workflows run with read-only repository permissions. The one job that
  commits a run report receives no secrets.
- Pull requests from forks cannot access secrets.

To report a problem, open a private security advisory on this repository.
