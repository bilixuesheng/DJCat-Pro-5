from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest


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
    assert 'Name: "english"' not in script
    assert 'Name: "chinesetraditional"' not in script
    assert "ArchitecturesAllowed={#MyAppArch}" in script
    assert "Windows-{#MyAppArchName}-Setup" in script


def test_release_workflow_uses_native_windows_runners_and_four_packages():
    workflow = (REPO / ".github" / "workflows" / "main.yml").read_text(encoding="utf-8")

    assert "runner: windows-2022" in workflow
    assert "runner: windows-11-arm" in workflow
    assert "python_arch: x64" in workflow
    assert "python_arch: arm64" in workflow
    assert "verify_pe_arch.py" in workflow
    assert "Windows-x86_64.zip" in workflow
    assert "Windows-arm64.zip" in workflow
    assert "Windows-x86_64-Setup.exe" in workflow
    assert "Windows-arm64-Setup.exe" in workflow
    assert "gh release create" in workflow
    assert "--prerelease" in workflow
