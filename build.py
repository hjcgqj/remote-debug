"""一键打包脚本：把服务端和客户端分别打包成单文件可执行程序。

打包后目标机器无需安装 Python，直接拷贝运行：
  - dist/remote-debug-server(.exe)   部署到远程目标机器
  - dist/remote-debug(.exe)          本机使用

使用：
  python build.py            # 同时打包 server + client
  python build.py server     # 仅打包 server
  python build.py client     # 仅打包 client

跨平台说明：
  - 必须在对应平台运行本脚本以生成对应平台的二进制
    （Windows 出 .exe，Linux/Mac 出无后缀二进制）
  - 产物体积约 15-25MB，单文件自包含 Python 解释器与全部依赖
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUILD = os.path.join(ROOT, "build")


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build] 未检测到 PyInstaller，正在安装...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller>=6.0"]
        )


def build_server():
    print("[build] 打包服务端 -> dist/remote-debug-server")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "remote-debug-server",
        # 把 server 目录加入模块搜索路径，确保 config/deploy/process_manager 可被定位
        "--paths", os.path.join(ROOT, "server"),
        # uvicorn 运行时动态导入较多子模块，必须 collect-all，否则打包后启动报缺模块
        "--collect-all", "uvicorn",
        "--collect-all", "fastapi",
        "--collect-all", "starlette",
        "--collect-all", "multipart",
        "--collect-all", "anyio",
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "server_work"),
        "--specpath", os.path.join(BUILD, "server_spec"),
        "--clean", "--noconfirm",
        os.path.join(ROOT, "server", "main.py"),
    ]
    subprocess.check_call(args)


def build_client():
    print("[build] 打包客户端 -> dist/remote-debug")
    args = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--name", "remote-debug",
        "--paths", os.path.join(ROOT, "client"),
        "--collect-all", "requests",
        "--collect-all", "websocket",
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "client_work"),
        "--specpath", os.path.join(BUILD, "client_spec"),
        "--clean", "--noconfirm",
        os.path.join(ROOT, "client", "cli.py"),
    ]
    subprocess.check_call(args)


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    ensure_pyinstaller()
    os.makedirs(DIST, exist_ok=True)
    os.makedirs(BUILD, exist_ok=True)
    if target in ("all", "server"):
        build_server()
    if target in ("all", "client"):
        build_client()
    print(f"\n[build] 完成。产物目录: {DIST}")
    for name in os.listdir(DIST):
        print(f"  - {os.path.join(DIST, name)}")


if __name__ == "__main__":
    main()
