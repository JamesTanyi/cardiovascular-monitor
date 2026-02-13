from datetime import datetime


def load_bp_csv(path, year=None):
    """
    自动识别三种格式：
    C: 中文表头格式（日期,时间,收缩压,舒张压,脉压差,心率,备注）
    A: 12月31日,22:10,128,81,47,58,
    B: datetime,sbp,dbp,hr + 2025-01-01 06:30,148,92,78
    """

    records = []

    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parts = [x.strip() for x in line.split(",")]

        # -------------------------
        # 跳过中文表头
        # -------------------------
        if parts[0] in ["日期", "datetime"]:
            continue

        # -------------------------
        # 格式 B：标准格式
        # -------------------------
        if len(parts) == 4 and "-" in parts[0]:
            # 例如：2025-01-01 06:30,148,92,78
            dt = datetime.strptime(parts[0], "%Y-%m-%d %H:%M")
            sbp = int(parts[1])
            dbp = int(parts[2])
            hr = int(parts[3])

            records.append({
                "datetime": dt,
                "sbp": sbp,
                "dbp": dbp,
                "pp": sbp - dbp,
                "hr": hr,
            })
            continue

        # -------------------------
        # 格式 C / A：中文日期格式
        # 例如：
        # 12月31日,22:10,128,81,47,58,
        # -------------------------
        if "月" in parts[0] and "日" in parts[0]:
            if year is None:
                raise ValueError("中文日期格式需要提供 year 参数")

            # 解析日期
            date_str = f"{year}-{parts[0]}"
            dt_date = datetime.strptime(date_str, "%Y-%m月%d日")

            # 解析时间
            time_str = parts[1]
            dt = datetime.strptime(f"{dt_date.date()} {time_str}", "%Y-%m-%d %H:%M")

            sbp = int(parts[2])
            dbp = int(parts[3])
            hr = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else int(parts[4])

            records.append({
                "datetime": dt,
                "sbp": sbp,
                "dbp": dbp,
                "pp": sbp - dbp,
                "hr": hr,
            })
            continue

        # -------------------------
        # 无法识别
        # -------------------------
        raise ValueError(f"无法识别的 CSV 行格式: {line}")

    return records

def normalize_and_sort(records):
    """
    接收一条或多条记录（dict），确保 timestamp 是 datetime，
    并按时间排序，返回新的 list。
    """
    normalized = []

    for r in records:
        ts = r.get("timestamp")

        # 如果 timestamp 是字符串，转成 datetime
        if isinstance(ts, str):
            # 兼容 ISO 格式与无 Z 的格式
            if "Z" in ts:
                ts = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            else:
                ts = datetime.fromisoformat(ts)

        normalized.append({
            "timestamp": ts,
            "sbp": float(r["sbp"]),
            "dbp": float(r["dbp"]),
            "hr": float(r["hr"]) if r.get("hr") is not None else None
        })

    # 按时间排序
    normalized.sort(key=lambda x: x["timestamp"])
    return normalized

def debug_dump(records, n=5):
    for r in records[:n]:
        print(r)

from datetime import datetime

class BPRecord:
    """
    标准化后的血压记录对象，供 temporal_context 使用。
    """
    def __init__(self, timestamp, sbp, dbp, pp, hr, symptoms=None):
        self.timestamp = timestamp
        self.sbp = sbp
        self.dbp = dbp
        self.pp = pp
        self.hr = hr
        self.symptoms = symptoms or []

    def to_dict(self):
        return {
            "timestamp": self.timestamp.isoformat(),
            "sbp": self.sbp,
            "dbp": self.dbp,
            "pp": self.pp,
            "hr": self.hr,
            "symptoms": self.symptoms,
        }

    @classmethod
    def from_dict(cls, d):
        from datetime import datetime

        # --- 修复 timestamp ---
        ts = d.get("timestamp")
        if not ts or ts in ("None", "null", "", None):
            ts = datetime.now().isoformat()

        try:
            timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            timestamp = datetime.now()

        sbp = d.get("sbp")
        dbp = d.get("dbp")
        pp = d.get("pp", sbp - dbp if sbp is not None and dbp is not None else None)
        hr = d.get("hr")
        symptoms = d.get("symptoms", [])

        return cls(
            timestamp=timestamp,
            sbp=sbp,
            dbp=dbp,
            pp=pp,
            hr=hr,
            symptoms=symptoms
        )


def build_single_record_from_payload(payload: dict) -> BPRecord:
    try:
        ts = payload.get("timestamp")

        # 统一处理 timestamp → datetime
        if isinstance(ts, str):
            try:
                timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                timestamp = datetime.fromisoformat(ts)
        else:
            timestamp = ts

        sbp = int(payload["sbp"])
        dbp = int(payload["dbp"])
        pp = payload.get("pp", sbp - dbp)
        hr = payload.get("hr", None)
        symptoms = payload.get("symptoms") or payload.get("events") or []

        return BPRecord(
            timestamp=timestamp,
            sbp=sbp,
            dbp=dbp,
            pp=pp,
            hr=hr,
            symptoms=symptoms
        )

    except Exception as e:
        import traceback
        print("❌ ERROR in build_single_record_from_payload")
        print("payload =", payload)
        traceback.print_exc()
        raise
