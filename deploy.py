import re
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

sys.path.append(str(Path(__file__).resolve().parent))
from app.common.config import VERSION
from app.config.constants import APP_NAME, AUTHOR, YEAR


def build_args() -> list[str]:
    nuitka_command = f'"{sys.executable}" -m nuitka'

    assetFiles = [
        "app/assets/logo.png",
        "app/assets/home.png",
        "app/assets/1230.mp3",
        "app/assets/1825.mp3",
        "app/assets/class.mp3",
    ]
    missingFiles = [path for path in assetFiles if not Path(path).is_file()]

    if missingFiles:
        print(f"\n[ERROR] Missing required files: {missingFiles}")
        print("Please ensure these files are committed to Git.")
        sys.exit(1)

    match = re.match(r"^(\d+\.\d+\.\d+(?:\.\d+)?)", VERSION)
    clean_version = match.group(1) if match else "1.0.0"
    return [
        nuitka_command,
        "--standalone",
        "--windows-console-mode=disable",
        "--plugin-enable=pyside6",
        "--assume-yes-for-downloads",
        "--msvc=latest",
        "--include-qt-plugins=multimedia,texttospeech",
        "--include-package=requests",
        "--include-package=loguru",
        "--include-data-dir=app/assets=app/assets",
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
    sys.exit(main())
