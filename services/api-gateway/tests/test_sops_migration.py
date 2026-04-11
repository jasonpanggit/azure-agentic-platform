"""Tests for the `sops` PostgreSQL migration (Phase 30)."""
from __future__ import annotations

import pytest


class TestSopsMigration:
    """Validate the sops table DDL and indexes."""

    def test_migration_file_exists(self):
        import os

        path = "services/api-gateway/migrations/003_create_sops_table.py"
        assert os.path.exists(path), f"Migration file not found: {path}"

    def test_migration_creates_sops_table(self):
        """Migration SQL must include CREATE TABLE sops."""
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "CREATE TABLE" in content and "sops" in content

    def test_migration_includes_content_hash_column(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "content_hash" in content

    def test_migration_includes_scenario_tags_array(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "scenario_tags" in content
        assert "TEXT[]" in content or "text[]" in content

    def test_migration_includes_domain_index(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "CREATE INDEX" in content
        assert "domain" in content

    def test_migration_includes_foundry_filename_column(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "foundry_filename" in content

    def test_migration_has_up_and_down_functions(self):
        with open("services/api-gateway/migrations/003_create_sops_table.py") as f:
            content = f.read()
        assert "async def up(" in content
        assert "async def down(" in content
