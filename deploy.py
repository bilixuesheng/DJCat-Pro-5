import subprocess
import sys
from pathlib import Path

# 将项目根目录加入 sys.path，以便导入 app.common.config
sys.path.append(str(Path(__file__).resolve().parent))
from app.common.config import VERSION, YEAR, AUTHOR, APP_NAME

def build_args() -> list[str]:
    nuitka_command = f'"{sys.executable}" -m nuitka'

    return [
        nuitka_command,
        '--standalone',
        '--windows-console-mode=disable',  # 禁用控制台窗口
        '--plugin-enable=pyside6',         # 启用 pyside6 插件
        '--assume-yes-for-downloads',      # 自动同意下载缺失的依赖(如依赖树解析器)
        '--msvc=latest',                   # 使用最新的 MSVC 编译器
        
        # 显式包含依赖包，防止 Nuitka 漏打包
        '--include-package=requests',
        '--include-package=loguru',
        
        # 包含必要的数据文件 (源文件=目标文件)
        '--include-data-file=home.png=home.png',
        '--include-data-file=logo.png=logo.png',
        
        # Windows 应用元数据
        '--windows-icon-from-ico=logo.png', # Nuitka 支持直接使用 png 作为图标
        f'--company-name="{AUTHOR}"',
        f'--product-name="{APP_NAME}"',
        f'--file-version={VERSION}',
        f'--product-version={VERSION}',
        f'--file-description="{APP_NAME}"',
        f'--copyright="Copyright(C) {YEAR} {AUTHOR}"',
        
        '--output-dir=dist',
        'djcat.py', # 入口文件
    ]

def main() -> int:
    if sys.platform != "win32":
        print("此打包脚本仅支持 Windows")
        return 1

    args = build_args()
    command = ' '.join(args)

    print(f"执行 Nuitka 打包命令:\n{command}\n")
    result = subprocess.run(command, shell=True)
    
    if result.returncode == 0:
        print("\n✅ 打包成功！产物位于 dist/djcat.dist 目录。")
    else:
        print(f"\n❌ 打包失败，退出码: {result.returncode}")
        
    return result.returncode

if __name__ == "__main__":
    raise SystemExit(main())
