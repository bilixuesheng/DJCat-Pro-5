import re

from app.common.config import VERSION

APP_NAME = "电教猫 Pro 5"
YEAR = 2026
AUTHOR = "XUESHENG"

AUTHOR_URL = "https://space.bilibili.com/1956850051"
DOWNLOAD_URL = "https://updata.cn-nb1.rains3.com/DJCat-Pro.exe"
UPDATE_API = "https://api.djcatpro.top"
AI_MARKDOWN_API = "https://api.djcatpro.top/ai/markdown"
_RELEASE_VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")


def normalizeReleaseVersion(version):
    version = str(version).strip().removeprefix("v")
    if not _RELEASE_VERSION.fullmatch(version):
        raise ValueError("更新版本号无效")
    return version


def updateDownloadUrl(version, architecture):
    version = normalizeReleaseVersion(version)
    if architecture not in {"x86_64", "arm64"}:
        raise ValueError("更新架构无效")
    filename = f"DJCat-Pro-v{version}-Windows-{architecture}-Setup.exe"
    return (
        "https://github.com/bilixuesheng/DJCat-Pro-5/releases/download/"
        f"v{version}/{filename}"
    )


def updateChecksumUrl(version, architecture):
    return f"{updateDownloadUrl(version, architecture)}.sha256"

__all__ = [
    "AI_MARKDOWN_API",
    "APP_NAME",
    "AUTHOR",
    "AUTHOR_URL",
    "DOWNLOAD_URL",
    "UPDATE_API",
    "VERSION",
    "YEAR",
    "normalizeReleaseVersion",
    "updateDownloadUrl",
    "updateChecksumUrl",
]
