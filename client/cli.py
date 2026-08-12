"""远程部署调试客户端 CLI。

用法示例（假设服务端在 192.168.1.100:9721）：

  # 查看服务端信息
  python cli.py --server http://192.168.1.100:9721 info

  # 部署单个文件
  python cli.py deploy D:\\build\\myapp.exe app

  # 部署整个目录（自动打包为 zip 上传并解压）
  python cli.py deploy D:\\build\\out app

  # 启动进程
  python cli.py run --cwd app myapp.exe --port 8080
  python cli.py run --shell "myapp.exe && echo done"

  # 查看进程列表
  python cli.py ps

  # 实时查看日志（Ctrl+C 退出）
  python cli.py logs <process_id>

  # 查看历史日志
  python cli.py cat <process_id>

  # 停止 / 删除
  python cli.py stop <process_id>
  python cli.py rm <process_id>
"""
import argparse
import json
import os
import sys
import tempfile
import zipfile
from urllib.parse import urlparse

import requests

# WebSocket 客户端（同步），用于实时日志流
try:
    import websocket  # type: ignore
except ImportError:
    websocket = None

# Android/鸿蒙 设备桥接（adb/hdc），仅 device 子命令使用
try:
    from device_bridge import DeviceBridge
except ImportError:
    DeviceBridge = None


def default_server() -> str:
    return os.getenv("REMOTE_DEBUG_SERVER", "http://localhost:9721")


def normalize(server: str) -> str:
    server = server.rstrip("/")
    if not server.startswith("http://") and not server.startswith("https://"):
        server = "http://" + server
    return server


def ws_url(server: str, path: str) -> str:
    p = urlparse(server)
    scheme = "wss" if p.scheme == "https" else "ws"
    return f"{scheme}://{p.netloc}{path}"


def err(msg: str):
    print(f"[错误] {msg}", file=sys.stderr)


# ===================== 子命令实现 =====================
def cmd_info(args):
    r = requests.get(f"{args.server}/api/info", timeout=10)
    r.raise_for_status()
    data = r.json()
    print(f"服务版本 : {data.get('service')} v{data.get('version')}")
    print(f"平台     : {data.get('platform')}")
    print(f"系统     : {data.get('system')} / {data.get('machine')}")
    print(f"Python   : {data.get('python')}")
    print(f"部署目录 : {data.get('deploy_root')}")
    print(f"进程数   : {data.get('process_count')}")


def cmd_deploy(args):
    local = args.local
    remote = args.remote or ""
    if not os.path.exists(local):
        err(f"本地路径不存在: {local}")
        sys.exit(1)

    files_for_upload = []  # [(filename, fileobj)]
    extract = False
    cleanup = None

    if os.path.isdir(local):
        # 目录：打包成 zip 上传并解压
        tmp = tempfile.NamedTemporaryFile(
            delete=False, suffix=".zip", prefix="deploy_"
        )
        tmp.close()
        cleanup = tmp.name
        zip_dir(local, tmp.name)
        files_for_upload = [("upload.zip", open(tmp.name, "rb"))]
        extract = True
        print(f"[打包] {local} -> {os.path.basename(tmp.name)}")
    else:
        files_for_upload = [(os.path.basename(local), open(local, "rb"))]

    # 可执行权限标记：--exec "*" 表示全部 +x；否则为相对路径列表
    exec_all = "*" in args.exec
    exec_paths = [p for p in args.exec if p != "*"]

    try:
        # requests 传入文件对象时会自动流式上传，不会一次性读入内存
        r = requests.post(
            f"{args.server}/api/deploy",
            files=[("files", f) for f in files_for_upload],
            data={
                "path": remote,
                "extract_zip": "true" if extract else "false",
                "exec_all": "true" if exec_all else "false",
                "exec_paths": json.dumps(exec_paths, ensure_ascii=False),
            },
            timeout=600,
        )
        r.raise_for_status()
        data = r.json()
        print(f"[部署成功] 共 {len(data.get('saved', []))} 个文件:")
        for p in data.get("saved", []):
            print(f"  {p}")
        print(f"[部署根目录] {data.get('deploy_root')}")
        if exec_all or exec_paths:
            who = "全部文件" if exec_all else ",".join(exec_paths)
            print(f"[可执行权限] 已标记 +x (非 Windows 生效): {who}")
    finally:
        for _, f in files_for_upload:
            f.close()
        if cleanup and os.path.exists(cleanup):
            os.remove(cleanup)


