import hashlib
import uuid

import requests
from PySide6.QtCore import QSysInfo

from app.config.constants import AI_MARKDOWN_API


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
        return int(quota["remaining"]), int(quota["limit"])
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None
