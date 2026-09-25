import tempfile
from copy import deepcopy
from pathlib import Path

from qfluentwidgets import ConfigItem, QConfig, qconfig

from app.config.cfg import cfg


def isolateCfg(testCase) -> Path:
    """Point cfg at a throwaway file and restore every item when the test ends.

    Returns the temporary directory, which lives until the test's cleanups run.
    """
    directory = tempfile.TemporaryDirectory()
    testCase.addCleanup(directory.cleanup)
    originalFile = cfg.file
    items = {
        item
        for klass in type(cfg).__mro__
        for item in vars(klass).values()
        if isinstance(item, ConfigItem)
    }
    values = [(item, deepcopy(item.value)) for item in items]
    cfg.file = Path(directory.name) / "config.json"

    fluentItems = set(vars(QConfig).values())

    def restore():
        for item, value in values:
            # QFluentWidgets 自己的项（主题等）要经 qconfig 设置，它缓存的 theme 才会跟着变。
            owner = qconfig if item in fluentItems else cfg
            owner.set(item, value, save=False)
        cfg.file = originalFile

    testCase.addCleanup(restore)
    return Path(directory.name)
