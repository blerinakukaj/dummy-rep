"""Structured logging configuration for AIPM pipeline runs."""

import logging
from pathlib import Path


class ColoredFormatter(logging.Formatter):
    """Console formatter that adds ANSI color codes based on log level."""

    COLORS = {
        logging.DEBUG: "\033[90m",  # grey
        logging.INFO: "\033[34m",  # blue
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",  # red
        logging.CRITICAL: "\033[1;31m",  # bold red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{self.RESET}"


def setup_logging(run_id: str, verbose: bool = False, output_dir: str = "output") -> logging.Logger:
    """Configure structured logging for a pipeline run.

    Creates a file handler that writes to output/{run_id}/pipeline.log
    and a console handler with colored output.

    Args:
        run_id: Unique run identifier for the log file path.
        verbose: If True, set level to DEBUG; otherwise INFO.
        output_dir: Base output directory.

    Returns:
        Configured root logger for the aipm namespace.
    """
    level = logging.DEBUG if verbose else logging.INFO
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    logger = logging.getLogger("aipm")
    logger.setLevel(level)

    # Avoid duplicate handlers on repeated calls
    logger.handlers.clear()

    # File handler — writes to output/{run_id}/pipeline.log
    log_dir = Path(output_dir) / run_id
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "pipeline.log"

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))
    logger.addHandler(file_handler)

    # Console handler — colored output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(ColoredFormatter(log_format, datefmt=date_format))
    logger.addHandler(console_handler)

    logger.info("Logging initialized — run_id=%s, level=%s, log_file=%s", run_id, logging.getLevelName(level), log_path)
    return logger
