"""服务端配置。

所有参数均可通过环境变量覆盖，方便不同部署环境使用。
"""
import os
from pathlib import Path


class Config:
    # 监听地址：0.0.0.0 表示接受任意网卡（远程可访问）
    host: str = os.getenv("REMOTE_DEBUG_HOST", "0.0.0.0")
    # 监听端口
    port: int = int(os.getenv("REMOTE_DEBUG_PORT", "9721"))
    # 部署根目录：上传的文件与解压内容都放在这里
    deploy_root: str = os.getenv(
        "REMOTE_DEBUG_ROOT",
        str(Path(__file__).resolve().parent.parent / "deploy"),
    )
    # 单个进程历史日志缓冲行/块数（环形缓冲，避免内存爆炸）
    history_size: int = int(os.getenv("REMOTE_DEBUG_HISTORY", "8192"))
    # 停止进程时的优雅退出等待秒数，超时则强制 kill
    stop_timeout: float = float(os.getenv("REMOTE_DEBUG_STOP_TIMEOUT", "5"))


config = Config()
