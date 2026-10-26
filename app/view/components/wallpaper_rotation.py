"""Wallpaper Rotation 的编辑：自动任务表单里的一行概要，以及单独的轮换列表对话框。

列表可能有几百张图，放进任务表单会把整页撑长、或在滚动区里再套一层滚动，所以在单独的对话框里
加图、导入、排序和删除。缩略图和"文件不存在"在后台线程里查，打开对话框不等磁盘。
"""

from __future__ import annotations

import os
import queue
import threading
from pathlib import PureWindowsPath

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QImage, QImageReader, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    Action,
    BodyLabel,
    CaptionLabel,
    InfoBadge,
    InfoBar,
    InfoBarPosition,
    InfoLevel,
    MessageBox,
    PushButton,
    RoundMenu,
    StrongBodyLabel,
    SubtitleLabel,
    ToolButton,
)
from qfluentwidgets import FluentIcon as FIF

from app.common.home_card_tasks import (
    homeCardTaskState,
    updateHomeCardTaskState,
    wallpaperKey,
)
from app.common.wallpaper import (
    WALLPAPER_FILE_FILTER,
    isWallpaperImage,
    scanWallpaperFolder,
    wallpaperFileExists,
)
from app.view.components.home_card_dialog import (
    SortableRow,
    SortableRowList,
    _dialogHost,
    _disposeDialog,
    _ResponsiveMessageBox,
)
from app.view.components.scroll_area import ScrollArea
from app.view.components.tool_tip import setFluentToolTip

THUMBNAIL_SIZE = QSize(64, 40)


def _fileName(path: str) -> str:
    return PureWindowsPath(path).name or path


def _folder(path: str) -> str:
    return str(PureWindowsPath(path).parent)


def rotationSummary(paths: list[str], current: str = "") -> str:
    """表单那一行的概要：「12 张 · 当前 海边.jpg」。"""
    if not paths:
        return "还没有图片"
    if current and wallpaperKey(current) in {wallpaperKey(path) for path in paths}:
        return f"{len(paths)} 张 · 当前 {_fileName(current)}"
    return f"{len(paths)} 张"


def rotationSuccessor(previous: list[str], current: str, paths: list[str]) -> str | None:
    """Current Wallpaper 被移出列表时，原来排在它后面、仍在列表里的那张；没有就从头开始。"""
    keys = [wallpaperKey(path) for path in previous]
    remaining = {wallpaperKey(path): path for path in paths}
    currentKey = wallpaperKey(current)
    if not current or currentKey not in keys or currentKey in remaining:
        return None
    for key in keys[keys.index(currentKey) + 1 :]:
        if key in remaining:
            return remaining[key]
    return None


class _ThumbnailLoader(QObject):
    """在一个后台线程里按顺序读缩略图，顺带查文件在不在。"""

    loaded = Signal(str, object, bool)

    def __init__(self, size: QSize, parent=None):
        super().__init__(parent)
        self._size = size
        self._queue = queue.Queue()
        self._canceled = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def request(self, path: str) -> None:
        self._queue.put(path)

    def cancel(self) -> None:
        self._canceled.set()
        self._queue.put(None)

    def _run(self) -> None:
        while not self._canceled.is_set():
            path = self._queue.get()
            if path is None or self._canceled.is_set():
                return
            exists = wallpaperFileExists(path)
            image = QImage()
            if exists:
                reader = QImageReader(os.path.expandvars(path))
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    # 按缩小后的尺寸解码：JPEG 能直接跳过大部分像素，几百张 4K 照片也很快。
                    reader.setScaledSize(
                        size.scaled(self._size, Qt.AspectRatioMode.KeepAspectRatio)
                    )
                image = reader.read()
            try:
                self.loaded.emit(path, image, exists)
            except RuntimeError:
                return


class _FolderScan(QObject):
    finished = Signal(object)

    def __init__(self, folder: str, parent=None):
        super().__init__(parent)
        self._canceled = threading.Event()
        self._thread = threading.Thread(target=self._run, args=(folder,), daemon=True)

    def start(self) -> None:
        self._thread.start()

    def cancel(self) -> None:
        self._canceled.set()

    def _run(self, folder: str) -> None:
        paths = scanWallpaperFolder(folder, self._canceled.is_set)
        if self._canceled.is_set():
            return
        try:
            self.finished.emit(paths)
        except RuntimeError:
            pass


