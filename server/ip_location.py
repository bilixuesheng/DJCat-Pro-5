"""IP Location：把来源 IP 换成「省 市」，只给 Last Seen 用。

数据来自 ip2region（https://github.com/lionsoul2014/ip2region，Apache-2.0 或 MIT，
许可证见 ip2region_LICENSE.md）的 IPv4 离线库 ip2region_v4.xdb，随服务端一起发布；
查询照它的官方 Python 绑定 py-ip2region 3.0.4 的 xdb 结构写，只取 IPv4。
api.djcatpro.top 没有 IPv6 地址，用不到 IPv6 库。更新数据就是换掉 xdb 文件并升 Server Version。
"""

import ipaddress
import struct
from functools import lru_cache
from pathlib import Path

DATABASE_PATH = Path(__file__).with_name("ip2region_v4.xdb")

_HEADER_LENGTH = 256
_VECTOR_INDEX_SIZE = 8
_SEGMENT_INDEX_SIZE = 14  # 起始 IP 4 + 结束 IP 4 + 数据长度 2 + 数据位置 4，均为小端
_PROVINCE_SUFFIXES = (
    "特别行政区",
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "省",
    "市",
)


@lru_cache(maxsize=1)
def _content():
    # 整个库约 11 MB，读进内存后查询不碰磁盘，多线程共用一份不可变的 bytes。
    try:
        return DATABASE_PATH.read_bytes()
    except OSError:
        return b""


def _region(ip):
    content = _content()
    try:
        address = ipaddress.ip_address(ip)
    except ValueError:
        return ""
    if address.version != 4 or len(content) < _HEADER_LENGTH:
        return ""
    packed = address.packed
    value = int.from_bytes(packed, "big")
    start, end = struct.unpack_from(
        "<II",
        content,
        _HEADER_LENGTH + (packed[0] * 256 + packed[1]) * _VECTOR_INDEX_SIZE,
    )
    low, high = 0, (end - start) // _SEGMENT_INDEX_SIZE
    while start and low <= high:
        middle = (low + high) // 2
        first, last, length, pointer = struct.unpack_from(
            "<IIHI", content, start + middle * _SEGMENT_INDEX_SIZE
        )
        if value < first:
            high = middle - 1
        elif value > last:
            low = middle + 1
        else:
            return content[pointer:pointer + length].decode("utf-8", "replace")
    return ""


def _shortName(name, suffixes):
    for suffix in suffixes:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def formatRegion(region):
    """ip2region 的「国家|省|市|运营商|代码」换成后台显示的属地，0 表示未知。"""
    country, province, city = (region.split("|") + ["", "", ""])[:3]
    if not country or country in {"0", "Reserved"}:
        return ""
    if country != "中国":
        return country
    names = []
    for name in (
        _shortName(province, _PROVINCE_SUFFIXES),
        _shortName(city, ("市",)),
    ):
        if name and name != "0" and name not in names:
            names.append(name)
    return " ".join(names) or country


@lru_cache(maxsize=4096)
def ipLocation(ip):
    """来源 IP 的属地，例如「江苏 南京」；内网、IPv6 或库里没有时返回空串。"""
    # 它在注册、查额度和整理的请求路径上：数据文件损坏也只能让属地变成未知，不能拖垮请求。
    try:
        return formatRegion(_region(ip or ""))
    except (struct.error, ValueError):
        return ""
