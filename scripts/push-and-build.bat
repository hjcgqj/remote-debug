@echo off
REM ================================================================
REM 自动化推送脚本：本地 commit -> 推 GitHub -> Actions 自动云编译三平台
REM
REM 首次使用（只做一次）：
REM   1. 去 github.com 新建仓库，如 hujiancheng/remote-debug（不要勾选 README）
REM   2. 打开 https://github.com/settings/tokens （Classic 页）
REM      点 "Generate new token" → 选 "Generate new token (classic)"
REM      → Expiration 选 No expiration
REM      → 勾 "repo"（整组，含 Administration/Contents/Release 等所有仓库权限）
REM      → 勾 "workflow"（必须勾，否则 push 修改 .github/workflows 会被拒）
REM      → Generate token → 复制那串 ghp_xxx 备用（只显示一次）
REM      或配 SSH key（推荐：GITHUB_REPO 改成 git@github.com:hujiancheng/remote-deploy.git，不用密码）
REM   3. 改下面两行：GITHUB_REPO 填你的仓库地址，GITHUB_USER 填你的用户名
REM   4. 双击运行；提示 Password 时粘贴上面的 token（不是账号密码！）
REM ================================================================

REM ========== 改成你自己的 ==========
set GITHUB_REPO=https://github.com/hjcgqj/remote-debug.git
set GITHUB_USER=hjcgqj
REM ==================================

cd /d %~dp0
chcp 65001 >nul

REM ---- 首次 git 初始化 ----
if not exist .git (
  git init
  git branch -m main
  echo [初始化] 本地仓库已创建
)
git remote add origin %GITHUB_REPO% 2>nul
git remote set-url origin %GITHUB_REPO%
git config user.name "%GITHUB_USER%"
git config credential.helper store
echo.

REM ---- 自动 commit ----
git add -A
git status --short
for /f "tokens=* USEBACKQ" %%i in (`git status --short`) do set DIRTY=1
if not defined DIRTY (
  echo [无变更] 代码未改动，直接 push
) else (
  set MSG=auto commit %DATE:~0,10% %TIME:~0,8%
  call git commit -m "auto commit %DATE:~0,10% %TIME:~0,8%"
  echo [提交] 已 commit
)
echo.

REM ---- push main，Actions 自动触发三平台编译 ----
echo [推送] 到 %GITHUB_REPO%
git push -u origin main --force-with-lease
if errorlevel 1 (
  echo.
  echo [推送失败] 如果提示 Authentication failed：
  echo   - 确认在 github.com/settings/tokens 生成了带 repo 权限的 Personal Access Token
  echo   - 提示 Password 时粘贴 Token（不是 GitHub 登录密码）
  echo 或改用 SSH: 改 GITHUB_REPO=git@github.com:hujiancheng/remote-deploy.git
  pause
  exit /b 1
)

echo.
echo ============================================================
echo [完成] GitHub Actions 正在自动云编译三平台（约 15-25 分钟）
echo 查看进度和下载产物，打开：
echo    %GITHUB_REPO:~0,-4%/actions
echo
echo 点运行记录 → Artifacts 区 → 下载 remote-debug-all-platforms
echo 解压后获得 6 个文件：
echo   remote-debug-windows.exe / remote-debug-linux / remote-debug-macos
echo   remote-debug-server-windows.exe / remote-debug-server-linux / remote-debug-server-macos
echo ============================================================
REM 浏览器自动打开 Actions 页
start "" "%GITHUB_REPO:~0,-4%/actions"
pause
