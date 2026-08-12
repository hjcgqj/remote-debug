#!/bin/bash
# Linux 版云编译兜底脚本（Docker 方式，不依赖 GitHub Actions）
#
# 用途：在任意安装了 Docker 的机器（Windows/Mac/Linux 均可）上，
# 一键产出与 centos:7 / glibc 2.17 兼容的 Linux 单文件二进制：
#   dist/remote-debug-server-linux
#   dist/remote-debug-linux
#
# 用例：
#   bash scripts/build-linux-docker.sh
#
# 原理：在 centos:7 容器里从源码编译 Python 3.10 → 装依赖 → 跑 build.py。
# 容器 glibc 2.17，PyInstaller 生成的单文件二进制依赖与宿主 glibc 一致，
# 所以产物可以在 CentOS 7+/Ubuntu 18.04+/Debian 10+/RHEL 7+ 直接运行。

set -euxo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"  # 项目根
DIST="$HERE/dist"
mkdir -p "$DIST"

IMAGE="remote-debug-build-linux:latest"

# 构建构建镜像（含 Python 3.10 源码编译与 PyInstaller），便于重复构建
cat > /tmp/RemoteDebugDockerfile <<'DOCKERFILE'
FROM centos:7

# 基础编译依赖
RUN yum groupinstall -y "Development Tools" && \
    yum install -y zlib-devel bzip2 bzip2-devel readline-devel sqlite \
                   sqlite-devel openssl-devel xz xz-devel libffi-devel \
                   tar gzip make wget perl-core

# Python 3.10 源码编译（IUS 源经常断，源码最稳）
WORKDIR /tmp
RUN wget -q https://www.python.org/ftp/python/3.10.14/Python-3.10.14.tgz && \
    tar xf Python-3.10.14.tgz && \
    cd Python-3.10.14 && \
    ./configure --prefix=/usr/local --enable-shared \
      LDFLAGS="-Wl,-rpath,/usr/local/lib" && \
    make -j"$(nproc)" >/dev/null && \
    make install && \
    ln -sf /usr/local/bin/python3.10 /usr/local/bin/python3 && \
    ln -sf /usr/local/bin/pip3.10 /usr/local/bin/pip3 && \
    ldconfig && \
    cd / && rm -rf /tmp/Python-3.10.14*

# 安装打包依赖
RUN /usr/local/bin/python3.10 -m pip install --no-cache-dir --upgrade pip && \
    /usr/local/bin/python3.10 -m pip install --no-cache-dir \
      "pyinstaller>=6.0"

WORKDIR /workspace
DOCKERFILE

docker build -f /tmp/RemoteDebugDockerfile -t "$IMAGE" "$HERE"

# 在容器内安装 server/client 运行时依赖并执行 build.py
# 运行时依赖每次构建都重新安装，保证版本最新（这部分没打镜像，省得更新依赖就重编镜像）
docker run --rm \
  -v "$HERE:/workspace:rw" \
  -w /workspace \
  "$IMAGE" \
  /bin/bash -c '
    set -euxo pipefail
    /usr/local/bin/python3.10 -m pip install --no-cache-dir \
      -r server/requirements.txt -r client/requirements.txt
    /usr/local/bin/python3.10 build.py
  '

# 产物重命名为带平台后缀
for f in "$DIST"/remote-debug-server "$DIST"/remote-debug; do
  [ -f "$f" ] || continue
  mv "$f" "${f}-linux"
  echo "[产出] ${f}-linux  ($(du -h "${f}-linux" | cut -f1))"
done

ls -la "$DIST"
