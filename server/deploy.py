"""文件部署模块。

负责接收本机编译产物并落地到远程目标机器：
- 单文件上传
- 多文件上传
- zip 包上传后自动解压（用于一次性部署整个构建输出目录）

所有写入路径都会做边界检查，防止路径穿越越界写到部署根目录之外。

跨平台注意事项：
- 上传采用分块流式写入（每块 1MB），避免大文件一次性读入内存爆掉。
- Linux/Mac 下可执行文件需要 +x 权限，保存后可按 exec_all / exec_paths
  自动 chmod 0755；Windows 下无此概念，跳过。
"""
import os
import shutil
import zipfile
from pathlib import Path

# 流式写入块大小
CHUNK_SIZE = 1024 * 1024  # 1MB


class DeployManager:
    def __init__(self, deploy_root: str):
        self.deploy_root = Path(deploy_root).resolve()
        self.deploy_root.mkdir(parents=True, exist_ok=True)

    # ---------- 路径安全 ----------
    def _safe(self, relative_path: str) -> Path:
        """把相对路径解析为部署根目录内的绝对路径，越界则抛错。"""
        target = (self.deploy_root / relative_path).resolve()
        # Windows 下比较需要统一大小写并确保是 deploy_root 的子目录
        try:
            target.relative_to(self.deploy_root)
        except ValueError:
            raise ValueError(f"非法路径，超出部署根目录: {relative_path}")
        return target

    # ---------- 保存上传 ----------
    async def save_upload(
        self,
        file,
        relative_path: str = "",
        extract_zip: bool = False,
        exec_all: bool = False,
        exec_paths: list = None,
    ) -> list:
        """流式保存上传文件。

        file: FastAPI UploadFile（支持 await file.read(n) 分块读取）。
        exec_all=True 时对本次落地的所有文件 chmod +x（仅非 Windows）。
        exec_paths 为相对 target_dir 的路径列表，仅对这些文件赋权。
        """
        exec_paths = exec_paths or []
        target_dir = self._safe(relative_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / Path(file.filename).name

        # 分块流式写入磁盘，避免大文件撑爆内存
        with open(target_path, "wb") as f:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                f.write(chunk)

        saved = [str(target_path)]

        # zip 自动解压后删除原包，返回解压出的所有文件
        if extract_zip and target_path.suffix.lower() == ".zip":
            with zipfile.ZipFile(target_path) as z:
                # 解压前校验每个成员路径，防止 zip slip
                for member in z.namelist():
                    member_path = (target_dir / member).resolve()
                    try:
                        member_path.relative_to(target_dir)
                    except ValueError:
                        raise ValueError(f"zip 内含非法路径: {member}")
                z.extractall(target_dir)
            os.remove(target_path)
            saved = [str(p) for p in target_dir.rglob("*") if p.is_file()]

        # 非 Windows 下按需赋予可执行权限
        self._apply_exec(target_dir, saved, exec_all, exec_paths)

        return saved

    def _apply_exec(self, target_dir: Path, saved: list, exec_all: bool, exec_paths: list):
        """对落地文件赋予 +x 权限。Windows 直接跳过。"""
        if os.name == "nt":
            return
        targets = []
        if exec_all:
            targets = [Path(p) for p in saved]
        elif exec_paths:
            for p in exec_paths:
                tp = (target_dir / p).resolve()
                try:
                    tp.relative_to(target_dir)
                except ValueError:
                    continue  # 越界路径忽略
                targets.append(tp)
        else:
            return
        for t in targets:
            try:
                if t.is_file():
                    t.chmod(0o755)
            except OSError:
                pass

    # ---------- 文件列表 ----------
    def list_files(self, relative_path: str = "") -> list:
        base = self._safe(relative_path)
        if not base.exists():
            return []
        if base.is_file():
            return [{"path": str(base), "size": base.stat().st_size}]
        result = []
        for p in sorted(base.rglob("*")):
            if p.is_file():
                result.append(
                    {
                        "path": str(p),
                        "rel": str(p.relative_to(self.deploy_root)),
                        "size": p.stat().st_size,
                    }
                )
        return result

    # ---------- 删除 ----------
    def delete(self, relative_path: str = "") -> None:
        if relative_path in ("", ".", "/"):
            # 保护：禁止直接删除整个部署根目录
            raise ValueError("禁止删除部署根目录，请指定具体子路径")
        target = self._safe(relative_path)
        if not target.exists():
            return
        if target.is_file():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)
