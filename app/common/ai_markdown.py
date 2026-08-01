import hashlib
import uuid

import requests
from PySide6.QtCore import QSysInfo

from app.config.constants import AI_MARKDOWN_API

PEAK_HOURS_TEXT = "北京时间 9:00–12:00、14:00–18:00"


def machineId():
    raw = bytes(QSysInfo.machineUniqueId())
    if not raw:
        raw = uuid.getnode().to_bytes(6, "big")
    return hashlib.sha256(raw).hexdigest()


def fetchQuota():
    try:
        response = requests.get(
            f"{AI_MARKDOWN_API}/quota",
            params={"machine_id": machineId()},
            timeout=5,
        )
        response.raise_for_status()
        quota = response.json()
        return (
            int(quota["remaining"]),
            int(quota["limit"]),
            int(quota.get("cost", 1)),
        )
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None
