"""
backup_online_boutique_experiment.py

用途：
将 Online Boutique + ChaosMesh + Prometheus + SR / SR-CNN 复现实验相关文件
备份到 Online-Boutique/allBackUp/backup_YYYYmmdd_HHMMSS 目录。

默认会备份：
1. python 源代码目录中的 .py 文件，但跳过 .venv、__pycache__。
2. chaos-yamls 目录，包括 YAML、PowerShell 脚本、fault_windows.csv。
3. Prometheus 导出的 CSV 数据目录。
4. SR 输出目录 sr-output。
5. SR-CNN 数据集目录 sr-cnn-dataset。
6. SR-CNN 输出目录 sr-cnn-output。
7. 根目录下常见的导出脚本和说明文件。
8. 生成 backup_manifest.json，记录备份文件、大小和 SHA256。
9. 默认额外打包一个 zip，方便提交或转移。

推荐放置位置：
E:\\0AI\\Online-Boutique\\python\\backup_online_boutique_experiment.py

运行方式：
cd E:\\0AI\\Online-Boutique
python .\\python\\backup_online_boutique_experiment.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path


EXCLUDE_DIR_NAMES = {
    ".venv",
    "venv",
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    "node_modules",
}

EXCLUDE_FILE_SUFFIXES = {
    ".pyc",
    ".pyo",
    ".tmp",
    ".log",
}

DIRS_TO_BACKUP = [
    "chaos-yamls",
    "prometheus-online-boutique-pod-data",
    "prometheus-container-data",
    "prometheus-data-node",
    "prometheus-data",
    "sr-output",
    "sr-cnn-dataset",
    "sr-cnn-output",
]

PYTHON_DIR_NAME = "python"

ROOT_FILE_PATTERNS = [
    "*.ps1",
    "*.yaml",
    "*.yml",
    "*.md",
    "*.txt",
    "*.json",
]


def guess_project_dir() -> Path:
    script_path = Path(__file__).resolve()
    if script_path.parent.name.lower() == PYTHON_DIR_NAME:
        return script_path.parent.parent
    return Path.cwd().resolve()


def should_skip_file(path: Path) -> bool:
    return path.suffix.lower() in EXCLUDE_FILE_SUFFIXES


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def make_manifest_record(src: Path, dst: Path) -> dict:
    try:
        size = src.stat().st_size
    except OSError:
        size = None

    try:
        digest = sha256_file(src)
    except OSError:
        digest = None

    return {
        "source": str(src),
        "backup_path": str(dst),
        "size_bytes": size,
        "sha256": digest,
    }


def copy_tree_filtered(src: Path, dst: Path, manifest: list[dict]) -> None:
    if not src.exists():
        return

    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]

        for filename in files:
            src_file = root_path / filename
            if should_skip_file(src_file):
                continue

            rel = src_file.relative_to(src)
            dst_file = dst / rel
            safe_copy_file(src_file, dst_file)
            manifest.append(make_manifest_record(src_file, dst_file))


def backup_python_sources(project_dir: Path, backup_dir: Path, manifest: list[dict]) -> None:
    src = project_dir / PYTHON_DIR_NAME
    if not src.exists():
        return

    dst = backup_dir / PYTHON_DIR_NAME

    allowed_suffixes = {
        ".py", ".ipynb", ".md", ".txt", ".json", ".yaml", ".yml", ".ps1"
    }

    for root, dirs, files in os.walk(src):
        root_path = Path(root)
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES]

        for filename in files:
            src_file = root_path / filename
            if src_file.suffix.lower() not in allowed_suffixes:
                continue

            rel = src_file.relative_to(src)
            dst_file = dst / rel
            safe_copy_file(src_file, dst_file)
            manifest.append(make_manifest_record(src_file, dst_file))


def backup_root_files(project_dir: Path, backup_dir: Path, manifest: list[dict]) -> None:
    dst_root = backup_dir / "root_files"
    seen: set[Path] = set()

    for pattern in ROOT_FILE_PATTERNS:
        for src in project_dir.glob(pattern):
            if not src.is_file() or src in seen:
                continue
            seen.add(src)

            dst = dst_root / src.name
            safe_copy_file(src, dst)
            manifest.append(make_manifest_record(src, dst))


def write_environment_info(backup_dir: Path) -> None:
    info_dir = backup_dir / "environment"
    info_dir.mkdir(parents=True, exist_ok=True)

    (info_dir / "python_version.txt").write_text(sys.version, encoding="utf-8")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            check=False,
        )
        (info_dir / "pip_freeze.txt").write_text(result.stdout, encoding="utf-8")
        if result.stderr:
            (info_dir / "pip_freeze_stderr.txt").write_text(result.stderr, encoding="utf-8")
    except Exception as exc:
        (info_dir / "pip_freeze_error.txt").write_text(str(exc), encoding="utf-8")

    commands = {
        "kubectl_get_pods_all.txt": ["kubectl", "get", "pods", "-A"],
        "kubectl_get_stresschaos.txt": ["kubectl", "get", "stresschaos", "-A"],
        "kubectl_get_networkchaos.txt": ["kubectl", "get", "networkchaos", "-A"],
        "kubectl_get_svc_all.txt": ["kubectl", "get", "svc", "-A"],
    }

    for filename, cmd in commands.items():
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            content = result.stdout
            if result.stderr:
                content += "\n\n--- STDERR ---\n" + result.stderr
            (info_dir / filename).write_text(content, encoding="utf-8")
        except Exception as exc:
            (info_dir / filename).write_text(f"Failed to run {cmd}: {exc}", encoding="utf-8")


def zip_directory(src_dir: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file in src_dir.rglob("*"):
            if file.is_file():
                zf.write(file, arcname=file.relative_to(src_dir.parent))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup Online Boutique SR/SR-CNN experiment files.")
    parser.add_argument(
        "--project-dir",
        type=str,
        default=None,
        help="Online-Boutique 项目根目录。默认自动判断。",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="只生成备份文件夹，不额外生成 zip。",
    )
    args = parser.parse_args()

    project_dir = Path(args.project_dir).resolve() if args.project_dir else guess_project_dir()

    if not project_dir.exists():
        raise FileNotFoundError(f"项目目录不存在：{project_dir}")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = project_dir / "allBackUp"
    backup_dir = backup_root / f"backup_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)

    manifest: list[dict] = []

    print(f"Project dir: {project_dir}")
    print(f"Backup dir : {backup_dir}")

    backup_python_sources(project_dir, backup_dir, manifest)

    for dirname in DIRS_TO_BACKUP:
        src = project_dir / dirname
        if src.exists():
            print(f"Copy dir: {src}")
            copy_tree_filtered(src, backup_dir / dirname, manifest)
        else:
            print(f"Skip missing dir: {src}")

    backup_root_files(project_dir, backup_dir, manifest)
    write_environment_info(backup_dir)

    manifest_data = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_dir": str(project_dir),
        "backup_dir": str(backup_dir),
        "file_count": len(manifest),
        "files": manifest,
    }
    manifest_path = backup_dir / "backup_manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, ensure_ascii=False, indent=2), encoding="utf-8")

    readme = f"""# Online Boutique SR/SR-CNN 实验备份

创建时间：{manifest_data["created_at"]}

项目目录：{project_dir}

备份目录：{backup_dir}

备份内容包括：
- python 源代码，不包含 .venv
- chaos-yamls 故障注入 YAML / PowerShell / fault_windows.csv
- Prometheus 导出的 CSV 数据
- SR 输出结果
- SR-CNN 数据集和训练输出
- kubectl 状态快照
- pip freeze 环境依赖记录
- backup_manifest.json 文件哈希清单

说明：
该备份用于课程大作业复现实验留档。
"""
    (backup_dir / "README_BACKUP.md").write_text(readme, encoding="utf-8")

    if not args.no_zip:
        zip_path = backup_root / f"backup_{timestamp}.zip"
        print(f"Creating zip: {zip_path}")
        zip_directory(backup_dir, zip_path)

    print("\nBackup finished.")
    print(f"Backup folder: {backup_dir}")
    if not args.no_zip:
        print(f"Zip file     : {zip_path}")
    print(f"Manifest     : {manifest_path}")


if __name__ == "__main__":
    main()
