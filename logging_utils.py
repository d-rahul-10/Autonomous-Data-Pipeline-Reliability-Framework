"""Logging setup shared by all modules."""
import logging
import sys
import threading


_LOGGER_INIT_LOCK = threading.Lock()
_LOGGER_INITIALIZED: set[str] = set()


def get_logger(name: str = "pipeline", log_file: str = "pipeline.log", level=logging.INFO) -> logging.Logger:
    """Get or create a logger with thread-safe initialization."""
    logger = logging.getLogger(name)
    if name in _LOGGER_INITIALIZED:
        return logger

    with _LOGGER_INIT_LOCK:
        if name in _LOGGER_INITIALIZED:
            return logger
        logger.setLevel(level)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        logger.addHandler(sh)
        logger.addHandler(fh)
        _LOGGER_INITIALIZED.add(name)
    return logger