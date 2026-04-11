"""Tests for scripts/upload_sops.py — idempotent SOP upload."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


class TestComputeSopHash:
    """Verify SHA-256 content hash computation."""

    def test_returns_sha256_hex_string(self, tmp_path):
        sop_file = tmp_path / "test.md"
        content = b"# Test SOP\nThis is a test."
        sop_file.write_bytes(content)

        from scripts.upload_sops import compute_sop_hash

        result = compute_sop_hash(sop_file)
        expected = hashlib.sha256(content).hexdigest()
        assert result == expected

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "sop1.md"
        f2 = tmp_path / "sop2.md"
        f1.write_text("version 1")
        f2.write_text("version 2")

        from scripts.upload_sops import compute_sop_hash

        assert compute_sop_hash(f1) != compute_sop_hash(f2)

    def test_same_content_same_hash(self, tmp_path):
        f1 = tmp_path / "sop1.md"
        f2 = tmp_path / "sop2_copy.md"
        f1.write_text("same content")
        f2.write_text("same content")

        from scripts.upload_sops import compute_sop_hash

        assert compute_sop_hash(f1) == compute_sop_hash(f2)

    def test_hash_is_64_chars_hex(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("hello")

        from scripts.upload_sops import compute_sop_hash

        result = compute_sop_hash(sop_file)
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


class TestParseSopFrontMatter:
    """Verify YAML front matter parsing."""

    def test_extracts_title(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text(
            "---\ntitle: VM High CPU\ndomain: compute\nversion: '1.0'\n---\n# Body"
        )

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["title"] == "VM High CPU"

    def test_extracts_domain(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("---\ntitle: Test\ndomain: patch\nversion: '1.0'\n---\n")

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["domain"] == "patch"

    def test_extracts_version(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("---\ntitle: Test\ndomain: compute\nversion: '2.1'\n---\n")

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["version"] == "2.1"

    def test_extracts_scenario_tags(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text(
            "---\ntitle: Test\ndomain: compute\nversion: '1.0'\n"
            "scenario_tags:\n  - cpu\n  - high\n---\n"
        )

        from scripts.upload_sops import parse_sop_front_matter

        result = parse_sop_front_matter(sop_file)
        assert result["scenario_tags"] == ["cpu", "high"]

    def test_missing_front_matter_raises(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("# No front matter here")

        from scripts.upload_sops import parse_sop_front_matter

        with pytest.raises(ValueError, match="front matter"):
            parse_sop_front_matter(sop_file)

    def test_missing_required_field_raises(self, tmp_path):
        sop_file = tmp_path / "test.md"
        sop_file.write_text("---\ntitle: Test\n---\n# Missing domain and version")

        from scripts.upload_sops import parse_sop_front_matter

        with pytest.raises(ValueError, match="missing required"):
            parse_sop_front_matter(sop_file)
