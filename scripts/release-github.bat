@echo off
REM ================================================================
REM 一键推代码到 GitHub 并打 tag 触发三平台云编译
REM 使用前（只做一次）：
REM   1. 在 github.com 创建仓库，例如 hujiancheng/remote-debug
REM   2. 打开 https://github.com/settings/tokens （Classic 页）
REM      点 "Generate new token" → 选 "Generate new token (classic)"
REM      → Expiration 选 No expiration
REM      → 勾 "repo"（整组，含 Administration/Contents/Release 等所有仓库权限）
REM      → 勾 "workflow"（必须勾，否则 push 修改 .github/workflows 会被拒）
REM      → Generate token → 复制那串 ghp_xxx（只显示一次，push 时当密码用）
REM      或配置 SSH key（推荐，不用每次输密码）
REM   3. 回到本脚本，把下面 2 行改成你的仓库地址
REM ================================================================

REM ========== 改这里 ==========
set GITHUB_REPO=https://github.com/hujiancheng/remote-deploy.git
set TAG_VERSION=v1.0.0
REM ============================

cd /d %~dp0
chcp 65001 >nul

REM 如果没初始化过 git 仓库，初始化
if not exist .git (
  git init
  git branch -m main
)

REM 关联远程仓库（已关联时不会报错）
git remote add origin %GITHUB_REPO% 2>nul
REM 如果上面的 origin 已存在且地址不对，用 set-url 修正
git remote set-url origin %GITHUB_REPO%

git add -A
git commit -m "release %TAG_VERSION%" 2>nul
git tag -f %TAG_VERSION%

REM 推代码和 tag
echo [推送] 代码和标签 %TAG_VERSION% 到 %GITHUB_REPO%
git push -u origin main --force-with-lease
git push origin %TAG_VERSION% --force

echo.
echo [完成] 已打标签 %TAG_VERSION%，GitHub Actions 正在自动云编译三平台产物。
echo [查看] 浏览器打开:
echo         %GITHUB_REPO:~0,-4%/actions  （查看构建进度）
echo         %GITHUB_REPO:~0,-4%/releases  （构建完成后在此下载 6 个产物）
echo.
echo 产物清单：
echo   remote-debug-windows.exe        remote-debug-server-windows.exe
echo   remote-debug-linux              remote-debug-server-linux        （glibc 2.17，CentOS7+/Ubuntu18+ 直接跑）
echo   remote-debug-macos              remote-debug-server-macos
pause
