from qfluentwidgets import ToolTipFilter, ToolTipPosition


def setFluentToolTip(widget, text):
    widget.setToolTip(text)
    if not widget.findChildren(ToolTipFilter):
        widget.installEventFilter(
            ToolTipFilter(widget, showDelay=300, position=ToolTipPosition.TOP)
        )
