# SOP Authoring Guide

All SOP files must follow `sop-template.md`. Key rules:

1. Front matter is required — `title`, `domain`, `version` are mandatory fields.
2. Step types must use exact labels: `[DIAGNOSTIC]`, `[NOTIFY]`, `[DECISION]`,
   `[REMEDIATION:LOW]`, `[REMEDIATION:MEDIUM]`, `[REMEDIATION:HIGH]`,
   `[REMEDIATION:CRITICAL]`, `[ESCALATE]`.
3. Every file with `is_generic: false` must have at least one entry in `resource_types`.
4. Generic SOPs must set `is_generic: true` and use filename pattern `{domain}-generic.md`.
5. After authoring, run `python scripts/lint_sops.py` to validate.
6. Then run `python scripts/upload_sops.py` to upload to Foundry.
