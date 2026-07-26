from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    ElevatedCardWidget,
    HyperlinkButton,
    SubtitleLabel,
    TitleLabel,
)
from qfluentwidgets import FluentIcon as FIF

from app.config.paths import ASSET_DIR
from app.view.components.scroll_area import ScrollArea


_GROUPS = (
    (
        "技术支持",
        (
            (
                "Ghost Downloader",
                "ghd.png",
                "很优秀的项目，奠定了本项目重构的基础，被参考了很多设计思路",
                (
                    (
                        "GitHub",
                        FIF.GITHUB,
                        "https://github.com/XiaoYouChR/Ghost-Downloader-3",
                    ),
                    ("官网", FIF.GLOBE, "https://gd.xychr.com"),
                ),
            ),
            (
                "晓游ChR",
                "chr.jpg",
                "Ghost Downloader 开发者",
                (
                    ("GitHub", FIF.GITHUB, "https://github.com/XiaoYouChR"),
                    ("bilibili", FIF.VIDEO, "https://space.bilibili.com/437313511"),
                ),
            ),
            (
                "ChatGPT CodeX",
                "codex.png",
                "OpenAI 公司打造的编程工具",
                (("官网", FIF.GLOBE, "https://openai.com/codex/"),),
            ),
            (
                "Claude Code",
                "claude.png",
                "ANTHROP\\C 公司打造的编程工具",
                (("官网", FIF.GLOBE, "https://claude.com/product/claude-code"),),
            ),
            (
                "Gemini",
                "gemini.png",
                "辅助参与了 电教猫 Pro 5 Beta Pre.11 以前的版本，"
                "并开发了 电教猫 Pro 4 及之前的官网",
                (("官网", FIF.GLOBE, "https://gemini.google.com/"),),
            ),
            (
                "DeepSeek",
                "deepseek.png",
                "辅助开发了 电教猫 Pro 4 及以前的版本",
                (("官网", FIF.GLOBE, "https://chat.deepseek.com/"),),
            ),
        ),
    ),
    (
        "鸣谢",
        (
            (
                "班主任李老师",
                "nsfz.jpg",
                "提出新功能并同意我们使用",
                (("网页", FIF.GLOBE, "https://李子扬.top"),),
            ),
            ("丁*腾", "nsfz.jpg", "持续关注新功能更新并试用", ()),
            (
                "未确定",
                "nsfz.jpg",
                "保持试用 电教猫 Pro 并提出新功能与建议",
                (),
            ),
            (
                "陈*铮",
                "nsfz.jpg",
                "保持试用 电教猫 Pro 并提出新功能与建议",
                (),
            ),
            (
                "龙ger_longer",
                "longer.jpg",
                "将 电教猫 Pro 刊登在自己网站的广告上",
                (
                    ("GitHub", FIF.GITHUB, "https://github.com/0xlonger"),
                    ("网页", FIF.GLOBE, "https://lgr.pages.dev"),
                    (
                        "bilibili",
                        FIF.VIDEO,
                        "https://space.bilibili.com/3493110082439389",
                    ),
                ),
            ),
        ),
    ),
    (
        "GUI技术",
        (
            ("PySide 6", "py.png", "", ()),
            (
                "PySide6-Fluent-Widgets",
                "py.png",
                "",
                (
                    (
                        "GitHub",
                        FIF.GITHUB,
                        "https://github.com/zhiyiYo/PyQt-Fluent-Widgets/tree/PySide6",
                    ),
                ),
            ),
        ),
    ),
)


class CreditEntry(QWidget):
    def __init__(self, name, avatar, description, links, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(52)

        avatarLabel = QLabel(self)
        avatarLabel.setFixedSize(34, 34)
        avatarLabel.setPixmap(self._roundPixmap(avatar, 34))

        nameLabel = BodyLabel(name, self)
        descriptionLabel = CaptionLabel(description, self)
        descriptionLabel.setWordWrap(True)
        descriptionLabel.setSizePolicy(
            QSizePolicy.Policy.Ignored,
            QSizePolicy.Policy.Preferred,
        )
        descriptionLabel.setTextColor(QColor(96, 96, 96), QColor(160, 160, 160))
        descriptionLabel.setVisible(bool(description))

        textLayout = QVBoxLayout()
        textLayout.setContentsMargins(0, 0, 0, 0)
        textLayout.setSpacing(0)
        textLayout.addWidget(nameLabel)
        textLayout.addWidget(descriptionLabel)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(8)
        layout.addWidget(avatarLabel, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(textLayout, 1)

        buttonLayout = QHBoxLayout()
        buttonLayout.setContentsMargins(0, 0, 0, 0)
        buttonLayout.setSpacing(2)
        for text, icon, url in links:
            button = HyperlinkButton(icon, url, text, self)
            button.setFixedWidth(button.sizeHint().width())
            buttonLayout.addWidget(button)
        layout.addLayout(buttonLayout)

    @staticmethod
    def _roundPixmap(fileName, size):
        source = QPixmap(str(ASSET_DIR / "support" / fileName)).scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addEllipse(QRectF(0, 0, size, size))
        painter.setClipPath(path)
        painter.drawPixmap(
            (size - source.width()) // 2,
            (size - source.height()) // 2,
            source,
        )
        painter.end()
        return pixmap


class CreditGroup(ElevatedCardWidget):
    def __init__(self, title, entries, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 16, 14, 18)
        layout.setSpacing(8)

        titleLabel = SubtitleLabel(title, self)
        titleLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(titleLabel)

        for entry in entries:
            layout.addWidget(CreditEntry(*entry, self))


class CreditsPage(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CreditsPage")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.enableTransparentBackground()

        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 30, 8, 36)
        layout.setSpacing(16)
        layout.addWidget(TitleLabel("特别鸣谢", container))

        for title, entries in _GROUPS:
            layout.addWidget(CreditGroup(title, entries, container))

        layout.addStretch(1)
        self.setWidget(container)
