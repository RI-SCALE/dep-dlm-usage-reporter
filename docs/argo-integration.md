# ARGO Accounting integration: agreed facts

What GRNET (ARGO Accounting, WP4) and DEP DLM agreed for reporting data
transfer usage. Source: integration meetings and follow-up of 16 and 23
November 2026, and GRNET's "DEP Resource Accounting Info" sheet (tab "ACC -
Final metric definitions"). Design-001 says how this repository implements it.

## Endpoint and authentication

- **Devel API:** `https://api.devel.acc.argo.grnet.gr`
- **Client registration:** with an interactive user token, call
  `POST /accounting-system/clients`, then ask GRNET to approve it and grant
  permissions.
- **Service authentication:** non-interactive client credentials (client ID and
  secret) at the OIDC provider's `/token` endpoint. Recommended for this job.
- **Credentials are per accounting project.** GRNET delivers them out of band;
  the first set is for `RI-SCALE_ENES`.

## Structure

Project (DEP) -> Provider (CERN) -> Installation (Rucio) -> Metric definition

| Item | Value |
| --- | --- |
| Provider | CERN, `6afaf7fa947efcc6dea636e0` |
| Installation | `CERN-Rucio`, `6afaff4e947efcc6dea636e2` (infrastructure "CERN DEP-DLM", resource `data-transfer`) |
| Metric definition | `6afc3e7801adaea4c9c12777`, data transfer size, `aggregated`, unit `#` (bytes) |

## Records

- **Unit:** bytes.
- **Granularity:** daily per calendar date, 00:00:00-23:59:59 UTC.
- **Use cases:** one `group_id` per scientific use case.

| Project | Use cases |
| --- | --- |
| `RI-SCALE_ENES` | `suc1`, `suc2` |
| `RI-SCALE_EISCAT` | `suc3`, `suc4` |
| `RI-SCALE_BBMRI` | `suc5`, `suc6` |
| `RI-SCALE_Euro-BioImaging` | `suc7`, `suc8` |

`group_id` is not settled: GRNET asked to escalate fair sharing and data
ownership (per DEP or per use case) before building on it.

## Milestones

- **10 December 2026:** pipeline validated with mock data for `RI-SCALE_ENES`,
  in time for the TCB Technical Workshop.