"""远程部署与调试服务端。

提供 HTTP 接口用于：
- 上传/部署编译产物
- 启动/停止/查询进程
- 查询历史日志

提供 WebSocket 接口用于：
- 实时推送进程 stdout/stderr

启动：python main.py
依赖：见 requirements.txt
"""
import os
import platform
import json
from typing import List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from pydantic import BaseModel

from config import config
from deploy import DeployManager
from process_manager import ProcessManager, ProcessStatus

app = FastAPI(title="Remote Deploy & Debug Service", version="1.0.0")
deploy_mgr = DeployManager(config.deploy_root)
pm = ProcessManager()


# ===================== 基础信息 =====================
@app.get("/api/info")
async def info():
    return {
        "service": "remote-deploy-debug",
        "version": "1.0.0",
        "platform": platform.platform(),
        "system": platform.system(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "deploy_root": str(deploy_mgr.deploy_root),
        "process_count": len(pm.list_processes()),
    }


# ===================== 文件部署 =====================
@app.post("/api/deploy")
async def deploy(
    files: List[UploadFile] = File(...),
    path: str = Form(""),
    extract_zip: bool = Form(False),
    exec_all: bool = Form(False),
    exec_paths: str = Form(""),
):
    """上传文件到部署目录。

    - files: 一个或多个文件
    - path: 部署目录下的相对子路径（不存在会自动创建）
    - extract_zip: 为 True 时，.zip 文件会自动解压并删除原包
    - exec_all: 为 True 时，本次落地的所有文件在非 Windows 上 chmod +x
    - exec_paths: JSON 数组字符串，指定相对 path 的文件路径列表，仅对这些赋权
    """
    if not files:
        raise HTTPException(400, "未提供文件")
    # 解析 exec_paths（JSON 数组）
    paths_list = []
    if exec_paths:
        try:
            paths_list = json.loads(exec_paths)
            if not isinstance(paths_list, list):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(400, "exec_paths 不是合法的 JSON 数组")
    saved = []
    try:
        for f in files:
            saved.extend(
                await deploy_mgr.save_upload(
                    f, path, extract_zip, exec_all, paths_list
                )
            )
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"saved": saved, "deploy_root": str(deploy_mgr.deploy_root)}


@app.get("/api/files")
async def list_files(path: str = ""):
    try:
        return {"files": deploy_mgr.list_files(path)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/files")
async def delete_files(path: str = ""):
    try:
        deploy_mgr.delete(path)
        return {"deleted": True, "path": path}
    except ValueError as e:
        raise HTTPException(400, str(e))


# ===================== 进程控制 =====================
class StartRequest(BaseModel):
    command: List[str]
    cwd: Optional[str] = None
    name: str = ""
    shell: bool = False


@app.post("/api/process/start")
async def start_process(req: StartRequest):
    if not req.command:
        raise HTTPException(400, "command 不能为空")
    if req.cwd and not os.path.exists(req.cwd):
        raise HTTPException(400, f"工作目录不存在: {req.cwd}")
    mp = await pm.start(
        req.command, cwd=req.cwd, name=req.name, shell=req.shell
    )
    return ProcessManager.to_dict(mp)


@app.get("/api/process")
async def list_processes():
    return {"processes": [ProcessManager.to_dict(m) for m in pm.list_processes()]}


@app.get("/api/process/{process_id}")
async def get_process(process_id: str):
    mp = pm.get(process_id)
    if not mp:
        raise HTTPException(404, "进程不存在")
    return ProcessManager.to_dict(mp)


@app.post("/api/process/{process_id}/stop")
async def stop_process(process_id: str):
    mp = await pm.stop(process_id)
    if not mp:
        raise HTTPException(404, "进程不存在")
    return ProcessManager.to_dict(mp)


@app.delete("/api/process/{process_id}")
async def delete_process(process_id: str):
    mp = await pm.remove(process_id)
    if not mp:
        raise HTTPException(404, "进程不存在")
    return {"process_id": process_id, "removed": True}


@app.get("/api/process/{process_id}/logs")
async def get_logs(process_id: str):
    mp = pm.get(process_id)
    if not mp:
        raise HTTPException(404, "进程不存在")
    return {"logs": mp.history_snapshot(), "status": mp.status.value}


# ===================== 实时日志 WebSocket =====================
@app.websocket("/ws/logs/{process_id}")
async def ws_logs(ws: WebSocket, process_id: str):
    mp = pm.get(process_id)
    if not mp:
        await ws.accept()
        await ws.close(code=1008, reason="进程不存在")
        return

    await ws.accept()
    q, snapshot = await pm.subscribe(mp)
    try:
        # 1) 先补看历史日志
        await ws.send_json({"type": "history", "data": "".join(snapshot)})
        # 2) 若进程已结束，补发退出事件
        if mp.status in (ProcessStatus.EXITED, ProcessStatus.STOPPED, ProcessStatus.FAILED):
            await ws.send_json(
                {
                    "type": "exit",
                    "return_code": mp.return_code,
                    "status": mp.status.value,
                }
            )
        # 3) 实时转发
        while True:
            msg = await q.get()
            await ws.send_json(msg)
            if msg.get("type") in ("exit", "removed"):
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        pm.unsubscribe(mp, q)
        try:
            await ws.close()
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    print(f"远程部署调试服务启动中...")
    print(f"  监听: http://{config.host}:{config.port}")
    print(f"  部署根目录: {deploy_mgr.deploy_root}")
    print(f"  平台: {platform.platform()}")
    print(f"  文档: http://{config.host}:{config.port}/docs")
    uvicorn.run(app, host=config.host, port=config.port)
