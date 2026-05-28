import logging
import sys

try:
    from pythonjsonlogger.json import JsonFormatter  # python-json-logger v3+
except ImportError:  # pragma: no cover
    from pythonjsonlogger.jsonlogger import JsonFormatter  # v2

_configured = False


def setup_logging(level: int = logging.INFO) -> None:
    """stdout に JSON 形式でログを出力する。

    Cloud Logging は stdout の JSON を jsonPayload として解釈し、
    `levelname` を `severity` にリネームすることで重大度も認識される。
    これにより `gcloud run services logs read` のデフォルト出力で
    アプリ層の logger.info(...) が見えるようになる。
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(name)s %(levelname)s %(message)s",
            rename_fields={"levelname": "severity", "asctime": "timestamp"},
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    _configured = True