class WallpaperRow(SortableRow):
    deleteRequested = Signal()
    moveFirstRequested = Signal()
    moveLastRequested = Signal()

    def __init__(self, path: str, parent=None):
        super().__init__(parent, "拖动调整图片顺序")
        self.path = path
        self.thumbnail = QLabel(self)
        self.thumbnail.setFixedSize(THUMBNAIL_SIZE)
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.nameLabel = StrongBodyLabel(self)
        self.detailLabel = CaptionLabel(self)
        self._texts = {self.nameLabel: _fileName(path), self.detailLabel: _folder(path)}
        for label in (self.nameLabel, self.detailLabel):
            label.setWordWrap(False)
            # 长路径不撑宽这一行，放不下的部分在 resizeEvent 里省略掉。
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.detailLabel.setStyleSheet("color: gray;")
        setFluentToolTip(self, path)
        self.currentBadge = InfoBadge("当前", self, InfoLevel.ATTENTION)
        self.currentBadge.hide()
        self.moreButton = ToolButton(FIF.MORE, self)
        self.deleteButton = ToolButton(FIF.DELETE, self)
        for button, name in (
            (self.moreButton, "更多操作"),
            (self.deleteButton, "移除这张图片"),
        ):
            button.setFixedSize(44, 44)
            setFluentToolTip(button, name)
            button.setAccessibleName(name)
        self.moreButton.clicked.connect(self._showMenu)
        self.deleteButton.clicked.connect(self.deleteRequested)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(12)
        layout.addWidget(self.dragHandle)
        layout.addWidget(self.thumbnail)
        textLayout = QVBoxLayout()
        textLayout.setContentsMargins(0, 0, 0, 0)
        textLayout.setSpacing(2)
        nameLayout = QHBoxLayout()
        nameLayout.setContentsMargins(0, 0, 0, 0)
        nameLayout.setSpacing(8)
        # 名字最多占它需要的宽度，「当前」紧跟在后面；放不下时名字先省略。
        self.nameLabel.setMaximumWidth(
            self.nameLabel.fontMetrics().horizontalAdvance(_fileName(path)) + 2
        )
        nameLayout.addWidget(self.nameLabel, 1)
        nameLayout.addWidget(self.currentBadge, 0, Qt.AlignmentFlag.AlignVCenter)
        nameLayout.addStretch(0)
        textLayout.addLayout(nameLayout)
        textLayout.addWidget(self.detailLabel)
        layout.addLayout(textLayout, 1)
        layout.addWidget(self.moreButton)
        layout.addWidget(self.deleteButton)
        self.setMinimumHeight(64)

    def setCurrent(self, current: bool) -> None:
        self.currentBadge.setVisible(current)
        self._elide()

    def setLoaded(self, image: QImage, exists: bool) -> None:
        folder = _folder(self.path)
        self._texts[self.detailLabel] = folder if exists else f"文件不存在 · {folder}"
        self._elide()
        if not image.isNull():
            pixmap = QPixmap.fromImage(image)
            pixmap.setDevicePixelRatio(self.devicePixelRatioF())
            self.thumbnail.setPixmap(pixmap)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()

    def _elide(self):
        for label, text in self._texts.items():
            width = label.width()
            label.setText(
                label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, width)
                if width > 0
                else text
            )

    def _showMenu(self):
        menu = RoundMenu(parent=self)
        first = Action(FIF.UP, "移到最前", menu)
        last = Action(FIF.DOWN, "移到最后", menu)
        first.triggered.connect(self.moveFirstRequested)
        last.triggered.connect(self.moveLastRequested)
        menu.addAction(first)
        menu.addAction(last)
        menu.exec(self.moreButton.mapToGlobal(self.moreButton.rect().bottomLeft()))