def zip_dir(src_dir: str, zip_path: str):
    src_dir = os.path.abspath(src_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(src_dir):
            for fn in files:
                full = os.path.join(root, fn)
                arc = os.path.relpath(full, src_dir)
                # 统一为正斜杠，避免 Windows 反斜杠在解压端出问题
                arc = arc.replace(os.sep, "/")
                z.write(full, arc)


def cmd_run(args):
    if not args.command:
        err("缺少要执行的命令")
        sys.exit(1)
    payload = {
        "command": args.command,
        "cwd": args.cwd,
        "name": args.name,
        "shell": args.shell,
    }
    r = requests.post(
        f"{args.server}/api/process/start", json=payload, timeout=30
    )
    r.raise_for_status()
    data = r.json()
    print(f"[已启动] process_id={data['process_id']} pid={data.get('pid')}")
    print(f"  命令: {' '.join(data.get('command', []))}")
    print(f"  状态: {data.get('status')}")
    print(f"  实时日志: python cli.py logs {data['process_id']}")
    print(data["process_id"])  # 末行单独输出 id，便于脚本捕获


def cmd_ps(args):
    r = requests.get(f"{args.server}/api/process", timeout=10)
    r.raise_for_status()
    procs = r.json().get("processes", [])
    if not procs:
        print("（无进程）")
        return
    print(f"{'process_id':<14}{'pid':<8}{'status':<10}{'rc':<6}command")
    print("-" * 70)
    for p in procs:
        print(
            f"{p['process_id']:<14}{str(p.get('pid') or '-'):<8}"
            f"{p.get('status',''):<10}{str(p.get('return_code') if p.get('return_code') is not None else '-'):<6}"
            f"{' '.join(p.get('command', []))}"
        )


def cmd_stop(args):
    r = requests.post(f"{args.server}/api/process/{args.process_id}/stop", timeout=30)
    if r.status_code == 404:
        err("进程不存在")
        sys.exit(1)
    r.raise_for_status()
    data = r.json()
    print(f"[已停止] {data['process_id']} status={data.get('status')}")


def cmd_rm(args):
    r = requests.delete(f"{args.server}/api/process/{args.process_id}", timeout=30)
    if r.status_code == 404:
        err("进程不存在")
        sys.exit(1)
    r.raise_for_status()
    print(f"[已删除] {args.process_id}")


def cmd_cat(args):
    r = requests.get(f"{args.server}/api/process/{args.process_id}/logs", timeout=30)
    if r.status_code == 404:
        err("进程不存在")
        sys.exit(1)
    r.raise_for_status()
    data = r.json()
    for chunk in data.get("logs", []):
        sys.stdout.write(chunk)
    if not data.get("logs"):
        print("（无历史日志）")


def cmd_logs(args):
    if websocket is None:
        err("缺少依赖 websocket-client，请执行: pip install websocket-client")
        sys.exit(1)
    url = ws_url(args.server, f"/ws/logs/{args.process_id}")
    print(f"[连接] {url}  (Ctrl+C 退出)\n" + "-" * 60)
    try:
        ws = websocket.create_connection(url, timeout=10)
    except Exception as e:
        err(f"连接失败: {e}")
        sys.exit(1)
    try:
        while True:
            try:
                raw = ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as e:
                err(f"连接断开: {e}")
                break
            if not raw:
                break
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                sys.stdout.write(raw)
                continue
            mtype = msg.get("type")
            if mtype == "history":
                sys.stdout.write(msg.get("data", ""))
                sys.stdout.flush()
            elif mtype == "log":
                sys.stdout.write(msg.get("data", ""))
                sys.stdout.flush()
            elif mtype == "exit":
                print(f"\n[进程结束] 返回码={msg.get('return_code')} 状态={msg.get('status')}")
                break
            elif mtype == "removed":
                print("\n[进程已被删除]")
                break
    except KeyboardInterrupt:
        print("\n[已退出日志流]")
    finally:
        try:
            ws.close()
        except Exception:
            pass


def cmd_files(args):
    if args.action == "ls":
        r = requests.get(f"{args.server}/api/files", params={"path": args.path or ""}, timeout=30)
        r.raise_for_status()
        files = r.json().get("files", [])
        if not files:
            print("（无文件）")
            return
        for f in files:
            print(f"{f.get('size', 0):>12}  {f.get('rel', f.get('path'))}")
    elif args.action == "rm":
        r = requests.delete(f"{args.server}/api/files", params={"path": args.path or ""}, timeout=30)
        if r.status_code >= 400:
            err(r.text)
            sys.exit(1)
        print(f"[已删除] {args.path or ''}")


# ===================== 设备桥接（Android/鸿蒙，走 adb/hdc）=====================
def cmd_device(args):
    if DeviceBridge is None:
        err("device 桥接模块未就绪（应与 cli 同目录）")
        sys.exit(1)
    try:
        bridge = DeviceBridge(tool=args.tool, device=args.device)
    except RuntimeError as e:
        err(str(e))
        sys.exit(1)

    action = args.action

    if action == "list":
        devs = bridge.list_devices()
        if not devs:
            print(f"（未检测到设备，工具={bridge.tool}）")
            return
        print(f"工具: {bridge.tool}")
        print(f"{'serial':<28}state")
        print("-" * 40)
        for s, st in devs:
            print(f"{s:<28}{st}")
        return

    if action == "info":
        print(f"工具: {bridge.info()['tool']}")
        print(f"设备: {bridge.info()['device']}")
        return

    if action == "push":
        if not args.rest:
            err("用法: device push <local> <remote>")
            sys.exit(1)
        local, remote = args.rest[0], args.rest[1]
        out = bridge.push(local, remote)
        print(f"[推送完成] {local} -> {remote}")
        if out:
            print(out)
        return

    if action == "run":
        if not args.rest:
            err("用法: device run -- <cmd> [args...]")
            sys.exit(1)
        # run 在设备上执行命令并等待结束，捕获输出
        rc = bridge.shell(args.rest)
        sys.exit(rc if rc else 0)
        return

    if action == "logs":
        rc = bridge.logs(pid=args.pid, tag=args.tag)
        sys.exit(rc if rc else 0)
        return

    if action == "shell":
        if not args.rest:
            err("用法: device shell -- <cmd> [args...]")
            sys.exit(1)
        # 交互式 shell，继承 stdio，支持实时交互与持续输出
        rc = bridge.shell(args.rest, interactive=True)
        sys.exit(rc if rc else 0)
        return


# ===================== 参数解析 =====================
def build_parser():
    parser = argparse.ArgumentParser(
        description="远程部署调试客户端",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--server", "-s",
        default=default_server(),
        help=f"服务端地址，默认 {default_server()} 或环境变量 REMOTE_DEBUG_SERVER",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("info", help="查看服务端信息").set_defaults(func=cmd_info)

    p_deploy = sub.add_parser("deploy", help="部署文件/目录")
    p_deploy.add_argument("local", help="本地文件或目录路径")
    p_deploy.add_argument("remote", nargs="?", default="", help="部署目录下的相对子路径")
    p_deploy.add_argument(
        "--exec", action="append", default=[],
        help='标记可执行权限(非 Windows chmod +x)。可多次指定相对路径，或用 "*" 表示全部',
    )
    p_deploy.set_defaults(func=cmd_deploy)

    p_run = sub.add_parser("run", help="启动进程")
    p_run.add_argument("--cwd", default=None, help="工作目录（服务端路径）")
    p_run.add_argument("--name", default="", help="进程别名")
    p_run.add_argument("--shell", action="store_true", help="通过 shell 执行（命令合并为字符串）")
    p_run.add_argument("command", nargs=argparse.REMAINDER, help="要执行的命令及其参数")
    p_run.set_defaults(func=cmd_run)

    sub.add_parser("ps", help="列出进程").set_defaults(func=cmd_ps)

    p_stop = sub.add_parser("stop", help="停止进程")
    p_stop.add_argument("process_id")
    p_stop.set_defaults(func=cmd_stop)

    p_rm = sub.add_parser("rm", help="停止并从列表删除进程")
    p_rm.add_argument("process_id")
    p_rm.set_defaults(func=cmd_rm)

    p_cat = sub.add_parser("cat", help="查看历史日志")
    p_cat.add_argument("process_id")
    p_cat.set_defaults(func=cmd_cat)

    p_logs = sub.add_parser("logs", help="实时查看日志")
    p_logs.add_argument("process_id")
    p_logs.set_defaults(func=cmd_logs)

    p_files = sub.add_parser("files", help="文件列表/删除")
    p_files.add_argument("action", choices=["ls", "rm"])
    p_files.add_argument("path", nargs="?", default="")
    p_files.set_defaults(func=cmd_files)

    # ---- 设备桥接（Android/鸿蒙，走 adb/hdc，不依赖 server）----
    p_dev = sub.add_parser(
        "device",
        help="Android/鸿蒙设备桥接（adb/hdc，不走 HTTP 服务）",
    )
    p_dev.add_argument(
        "--tool", choices=["adb", "hdc"], default="",
        help="指定工具，默认自动探测（先 hdc 后 adb）",
    )
    p_dev.add_argument(
        "--device", "-d", default="",
        help="设备序列号，多设备时指定",
    )
    p_dev.add_argument(
        "action",
        choices=["list", "info", "push", "run", "logs", "shell"],
        help="list 列设备 | info 工具信息 | push 推送 | run 运行 | logs 日志 | shell 交互",
    )
    p_dev.add_argument(
        "--pid", default="", help="logs 时按进程号过滤（仅 adb）"
    )
    p_dev.add_argument(
        "--tag", default="", help="logs 时按 tag 过滤"
    )
    p_dev.add_argument(
        "rest", nargs=argparse.REMAINDER,
        help="各 action 的参数（push: <local> <remote>；run/shell: -- <cmd> ...）",
    )
    p_dev.set_defaults(func=cmd_device)

    return parser


def main():
    args = build_parser().parse_args()
    # device 子命令走 adb/hdc，不依赖 HTTP 服务端，单独处理
    if getattr(args, "func", None) is cmd_device:
        try:
            args.func(args)
        except KeyboardInterrupt:
            print("\n[已退出]")
        except FileNotFoundError as e:
            err(str(e))
            sys.exit(1)
        return

    args.server = normalize(args.server)
    try:
        args.func(args)
    except requests.exceptions.ConnectionError:
        err(f"无法连接服务端: {args.server}")
        sys.exit(1)
    except requests.exceptions.RequestException as e:
        err(f"请求失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
