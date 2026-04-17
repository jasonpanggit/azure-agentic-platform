# tests

Top-level Python test suite covering unit and integration tests for platform services, agents, and shared utilities. Approximately 1,155 tests total across all services.

## Contents

- `eval/` — agent evaluation tests using sample traces to validate reasoning quality
- `test_alert_rule_audit.py` — tests for alert rule audit service
- `test_backup_compliance.py` — tests for backup compliance checks
- `test_capacity_endpoints.py` — tests for capacity planning API endpoints
- `test_capacity_planner.py` — tests for capacity planner business logic
- `test_identity_risk_service.py` — tests for identity risk detection service
- `test_maintenance_service.py` — tests for maintenance window service
- `test_private_endpoint_service.py` — tests for private endpoint validation
- `test_vm_extension_service.py` — tests for VM extension management service

Run with: `pytest tests/ -v` from the repo root (requires `pythonpath=["."]` in `pyproject.toml`).
