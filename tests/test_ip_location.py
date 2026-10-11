from unittest import TestCase
from unittest.mock import patch

from server import ip_location


class IPLocationTest(TestCase):
    def testLooksUpProvinceAndCityFromTheBundledDatabase(self):
        for ip, location in (
            ("114.114.114.114", "江苏 南京"),
            ("223.5.5.5", "浙江 杭州"),
            ("116.204.135.225", "香港"),
            ("8.8.8.8", "United States"),
        ):
            with self.subTest(ip=ip):
                self.assertEqual(ip_location.ipLocation(ip), location)

    def testUnknownAddressesHaveNoLocation(self):
        for ip in ("192.168.1.1", "127.0.0.1", "0.0.0.0", "::1", "2001:db8::1", "bad", "", None):
            with self.subTest(ip=ip):
                self.assertEqual(ip_location.ipLocation(ip), "")

    def testRegionNamesAreShortenedLikeSocialPlatforms(self):
        for region, location in (
            ("中国|江苏省|宿迁市|电信|CN", "江苏 宿迁"),
            ("中国|北京市|北京市|联通|CN", "北京"),
            ("中国|广西壮族自治区|南宁市|电信|CN", "广西 南宁"),
            ("中国|新疆维吾尔自治区|0|0|CN", "新疆"),
            ("中国|澳门特别行政区|0|0|CN", "澳门"),
            ("中国|0|0|0|CN", "中国"),
            ("Japan|Tokyo|0|0|JP", "Japan"),
            ("Reserved|Reserved|Reserved|0|0", ""),
            ("0|0|0|0|0", ""),
            ("", ""),
        ):
            with self.subTest(region=region):
                self.assertEqual(ip_location.formatRegion(region), location)

    def testADamagedDatabaseOnlyMakesTheLocationUnknown(self):
        ip_location.ipLocation.cache_clear()
        self.addCleanup(ip_location.ipLocation.cache_clear)
        with patch.object(ip_location, "_content", return_value=b"\x03" * 300):
            self.assertEqual(ip_location.ipLocation("114.114.114.114"), "")