class WallpaperRotationDialog(_ResponsiveMessageBox):
    """编辑 Wallpaper Rotation：加图、按文件夹导入、拖动排序、移除和清空。"""

    def __init__(self, paths, current: str = "", parent=None):
        super().__init__(parent)
        self._currentKey = wallpaperKey(current)
        self._keys = set()
        self._rows = {}
        self._scan = None
        self.titleLabel = SubtitleLabel("轮换列表", self)
        self.descriptionLabel = CaptionLabel(
            "按顺序每次换下一张，最后一张之后回到第一张；找不到的图会跳过。拖动左侧手柄调整顺序。",
            self,
        )
        self.descriptionLabel.setWordWrap(True)
        self.addButton = PushButton(FIF.ADD, "添加图片", self)
        self.importButton = PushButton(FIF.FOLDER_ADD, "导入文件夹", self)
        self.countLabel = BodyLabel(self)
        self.clearButton = PushButton(FIF.DELETE, "清空", self)
        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        toolbar.addWidget(self.addButton)
        toolbar.addWidget(self.importButton)
        toolbar.addStretch(1)
        toolbar.addWidget(self.countLabel)
        toolbar.addWidget(self.clearButton)

        self.scrollArea = ScrollArea(self.widget)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scrollArea.enableTransparentBackground()
        self.scrollArea.setMinimumHeight(160)
        self.content = QWidget(self.scrollArea)
        self.content.setStyleSheet("background: transparent;")
        contentLayout = QVBoxLayout(self.content)
        contentLayout.setContentsMargins(0, 0, 0, 0)
        self.list = SortableRowList(self.content)
        self.list.setScrollArea(self.scrollArea)
        self.emptyLabel = CaptionLabel(
            "还没有图片。点「添加图片」或「导入文件夹」。", self.content
        )
        self.emptyLabel.setAlignment(Qt.AlignmentFlag.AlignCenter)
        contentLayout.addWidget(self.list)
        contentLayout.addWidget(self.emptyLabel)
        contentLayout.addStretch(1)
        self.scrollArea.setWidget(self.content)

        self.viewLayout.addWidget(self.titleLabel)
        self.viewLayout.addWidget(self.descriptionLabel)
        self.viewLayout.addLayout(toolbar)
        self.viewLayout.addWidget(self.scrollArea, 1)
        self.setPreferredSize(680, 620)
        self.yesButton.setText("保存")
        self.cancelButton.setText("取消")

        ratio = self.devicePixelRatioF()
        self._loader = _ThumbnailLoader(
            QSize(
                round(THUMBNAIL_SIZE.width() * ratio),
                round(THUMBNAIL_SIZE.height() * ratio),
            ),
            self,
        )
        self._loader.loaded.connect(self._onThumbnailLoaded)
        self.addButton.clicked.connect(self._chooseImages)
        self.importButton.clicked.connect(self._chooseFolder)
        self.clearButton.clicked.connect(self._clear)
        self.addPaths(paths)

    def paths(self) -> list[str]:
        return [row.path for row in self.list.rows]

    def addPaths(self, paths) -> tuple[int, int]:
        """追加到末尾，已在列表里的跳过；返回加上和跳过的张数。"""
        added = skipped = 0
        for path in paths:
            key = wallpaperKey(path)
            if not path or key in self._keys:
                skipped += 1
                continue
            self._keys.add(key)
            row = WallpaperRow(path, self.list)
            row.setCurrent(key == self._currentKey)
            row.deleteRequested.connect(lambda row=row: self._removeRow(row))
            row.moveFirstRequested.connect(lambda row=row: self.list.moveRow(row, 0))
            row.moveLastRequested.connect(
                lambda row=row: self.list.moveRow(row, len(self.list.rows) - 1)
            )
            self.list.addRow(row)
            self._rows[path] = row
            self._loader.request(path)
            added += 1
        self._updateCount()
        return added, skipped

    def _onThumbnailLoaded(self, path, image, exists):
        row = self._rows.get(path)
        if row is not None:
            row.setLoaded(image, exists)

    def _removeRow(self, row):
        self._keys.discard(wallpaperKey(row.path))
        self._rows.pop(row.path, None)
        self.list.removeRow(row)
        self._updateCount()

    def _updateCount(self):
        count = len(self.list.rows)
        self.countLabel.setText(f"共 {count} 张")
        self.emptyLabel.setVisible(count == 0)
        self.clearButton.setEnabled(count > 0)

    def _notify(self, added, skipped, verb):
        text = f"已{verb} {added} 张"
        if skipped:
            text += f"，跳过 {skipped} 张重复"
        InfoBar.success(
            "",
            text,
            duration=2500,
            position=InfoBarPosition.TOP,
            parent=self,
        )

    def _chooseImages(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择壁纸图片", "", WALLPAPER_FILE_FILTER
        )
        paths = [os.path.normpath(path) for path in paths if isWallpaperImage(path)]
        if paths:
            self._notify(*self.addPaths(paths), "添加")

    def _chooseFolder(self):
        folder = QFileDialog.getExistingDirectory(self, "选择要导入的文件夹")
        if not folder:
            return
        self.importButton.setEnabled(False)
        self.importButton.setText("正在扫描…")
        self._scan = _FolderScan(os.path.normpath(folder), self)
        self._scan.finished.connect(self._onFolderScanned)
        self._scan.start()

    def _onFolderScanned(self, paths):
        self._scan = None
        self.importButton.setEnabled(True)
        self.importButton.setText("导入文件夹")
        if not paths:
            InfoBar.warning(
                "",
                "这个文件夹里没有 JPG、PNG 或 BMP 图片",
                duration=2500,
                position=InfoBarPosition.TOP,
                parent=self,
            )
            return
        self._notify(*self.addPaths(paths), "导入")

    def _clear(self):
        if not self.list.rows:
            return
        box = MessageBox(
            "清空轮换列表",
            f"列表里的 {len(self.list.rows)} 张图片都会移除，图片文件本身不受影响。",
            _dialogHost(self),
        )
        box.yesButton.setText("清空")
        box.cancelButton.setText("取消")
        try:
            confirmed = box.exec()
        finally:
            _disposeDialog(box)
        if not confirmed:
            return
        for row in list(self.list.rows):
            self.list.removeRow(row)
        self._keys.clear()
        self._rows.clear()
        self._updateCount()

    def done(self, code):
        self._loader.cancel()
        if self._scan is not None:
            self._scan.cancel()
            self._scan = None
        super().done(code)


