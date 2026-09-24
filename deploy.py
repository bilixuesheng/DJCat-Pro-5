import re
import subprocess
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))
from app.common.config import VERSION
from app.config.constants import APP_NAME, AUTHOR, YEAR


def _numeric_version(version: str) -> str:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:\.(\d+)|-pre\.(\d+)|-kb\d+)?", version)
    if not match:
        return "1.0.0.0"
    return f"{match.group(1)}.{match.group(2) or match.group(3) or '0'}"


QT_TRANSLATION_FILES = ("qtbase_zh_CN.qm",)


def qtTranslationArgs() -> list[str]:
    """把原生控件右键菜单等 Qt 自带文案的中文翻译打进包里，路径与 QT_TRANSLATIONS_DIR 对应。"""
    from PySide6.QtCore import QLibraryInfo

    source = Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    missing = [name for name in QT_TRANSLATION_FILES if not (source / name).is_file()]
    if missing:
        print(f"\n[ERROR] Missing Qt translations in {source}: {missing}")
        sys.exit(1)
    return [
        f'--include-data-files="{source / name}"=app/translations/{name}'
        for name in QT_TRANSLATION_FILES
    ]


def build_args() -> list[str]:
    nuitka_command = f'"{sys.executable}" -m nuitka'

    assetFiles = [
        "app/assets/logo.png",
        "app/assets/home.png",
        "app/assets/deepseek.png",
        "app/assets/1230.mp3",
        "app/assets/1825.mp3",
        "app/assets/class.mp3",
    ]
    missingFiles = [path for path in assetFiles if not Path(path).is_file()]

    if missingFiles:
        print(f"\n[ERROR] Missing required files: {missingFiles}")
        print("Please ensure these files are committed to Git.")
        sys.exit(1)

    clean_version = _numeric_version(VERSION)
    return [
        nuitka_command,
        "--standalone",
        "--windows-console-mode=disable",
        "--plugin-enable=pyside6",
        "--assume-yes-for-downloads",
        "--msvc=latest",
        "--disable-cache=ccache",
        "--include-qt-plugins=multimedia,texttospeech",
        "--include-package=requests",
        "--include-package=loguru",
        "--include-package=edge_tts",
        "--include-package=pyqt_github_markdown",
        "--include-package=markdown_it",
        "--include-package=linkify_it",
        "--include-package=pygments",
        "--include-package=emoji",
        "--include-package=PIL",
        "--include-data-dir=app/assets=app/assets",
        *qtTranslationArgs(),
        "--windows-icon-from-ico=app/assets/logo.png",
        f'--company-name="{AUTHOR}"',
        f'--product-name="{APP_NAME}"',
        f"--file-version={clean_version}",
        f"--product-version={clean_version}",
        f'--file-description="{APP_NAME}"',
        f'--copyright="Copyright(C) {YEAR} {AUTHOR}"',
        "--output-dir=dist",
        "djcat.py",
    ]


def main() -> int:
    if sys.platform != "win32":
        print("Error: This script is for Windows only.")
        return 1

    args = build_args()
    command = " ".join(args)

    print(f"Build Version: {VERSION}")
    print(f"Execution Command: {command}\n")
    result = subprocess.run(command, shell=True, check=False)

    if result.returncode == 0:
        print("\n[SUCCESS] Build finished. Output: dist/djcat.dist")
    else:
        print(f"\n[ERROR] Build failed with exit code: {result.returncode}")

    return result.returncode


if __name__ == "__main__":
    if sys.platform == "win32":
        import io

        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
