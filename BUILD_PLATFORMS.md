# 三平台自动化构建（Windows / Linux / macOS）

## 方案选择

| 方案 | 触发方式 | 产物位置 | 何时用 |
|---|---|---|---|
| **A. 日常自动 CI（推荐）** | 每次 `git push` 到 main，10 秒推完代码你就不用管了，Actions 自动云编译三平台 | Actions → Artifacts → `remote-debug-all-platforms.zip`（一键下载 6 个文件） | 日常开发、每次改完代码要拿三平台二进制 |
| **B. 正式 Release** | 手动打 tag `vX.Y.Z` 或运行 `release-github.bat` | 仓库 Releases 页（附带自动生成的 release notes） | 正式版本发布 |
| **C. Docker 本地出 Linux 版** | 本地一条 `bash scripts/build-linux-docker.sh` | `dist/remote-debug(-server)-linux` | 不想用 GitHub、立刻要 Linux 二进制 |
| **D. 本地单平台构建** | 本地 `python build.py` | `dist/` | 本机平台调试 |

---

## 方案 A：日常自动 CI（推荐，真正的自动化）

> 你**不用给任何人 GitHub 账号密码**，但你本人要配一次仓库 + 凭证（这是 GitHub 强制的安全机制，无法绕开）。

### 一次性准备（5 分钟搞定）

1. **建仓库**：浏览器打开 <https://github.com/new>，仓库名比如 `remote-debug`，Public/Private 都行，**不要**勾任何 Initialize with 选项 → Create repository。
2. **生成 Personal Access Token（Classic，最高权限）**（只需做一次）：
   1. 打开 <https://github.com/settings/tokens>（**Classic** 页，非 Fine-grained）
   2. 点 **`Generate new token`** → 选 **`Generate new token (classic)`**
   3. 填表单：
      - **Note**：随意，如 `remote-deploy-full`
      - **Expiration**：`No expiration`（永不过期，最方便）
      - **勾选权限**（这两项覆盖全部所需操作）：
        - ✅ **`repo`**（整组勾上，包含 Contents / Administration / Release 等所有仓库权限）
        - ✅ **`workflow`**（**必须勾**，否则 push 时修改 `.github/workflows/*.yml` 会被拒）
   4. 拉到底 → 点绿色 **`Generate token`**
   5. 复制显示的那串 `ghp_xxx…` 存记事本（**只显示一次**，后续 push 提示 Password 时粘贴它）
3. **改推送脚本**：编辑 [scripts/push-and-build.bat](scripts/push-and-build.bat)，只改 2 行：
   ```bat
   set GITHUB_REPO=https://github.com/你的用户名/remote-deploy.git
   set GITHUB_USER=你的用户名
   ```

### 之后每次：双击 → 自动云编译三平台（完事）

```
scripts\push-and-build.bat
```

脚本做的事：
1. 首次自动 init git、remote、保存凭证（提示 Password 时粘贴刚才的 **Token**，不是 GitHub 登录密码）
2. `git add .` + `git commit`（无变更则跳过）
3. `git push origin main`
4. **自动弹出浏览器到 Actions 页**，三平台云编译跑起来了

### 取产物

编译跑完（约 15–25 分钟），在 Actions 页面点运行记录，拉到底部 **Artifacts**：
- 下 `remote-debug-all-platforms` 一个 zip，解压后就全了：

| Windows | Linux (glibc 2.17) | macOS |
|---|---|---|
| remote-debug-windows.exe | remote-debug-linux | remote-debug-macos |
| remote-debug-server-windows.exe | remote-debug-server-linux | remote-debug-server-macos |

**Linux 兼容性**：在 `centos:7` 容器里构建（glibc 2.17 / manylinux2014），**CentOS 7+ / RHEL 7+ / Ubuntu 18.04+ / Debian 10+ 直接跑**，不会有 `GLIBC_2.xx not found`。

---

## 方案 B：正式 Release

改 `scripts/release-github.bat` 的 `TAG_VERSION`，双击，同流程。产物在 **Releases** 页，附带自动 release notes。

---

## 方案 C：Docker 本地出 Linux 版（不依赖 GitHub，立刻可用）

你只要本机装了 Docker（Windows/Mac/Linux 都行）：

```bash
bash scripts/build-linux-docker.sh
```

同样用 centos:7 容器，产物 `dist/remote-debug-linux` 和 `dist/remote-debug-server-linux` 是 glibc 2.17 兼容的，拷到任意新老 Linux 直接跑。

---

## 方案 D：本地单平台

```bash
# 出你当前平台的 server + client
python build.py

# 只要 client
python build.py client
```

---

## 各平台使用方式

### Windows 目标机
```bat
remote-debug-server-windows.exe
REM 环境变量改配置：
set REMOTE_DEBUG_HOST=0.0.0.0
set REMOTE_DEBUG_PORT=9721
set REMOTE_DEBUG_ROOT=D:\deploy
remote-debug-server-windows.exe
```

### Linux 目标机（拷 binary 上去）
```bash
chmod +x remote-debug-server-linux
./remote-debug-server-linux                  # 前台
nohup ./remote-debug-server-linux > server.log 2>&1 &   # 后台
```

### macOS 目标机
```bash
chmod +x remote-debug-server-macos
./remote-debug-server-macos
# Gatekeeper 拦截时：右键 → 打开 → 允许
```

### 客户端（三平台通用）
```bash
# 本机用
remote-debug -s http://远程IP:9721 info
remote-debug -s http://远程IP:9721 deploy D:\build\out app --exec "*"
remote-debug -s http://远程IP:9721 run --cwd app myapp.exe
remote-debug -s http://远程IP:9721 logs <process_id>
remote-debug device list                      # Android/鸿蒙 adb/hdc 列设备
```
