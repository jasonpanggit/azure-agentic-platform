# scripts/simulate-incidents

Fires synthetic incident payloads against the API gateway to exercise the full agent pipeline end-to-end without requiring real Azure alerts.

## Contents

| File | Description |
|------|-------------|
| `scenario_compute.py` | VM CPU spike, OOM, disk full, unresponsive VM scenarios |
| `scenario_network.py` | NSG block, VNet peering failure, ExpressRoute degradation |
| `scenario_storage.py` | Storage throttling, replication lag, access denied |
| `scenario_security.py` | Defender alert, unusual RBAC change, Key Vault access |
| `scenario_arc.py` | Arc server heartbeat loss, extension failure |
| `scenario_sre.py` | SLO breach, cross-domain availability incident |
| `scenario_cross.py` | Multi-domain correlated incident (compute + network) |
| `common.py` | Shared HTTP client, payload builders, result logging |
| `run-all.sh` | Runs all scenarios sequentially and logs results |
| `simulation-results.log` | Output log from the last full simulation run |
| `requirements.txt` | Python dependencies |
