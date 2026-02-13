"""
存储抽象层：本地文件 或 Google Cloud Storage。
未设置 GCS_BUCKET 时使用本地 data/ 目录；设置后使用 GCS，便于 Cloud Run 长期运行。
"""
import os

# 项目根目录（与 server.py 一致）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR_NAME = "data"
LOCAL_DATA_DIR = os.path.join(ROOT_DIR, DATA_DIR_NAME)

_GCS_BUCKET = os.environ.get("GCS_BUCKET")
_gcs_client = None


def _get_gcs_client():
    global _gcs_client
    if _gcs_client is None:
        try:
            from google.cloud import storage
        except ImportError:
            raise ImportError(
                "使用 GCS 存储需安装: pip install google-cloud-storage （或 pip install -r requirements-cloud.txt）"
            )
        _gcs_client = storage.Client()
    return _gcs_client


def _gcs_path(relative_path: str) -> str:
    """GCS 内使用 data/ 前缀，与本地目录结构一致。"""
    return f"{DATA_DIR_NAME}/{relative_path}".replace("\\", "/")


def read_file_content(relative_path: str) -> str:
    """读取文件全部内容；不存在时返回空字符串。"""
    if not _GCS_BUCKET:
        path = os.path.join(ROOT_DIR, DATA_DIR_NAME, relative_path)
        if not os.path.exists(path):
            return ""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    client = _get_gcs_client()
    bucket = client.bucket(_GCS_BUCKET)
    blob = bucket.blob(_gcs_path(relative_path))
    if not blob.exists():
        return ""
    return blob.download_as_text(encoding="utf-8")


def append_line(relative_path: str, line: str):
    """在文件末尾追加一行（含换行）。"""
    content = read_file_content(relative_path)
    new_content = content + line if content.endswith("\n") or not content else content + "\n" + line
    if not new_content.endswith("\n"):
        new_content = new_content + "\n"
    write_file_content(relative_path, new_content)


def write_file_content(relative_path: str, content: str):
    """覆盖写入文件内容。"""
    if not _GCS_BUCKET:
        path = os.path.join(ROOT_DIR, DATA_DIR_NAME, relative_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return

    client = _get_gcs_client()
    bucket = client.bucket(_GCS_BUCKET)
    blob = bucket.blob(_gcs_path(relative_path))
    blob.upload_from_string(content, content_type="text/plain; charset=utf-8")


def ensure_data_dir():
    """本地模式下确保 data 目录存在；GCS 模式无操作。"""
    if not _GCS_BUCKET:
        os.makedirs(LOCAL_DATA_DIR, exist_ok=True)


def is_gcs_mode() -> bool:
    return bool(_GCS_BUCKET)

import json
from app.ingest.bp_loader import BPRecord


def _history_path(patient_id: str) -> str:
    """历史记录文件路径：data/history/{patient_id}.jsonl"""
    return os.path.join("history", f"{patient_id}.jsonl")


def save_history_record(patient_id: str, record: BPRecord):
    """追加一条 BPRecord 到历史文件"""
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    append_line(_history_path(patient_id), line)

def load_history(patient_id: str):
    """加载历史记录，返回 BPRecord 列表（自动修复缺失 timestamp）"""
    content = read_file_content(_history_path(patient_id))
    if not content.strip():
        return []

    records = []
    for line in content.splitlines():
        try:
            d = json.loads(line)

            # 自动修复缺失 timestamp
            if "timestamp" not in d or d["timestamp"] in (None, "", "null"):
                # 用当前时间补齐
                from datetime import datetime
                d["timestamp"] = datetime.now().isoformat()

            records.append(BPRecord.from_dict(d))
        except Exception:
            continue

    return records
import json
from datetime import datetime
from app.ingest.bp_loader import BPRecord, build_single_record_from_payload


def _history_path(patient_id: str) -> str:
    """历史记录文件路径：data/history/{patient_id}.jsonl"""
    return os.path.join("history", f"{patient_id}.jsonl")


def save_history_record(patient_id: str, record: BPRecord):
    """追加一条 BPRecord 到历史文件"""
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    append_line(_history_path(patient_id), line)


def load_history(patient_id: str):
    """加载历史记录，返回 BPRecord 列表（自动修复 timestamp）"""
    content = read_file_content(_history_path(patient_id))
    if not content.strip():
        return []

    records = []
    for line in content.splitlines():
        try:
            d = json.loads(line)

            # 自动修复 timestamp
            ts = d.get("timestamp")
            if not ts or ts in ("None", "null", "", None):
                ts = datetime.now().isoformat()
            d["timestamp"] = ts

            records.append(BPRecord.from_dict(d))
        except Exception:
            continue

    return records


def load_history_for_patient(patient_id: str):
    return load_history(patient_id)


def save_raw_measurement(payload: dict):
    patient_id = payload.get("patient_id", "test_user")
    record = build_single_record_from_payload(payload)
    save_history_record(patient_id, record)

def clear_history_for_patient(patient_id: str):
    """清空指定患者的历史记录（用于测试重置）"""
    if _GCS_BUCKET:
        return # GCS 模式暂不实现删除，防止误操作
    
    path = os.path.join(ROOT_DIR, DATA_DIR_NAME, _history_path(patient_id))
    if os.path.exists(path):
        os.remove(path)
