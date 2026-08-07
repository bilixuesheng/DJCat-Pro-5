"""Verify that a Windows PE executable targets the expected CPU architecture."""

from __future__ import annotations

import argparse
from pathlib import Path


PE_MACHINES = {
    "x86_64": 0x8664,
    "arm64": 0xAA64,
}


def read_pe_machine(path: Path) -> int:
    data = path.read_bytes()
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError(f"{path} is not a DOS/PE executable")

    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    if pe_offset + 6 > len(data) or data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError(f"{path} does not contain a valid PE header")

    return int.from_bytes(data[pe_offset + 4 : pe_offset + 6], "little")


def verify_pe_arch(path: Path, expected_arch: str) -> None:
    expected_machine = PE_MACHINES[expected_arch]
    actual_machine = read_pe_machine(path)
    if actual_machine != expected_machine:
        raise ValueError(
            f"{path} targets PE machine 0x{actual_machine:04X}, "
            f"expected {expected_arch} (0x{expected_machine:04X})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("expected_arch", choices=sorted(PE_MACHINES))
    args = parser.parse_args()

    verify_pe_arch(args.path, args.expected_arch)
    print(f"Verified {args.path}: {args.expected_arch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
