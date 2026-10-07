"""Server Version：整个服务端的版本号，与 Client Version 各自编号。

改 SERVER_VERSION 并合并进 main 即发布一个 Server Update。
"""

SERVER_VERSION = "1.5.0"
# git archive 和 GitHub 的压缩包会把下面的占位符换成所在提交（.gitattributes 的
# export-subst）；直接从工作区运行时它保持原样，按未知提交处理。
SERVER_COMMIT = "$Format:%H$"
