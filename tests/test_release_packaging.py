from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest

import deploy


REPO = Path(__file__).resolve().parents[1]


def _load_pe_verifier():
    path = REPO / "scripts" / "verify_pe_arch.py"
    spec = importlib.util.spec_from_file_location("verify_pe_arch", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_pe(machine: int) -> bytes:
    pe_offset = 0x80
    data = bytearray(pe_offset + 6)
    data[:2] = b"MZ"
    data[0x3C:0x40] = struct.pack("<I", pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    data[pe_offset + 4 : pe_offset + 6] = struct.pack("<H", machine)
    return bytes(data)


@pytest.mark.parametrize("arch,machine", [("x86_64", 0x8664), ("arm64", 0xAA64)])
def test_pe_arch_verifier_accepts_expected_machine(tmp_path: Path, arch: str, machine: int):
    verifier = _load_pe_verifier()
    executable = tmp_path / "djcat.exe"
    executable.write_bytes(_fake_pe(machine))

    verifier.verify_pe_arch(executable, arch)


def test_pe_arch_verifier_rejects_mislabeled_build(tmp_path: Path):
    verifier = _load_pe_verifier()
    executable = tmp_path / "djcat.exe"
    executable.write_bytes(_fake_pe(0x8664))

    with pytest.raises(ValueError, match="expected arm64"):
        verifier.verify_pe_arch(executable, "arm64")


def test_installer_is_single_language_and_architecture_aware():
    script = (REPO / "scripts" / "DJCat-Pro-5.iss").read_text(encoding="utf-8")

    assert 'Name: "chinesesimplified"' in script
    assert 'MessagesFile: "scripts\\ChineseSimplified.isl"' in script
    assert 'Name: "english"' not in script
    assert 'Name: "chinesetraditional"' not in script
    assert "ArchitecturesAllowed={#MyAppArch}" in script
    assert "Windows-{#MyAppArchName}-Setup" in script
    assert "DefaultDirName={autopf}\\DJCat Pro" in script
    assert "DefaultDirName={autopf}\\DJCat Pro 5" not in script


def test_release_workflow_builds_only_x86_64_packages():
    workflow = (REPO / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    assert "runs-on: windows-2022" in workflow
    assert "architecture: x64" in workflow
    assert "windows-11-arm" not in workflow
    assert "arm64" not in workflow
    assert "verify_pe_arch.py" in workflow
    assert "Windows-x86_64.zip" in workflow
    assert "Windows-x86_64-Setup.exe" in workflow
    assert "gh release create" in workflow
    assert 'release_args=()' in workflow
    assert 'if [[ "$TAG" == *-* ]]; then' in workflow
    assert "--prerelease" in workflow
    assert "cancel-in-progress: false" in workflow
    assert '-OutFile "scripts\\ChineseSimplified.isl"' in workflow
    assert 'find release-assets -type f -name "$file"' in workflow
    assert 'cp "${matches[0]}" "release-files/$file"' in workflow
    assert 'gh release create "$TAG" release-files/*' in workflow


def test_python_requirement_accepts_release_runner_patch_version():
    metadata = (REPO / "pyproject.toml").read_text(encoding="utf-8")

    assert 'requires-python = ">=3.12.8,<3.13"' in metadata
    assert "PYTHON_VERSION: 3.12.10" in (
        REPO / ".github" / "workflows" / "main.yml"
    ).read_text(encoding="utf-8")


def test_pre_release_number_is_preserved_in_windows_file_version(monkeypatch):
    monkeypatch.setattr(deploy, "VERSION", "5.0.0-pre.22")

    args = deploy.build_args()

    assert "--file-version=5.0.0.22" in args
    assert "--product-version=5.0.0.22" in args


def test_windows_build_includes_ico_normalizer():
    assert "--include-package=PIL" in deploy.build_args()


def test_release_uses_the_committed_lock_for_tests_and_builds():
    workflow = (REPO / ".github" / "workflows" / "main.yml").read_text(
        encoding="utf-8"
    )
    metadata = (REPO / "pyproject.toml").read_text(encoding="utf-8")

    assert (REPO / "uv.lock").is_file()
    assert "uv.lock" not in (REPO / ".gitignore").read_text(encoding="utf-8")
    assert workflow.count("uv sync --frozen") == 2
    assert "uv run --frozen python -m pytest -q" in workflow
    assert "      - pyproject.toml" in workflow
    assert "      - uv.lock" in workflow
    assert '"cryptography==46.0.3"' in metadata
    assert '"Flask>=3.0"' in metadata


def test_release_requires_an_explicit_republish_commit_for_an_existing_tag():
    workflow = (REPO / ".github" / "workflows" / "main.yml").read_text(
        encoding="utf-8"
    )

    assert '"$(git log -1 --format=%s)" != "release: republish $TAG"' in workflow
    assert 'gh release delete "$TAG" --yes --cleanup-tag' in workflow
    assert "--clobber" not in workflow
    assert "gh release upload" not in workflow
