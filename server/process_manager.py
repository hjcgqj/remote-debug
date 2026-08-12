"""进程管理与实时日志流。

核心设计：
- 每个 ManagedProcess 持有一个 asyncio 子进程。
- 一个读取协程按块读取 stdout/stderr，实时推送给所有订阅者。
- 订阅者模型（pub-sub）：每个 WebSocket 连接对应一个 asyncio.Queue。
- 历史日志用环形缓冲保存，新连接可补看历史。
- 历史写入与订阅注册在同一把锁内完成，保证“历史 + 实时”无缝衔接，不丢不重。

说明：编译产物（C/C++ 等）若使用全缓冲，管道下可能不实时刷新输出，
需程序自身 fflush 或以无缓冲模式运行；本服务已按块实时透传，不做额外缓存。
"""
import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from config import config


class ProcessStatus(str, Enum):
    STARTING = "starting"
    RUNNING = "running"
    EXITED = "exited"      # 自然退出
    STOPPED = "stopped"    # 被主动停止
    FAILED = "failed"      # 启动失败


@dataclass
class ManagedProcess:
    process_id: str
    command: list
    name: str
    pid: Optional[int]
    status: ProcessStatus
    start_time: float
    end_time: Optional[float] = None
    return_code: Optional[int] = None
    proc: Optional[asyncio.subprocess.Process] = None
    history: deque = field(default_factory=deque)
    subscribers: list = field(default_factory=list)  # list[asyncio.Queue]
    reader_task: Optional[asyncio.Task] = None
    waiter_task: Optional[asyncio.Task] = None
    stopping: bool = False  # 标记是否为主动停止，供 waiter 区分状态

    def history_snapshot(self) -> list:
        return list(self.history)


class ProcessManager:
    def __init__(self, history_size: int = None):
        self._processes: dict[str, ManagedProcess] = {}
        self._lock = asyncio.Lock()
        self._history_size = history_size or config.history_size

    # ---------- 生命周期 ----------
    async def start(
        self,
        command: list,
        cwd: Optional[str] = None,
        name: str = "",
        shell: bool = False,
    ) -> ManagedProcess:
        process_id = uuid.uuid4().hex[:12]
        # 预先创建 history，容量受限
        mp = ManagedProcess(
            process_id=process_id,
            command=command,
            name=name,
            pid=None,
            status=ProcessStatus.STARTING,
            start_time=time.time(),
            history=deque(maxlen=self._history_size),
        )
        async with self._lock:
            self._processes[process_id] = mp

        try:
            if shell:
                cmd_str = command if isinstance(command, str) else " ".join(command)
                proc = await asyncio.create_subprocess_shell(
                    cmd_str,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
                )
            else:
                proc = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=cwd,
                )
            mp.proc = proc
            mp.pid = proc.pid
            mp.status = ProcessStatus.RUNNING
            mp.reader_task = asyncio.create_task(self._reader(mp))
            mp.waiter_task = asyncio.create_task(self._waiter(mp))
        except Exception as e:
            mp.status = ProcessStatus.FAILED
            mp.return_code = -1
            mp.end_time = time.time()
            await self._emit(mp, f"[启动失败] {e}\n")
        return mp

    async def stop(self, process_id: str) -> Optional[ManagedProcess]:
        mp = self._processes.get(process_id)
        if not mp:
            return None
        if mp.proc and mp.proc.returncode is None:
            mp.stopping = True
            try:
                mp.proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(mp.proc.wait(), timeout=config.stop_timeout)
            except asyncio.TimeoutError:
                try:
                    mp.proc.kill()
                except ProcessLookupError:
                    pass
        return mp

    async def remove(self, process_id: str) -> Optional[ManagedProcess]:
        mp = self._processes.get(process_id)
        if not mp:
            return None
        await self.stop(process_id)
        # 取消后台任务
        for t in (mp.reader_task, mp.waiter_task):
            if t and not t.done():
                t.cancel()
        async with self._lock:
            self._processes.pop(process_id, None)
            # 清空订阅者
            for q in mp.subscribers:
                q.put_nowait({"type": "removed"})
        return mp

    # ---------- 输出读取与事件 ----------
    async def _reader(self, mp: ManagedProcess):
        proc = mp.proc
        try:
            while True:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                await self._emit(mp, text)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._emit(mp, f"\n[读取输出错误] {e}\n")

    async def _waiter(self, mp: ManagedProcess):
        try:
            rc = await mp.proc.wait()
        except asyncio.CancelledError:
            return
        mp.return_code = rc
        mp.end_time = time.time()
        mp.status = ProcessStatus.STOPPED if mp.stopping else ProcessStatus.EXITED
        await self._emit(mp, f"[进程结束] 返回码={rc}\n")
        await self._emit_event(mp, {"type": "exit", "return_code": rc, "status": mp.status.value})

    # ---------- pub-sub ----------
    async def _emit(self, mp: ManagedProcess, text: str):
        """写历史 + 广播日志，与 subscribe 共用同一把锁，保证不丢不重。"""
        async with self._lock:
            mp.history.append(text)
            msg = {"type": "log", "data": text}
            for q in mp.subscribers:
                q.put_nowait(msg)

    async def _emit_event(self, mp: ManagedProcess, event: dict):
        async with self._lock:
            for q in mp.subscribers:
                q.put_nowait(event)

    async def subscribe(self, mp: ManagedProcess):
        """注册一个订阅队列，并返回当前历史快照。

        关键：加入订阅列表 与 截取历史快照 在同一锁内完成，
        因此快照之前的日志只出现在 history，之后只出现在 queue，无重叠无遗漏。
        """
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            mp.subscribers.append(q)
            snapshot = list(mp.history)
        return q, snapshot

    def unsubscribe(self, mp: ManagedProcess, q: asyncio.Queue):
        if q in mp.subscribers:
            mp.subscribers.remove(q)

    # ---------- 查询 ----------
    def get(self, process_id: str) -> Optional[ManagedProcess]:
        return self._processes.get(process_id)

    def list_processes(self) -> list:
        return list(self._processes.values())

    @staticmethod
    def to_dict(mp: ManagedProcess) -> dict:
        return {
            "process_id": mp.process_id,
            "pid": mp.pid,
            "name": mp.name,
            "command": mp.command,
            "status": mp.status.value,
            "start_time": mp.start_time,
            "end_time": mp.end_time,
            "return_code": mp.return_code,
        }
