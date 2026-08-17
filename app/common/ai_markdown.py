import hashlib
import re
import uuid

import requests
from PySide6.QtCore import QSysInfo

from app.common.update_download import isHttpsResponseChain
from app.config.constants import AI_MARKDOWN_API

PEAK_HOURS_TEXT = "北京时间 9:00–12:00、14:00–18:00"


def machineId():
    raw = bytes(QSysInfo.machineUniqueId())
    if not raw:
        raw = uuid.getnode().to_bytes(6, "big")
    return hashlib.sha256(raw).hexdigest()


def registerMachine():
    response = None
    try:
        response = requests.post(
            f"{AI_MARKDOWN_API}/register",
            json={"machine_id": machineId()},
            timeout=5,
        )
        response.raise_for_status()
        if not isHttpsResponseChain(response, f"{AI_MARKDOWN_API}/register"):
            raise requests.RequestException("注册接口必须保持 HTTPS")
        machineCode = str(response.json()["machine_code"])
        return machineCode if re.fullmatch(r"DJ-\d{6,}", machineCode) else None
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None
    finally:
        if response is not None:
            response.close()


def fetchQuota():
    response = None
    try:
        response = requests.get(
            f"{AI_MARKDOWN_API}/quota",
            params={"machine_id": machineId()},
            timeout=5,
        )
        response.raise_for_status()
        if not isHttpsResponseChain(response, f"{AI_MARKDOWN_API}/quota"):
            raise requests.RequestException("额度接口必须保持 HTTPS")
        quota = response.json()
        machineCode = str(quota.get("machine_code", ""))
        return (
            int(quota["remaining"]),
            int(quota["limit"]),
            int(quota.get("cost", 1)),
            bool(quota.get("peak_enabled", True)),
            machineCode if re.fullmatch(r"DJ-\d{6,}", machineCode) else "",
        )
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return None
    finally:
        if response is not None:
            response.close()
