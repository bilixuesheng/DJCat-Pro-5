import platform
import re


def clientArchitecture() -> str:
    machine = platform.machine().lower()
    return "arm64" if machine in {"arm64", "aarch64"} else "x86_64"


def versionKey(value: str) -> tuple:
    value = str(value or "").strip().lower().removeprefix("v")
    value = value.partition("+")[0]
    core, separator, prerelease = value.partition("-")
    if re.fullmatch(r"\d+(?:\.\d+)*", core):
        coreParts = [int(part) for part in core.split(".")]
        while len(coreParts) > 1 and coreParts[-1] == 0:
            coreParts.pop()
        coreKey = tuple((0, part) for part in coreParts)
        prereleaseKey = tuple(
            (0, int(part)) if part.isdigit() else (1, part)
            for part in re.findall(r"\d+|[a-z]+", prerelease)
        )
        return coreKey, 0 if separator else 1, prereleaseKey

    parts = re.findall(r"\d+|[a-z]+", value)
    return (
        tuple((0, int(part)) if part.isdigit() else (1, part) for part in parts),
        1,
        (),
    )


def isUpdateAvailable(installedVersion: str, catalogVersion: str) -> bool:
    if not installedVersion or not catalogVersion:
        return False
    return versionKey(catalogVersion) > versionKey(installedVersion)
