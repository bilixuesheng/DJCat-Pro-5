import subprocess
import sys
import os
from pathlib import Path
import re

# Fix encoding for Windows CI
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# Ensure we can import app.common.config
sys.path.append(str(Path(__file__).resolve().parent))
from app.common.config import VERSION, YEAR, AUTHOR, APP_NAME

def build_args() -> list[str]:
    nuitka_command = f'"{sys.executable}" -m nuitka'
    
    # 1. 修正检查路径
    # logo.png 在根目录，home.png 在 app/view/ 目录
    data_files_to_check = ["app/view/home.png", "logo.png"]
    missing_files = [f for f in data_files_to_check if not Path(f).exists()]
    
    if missing_files:
        print(f"\n[ERROR] Missing required files: {missing_files}")
        print("Please ensure these files are committed to Git.")
        sys.exit(1)

    match = re.match(r'^(\d+\.\d+\.\d+(?:\.\d+)?)', VERSION)
    clean_version = match.group(1) if match else "1.0.0"
    return [
        nuitka_command,
        '--standalone',
        '--windows-console-mode=disable',
        '--plugin-enable=pyside6',
        '--assume-yes-for-downloads',
        '--msvc=latest',
        
        # Dependencies
        '--include-package=requests',
        '--include-package=loguru',
        
        # Data files
        '--include-data-file=app/view/home.png=app/view/home.png',
        '--include-data-file=logo.png=logo.png',
        
        # Metadata
        '--windows-icon-from-ico=logo.png',
        f'--company-name="{AUTHOR}"',
        f'--product-name="{APP_NAME}"',
        
        # === 修改：使用过滤后的纯数字版本号 ===
        f'--file-version={clean_version}',
        f'--product-version={clean_version}',
        
        f'--file-description="{APP_NAME}"',
        f'--copyright="Copyright(C) {YEAR} {AUTHOR}"',
        
        '--output-dir=dist',
        'djcat.py',
    ]


def main() -> int:
    if sys.platform != "win32":
        print("Error: This script is for Windows only.")
        return 1

    args = build_args()
    command = ' '.join(args)

    print(f"Build Version: {VERSION}")
    print(f"Execution Command: {command}\n")
    
    # Execute Nuitka
    result = subprocess.run(command, shell=True)
    
    if result.returncode == 0:
        print("\n[SUCCESS] Build finished. Output: dist/djcat.dist")
    else:
        print(f"\n[ERROR] Build failed with exit code: {result.returncode}")
        
    return result.returncode

if __name__ == "__main__":
    # Use standard GD entry pattern
    sys.exit(main())