class WallpaperRotationField(QWidget):
    """自动任务表单里的「轮换列表」：概要一行加「编辑」按钮。"""

    changed = Signal()

    def __init__(self, paths, taskId: str = "", parent=None):
        super().__init__(parent)
        self._paths = list(paths)
        self.taskId = taskId
        self.summaryLabel = BodyLabel(self)
        self.editButton = PushButton(FIF.EDIT, "编辑", self)
        self.editButton.clicked.connect(self.edit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self.summaryLabel)
        layout.addWidget(self.editButton)
        self.refresh()

    def paths(self) -> list[str]:
        return list(self._paths)

    def _current(self) -> str:
        return homeCardTaskState(self.taskId).get("wallpaper", "") if self.taskId else ""

    def refresh(self) -> None:
        self.summaryLabel.setText(rotationSummary(self._paths, self._current()))

    def edit(self) -> None:
        current = self._current()
        dialog = WallpaperRotationDialog(self._paths, current, _dialogHost(self))
        try:
            if not dialog.exec():
                return
            paths = dialog.paths()
        finally:
            _disposeDialog(dialog)
        if paths == self._paths:
            return
        currentKey = wallpaperKey(current)
        if (
            self.taskId
            and current
            and any(wallpaperKey(path) == currentKey for path in self._paths)
            and all(wallpaperKey(path) != currentKey for path in paths)
        ):
            # 删掉了 Current Wallpaper：下次换成原来排在它后面的那张。
            updateHomeCardTaskState(
                self.taskId,
                wallpaperNext=rotationSuccessor(self._paths, current, paths),
            )
        self._paths = paths
        self.refresh()
        self.changed.emit()
