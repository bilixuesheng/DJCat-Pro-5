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
    # 默认目录改由 GetDefaultDir 计算，优先落在非还原分区；
    # 没有可用固定盘时回退仍是 {autopf}\DJCat Pro，目录名不带 5。
    assert "DefaultDirName={code:GetDefaultDir}" in script
    assert "ExpandConstant('{autopf}\\DJCat Pro')" in script
    assert "\\DJCat Pro 5" not in script


def test_pre_release_number_is_preserved_in_windows_file_version(monkeypatch):
    monkeypatch.setattr(deploy, "VERSION", "5.0.0-pre.22")

    args = deploy.buildArgs()

    assert "--file-version=5.0.0.22" in args
    assert "--product-version=5.0.0.22" in args


def test_kb_release_uses_base_version_for_windows_file_version(monkeypatch):
    monkeypatch.setattr(deploy, "VERSION", "5.1.4-kb20260914")

    args = deploy.buildArgs()

    assert "--file-version=5.1.4.0" in args
    assert "--product-version=5.1.4.0" in args


def test_windows_build_includes_ico_normalizer():
    assert "--include-package=PIL" in deploy.buildArgs()


def test_build_bundles_qt_chinese_translation_where_the_app_looks_for_it():
    from app.config.paths import ASSET_DIR, QT_TRANSLATIONS_DIR

    args = [arg for arg in deploy.buildArgs() if "qtbase_zh_CN.qm" in arg]

    assert len(args) == 1
    source, target = args[0].removeprefix("--include-data-files=").rsplit("=", 1)
    assert Path(source.strip('"')).is_file()
    assert target == (
        QT_TRANSLATIONS_DIR.relative_to(ASSET_DIR.parents[1]) / "qtbase_zh_CN.qm"
    ).as_posix()
