"""Android / 鸿蒙 设备桥接模块。

设计动机：
  Android 与鸿蒙(HarmonyOS) 应用沙箱严格，普通应用不能任意 exec 二进制，
  也无法在其上常驻一个 HTTP 调试服务。这两个平台的"远程部署调试"正确姿势是
  在本机通过 adb（Android）/ hdc（鸿蒙）对设备操作：push 程序、运行、拉日志。

本模块即为本机侧的代理：
  - 自动探测本机 PATH 中的 hdc / adb，优先 hdc（鸿蒙场景），其次 adb
  - 通过子进程调用对应工具命令，对设备做 list/push/run/logs 操作
  - 与 HTTP 服务端解耦：设备平台不走 /api，直接走本机工具链

依赖：本机需安装 Android Platform Tools（含 adb）或 HarmonyOS Command Tool（含 hdc），
      并加入 PATH。设备需开启 USB/网络调试。

用法（经 cli.py 暴露）：
  remote-debug device list
  remote-debug device push D:\\build\\app.apk /data/local/tmp/app
  remote-debug device run -- /data/local/tmp/app --port 8080
  remote-debug device logs
  remote-debug device shell -- ls -l /data/local/tmp
"""
import os
import shutil
import subprocess
import sys


class DeviceBridge:
    def __init__(self, tool: str = "", device: str = ""):
        # tool 留空则自动探测：先 hdc（鸿蒙），再 adb
        self.tool = tool or self._detect_tool()
        if not self.tool:
            raise RuntimeError(
                "未找到 adb / hdc。请安装 Android Platform Tools 或 HarmonyOS Command Tool "
                "并加入 PATH，或用 --tool 指定。"
            )
        self.device = device  # 指定设备序列号，空则用默认设备

    # ---------- 工具探测 ----------
    @staticmethod
    def _detect_tool() -> str:
        for name in ("hdc", "adb"):
            if shutil.which(name):
                return name
        return ""

    def _base(self) -> list:
        """构造工具基础命令前缀，含设备选择。"""
        if self.tool == "hdc":
            # hdc 用 -t <serial> 指定设备
            return [self.tool, "-t", self.device] if self.device else [self.tool]
        else:
            # adb 用 -s <serial>
            return [self.tool, "-s", self.device] if self.device else [self.tool]

    # ---------- 命令实现 ----------
    def list_devices(self) -> list:
        """列出已连接设备，返回 [(serial, state)]。"""
        # 两种工具都用 devices 子命令
        out = subprocess.run(
            [self.tool, "devices"], capture_output=True, text=True, timeout=10
        )
        devices = []
        for line in out.stdout.splitlines()[1:]:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                devices.append((parts[0], parts[1]))
            elif len(parts) == 1:
                devices.append((parts[0], "unknown"))
        return devices

    def push(self, local: str, remote: str) -> str:
        """把本地文件/目录推送到设备路径。"""
        if not os.path.exists(local):
            raise FileNotFoundError(f"本地路径不存在: {local}")
        cmd = self._base()
        # adb/hdc 均用 push <local> <remote>
        if self.tool == "hdc":
            cmd += ["file", "send", local, remote]
        else:
            cmd += ["push", local, remote]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise RuntimeError(f"push 失败: {r.stderr.strip() or r.stdout.strip()}")
        return r.stdout.strip()

    def shell(self, command: list, interactive: bool = False) -> int:
        """在设备上执行 shell 命令。

        interactive=True 时直接继承本机 stdin/stdout，适合交互式 shell 或实时日志。
        否则捕获输出并打印。
        """
        cmd = self._base()
        if self.tool == "hdc":
            cmd += ["shell"] + command
        else:
            cmd += ["shell"] + command
        if interactive:
            return subprocess.call(cmd)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.stdout:
            sys.stdout.write(r.stdout)
        if r.stderr:
            sys.stderr.write(r.stderr)
        return r.returncode

    def logs(self, pid: str = "", tag: str = "") -> int:
        """实时拉取设备日志。Android 用 logcat，鸿蒙用 hilog。"""
        cmd = self._base()
        if self.tool == "hdc":
            cmd += ["shell", "hilog"]
            if tag:
                cmd += ["-T", tag]
        else:
            cmd += ["shell", "logcat"]
            if pid:
                cmd += ["--pid=" + pid]
            if tag:
                cmd += ["-s", tag]
        # 日志是持续流，直接继承 stdio，Ctrl+C 退出
        return subprocess.call(cmd)

    def info(self) -> dict:
        return {"tool": self.tool, "device": self.device or "(default)"}
