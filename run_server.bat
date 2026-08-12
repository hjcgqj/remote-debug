@echo off
REM 远程部署调试服务端启动脚本（Windows）
chcp 65001 >nul
cd /d %~dp0\server

REM 首次运行自动安装依赖
python -c "import fastapi, uvicorn, multipart" 2>nul
if errorlevel 1 (
    echo [初始化] 安装依赖...
    python -m pip install -r requirements.txt
)

REM 可通过环境变量自定义监听地址/端口/部署目录
REM set REMOTE_DEBUG_HOST=0.0.0.0
REM set REMOTE_DEBUG_PORT=9721
REM set REMOTE_DEBUG_ROOT=D:\deploy

python main.py
pause
