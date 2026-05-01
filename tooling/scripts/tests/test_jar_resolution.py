"""Unit tests for format_file.py's JAR-resolution helpers.

The pipeline tests in test_format_file_jdt_pipeline.py exercise the
orchestrator end-to-end (subprocess-as-black-box). These tests
exercise the resolution helpers directly to cover branches that
end-to-end tests can't easily reach (cache hits, SHA verification,
download failures).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest import mock

import pytest

import format_file


def test_read_pom_version_returns_project_version() -> None:
    """The pom under tooling/jdt-formatter/ has the project's own
    version as the first <version> element. Subsequent <version>
    tags are dependency versions and must NOT be returned."""
    version = format_file._read_pom_version()
    assert version is not None
    # Sanity: it's a semver-like string, not a property reference
    # like ${jdt.version}.
    assert not version.startswith("${"), version
    assert version.split(".")[0].isdigit(), version


def test_cache_dir_honors_override_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SENZING_STANDARDS_CACHE_DIR", str(tmp_path / "cache"))
    assert format_file._cache_dir() == tmp_path / "cache"


def test_cache_dir_honors_xdg(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SENZING_STANDARDS_CACHE_DIR", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg"))
    expected = tmp_path / "xdg" / "senzing-java-coding-standards"
    assert format_file._cache_dir() == expected


def test_cache_dir_default(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SENZING_STANDARDS_CACHE_DIR", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    expected = tmp_path / ".cache" / "senzing-java-coding-standards"
    assert format_file._cache_dir() == expected


def test_sha256_matches_hashlib(tmp_path) -> None:
    f = tmp_path / "blob"
    payload = b"hello world\n" * 100_000
    f.write_bytes(payload)
    assert format_file._sha256(f) == hashlib.sha256(payload).hexdigest()


def test_resolve_jar_returns_local_build_when_present() -> None:
    """When tooling/jdt-formatter/target/jdt-formatter.jar exists
    (CI builds it; pytest skips orchestrator tests if missing), it's
    the first resolution path — no cache or download attempted."""
    if not format_file._JDT_LOCAL_BUILD.is_file():
        pytest.skip(
            "Local build absent; CI rebuilds it before pytest. "
            "Run `mvn package` in tooling/jdt-formatter/ to populate."
        )
    assert format_file._resolve_jar() == format_file._JDT_LOCAL_BUILD


def test_resolve_jar_uses_cache_when_local_build_absent(
    tmp_path, monkeypatch
) -> None:
    """With no local build, a cache hit at
    `<cache>/jdt-formatter-v<version>.jar` should be returned
    without attempting a download."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setenv("SENZING_STANDARDS_CACHE_DIR", str(cache_dir))
    fake_local = tmp_path / "nonexistent.jar"
    monkeypatch.setattr(format_file, "_JDT_LOCAL_BUILD", fake_local)
    version = format_file._read_pom_version()
    cache_path = cache_dir / f"jdt-formatter-v{version}.jar"
    cache_path.write_bytes(b"cached jar bytes")

    # If we ever reach the download branch, this would fire — but it shouldn't.
    with mock.patch.object(format_file, "_download") as dl:
        result = format_file._resolve_jar()
        dl.assert_not_called()
    assert result == cache_path


def test_resolve_jar_verifies_sha_on_download(
    tmp_path, monkeypatch
) -> None:
    """If a downloaded JAR's hash doesn't match the .sha256 sidecar,
    `_resolve_jar` must reject it and fall through (return None or a
    later-tier resolution result, never the bad cache file)."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("SENZING_STANDARDS_CACHE_DIR", str(cache_dir))
    fake_local = tmp_path / "nonexistent.jar"
    monkeypatch.setattr(format_file, "_JDT_LOCAL_BUILD", fake_local)
    monkeypatch.setattr(format_file, "_build_from_source", lambda: None)

    payload = b"jar contents"

    def fake_download(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".sha256"):
            # Return a hash that does NOT match the JAR.
            dest.write_text(
                "0" * 64 + "  jdt-formatter.jar\n", encoding="utf-8"
            )
        else:
            dest.write_bytes(payload)

    monkeypatch.setattr(format_file, "_download", fake_download)
    result = format_file._resolve_jar()
    assert result is None
    # Bad cache must be cleaned up so subsequent calls don't see it.
    version = format_file._read_pom_version()
    cache_path = cache_dir / f"jdt-formatter-v{version}.jar"
    assert not cache_path.exists()


def test_resolve_jar_accepts_matching_sha(
    tmp_path, monkeypatch
) -> None:
    """The successful download path: SHA matches → cache populated
    and returned."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("SENZING_STANDARDS_CACHE_DIR", str(cache_dir))
    fake_local = tmp_path / "nonexistent.jar"
    monkeypatch.setattr(format_file, "_JDT_LOCAL_BUILD", fake_local)

    payload = b"jar contents that match"
    expected_hash = hashlib.sha256(payload).hexdigest()

    def fake_download(url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url.endswith(".sha256"):
            dest.write_text(
                f"{expected_hash}  jdt-formatter.jar\n", encoding="utf-8"
            )
        else:
            dest.write_bytes(payload)

    monkeypatch.setattr(format_file, "_download", fake_download)
    result = format_file._resolve_jar()
    version = format_file._read_pom_version()
    cache_path = cache_dir / f"jdt-formatter-v{version}.jar"
    assert result == cache_path
    assert cache_path.read_bytes() == payload
