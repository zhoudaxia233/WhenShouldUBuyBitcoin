import sys
from pathlib import Path
from loguru import logger
from dca_service.config import settings

def setup_logging():
    """
    Configure loguru logger with:
    - stdout handler (colored)
    - file handler (rotated, retained)
    - format including time, level, module, function, line
    """
    # Remove default handler
    logger.remove()

    # Define format
    # Example: 2023-10-27 10:00:00 | INFO     | dca_service.main:startup:15 - DCA Service starting up
    log_format = (
        "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    
    file_format = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}"

    # Add stdout handler
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=log_format,
    )

    # Add file handler
    log_path = Path(settings.LOG_FILE_PATH)
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        
        logger.add(
            str(log_path),
            rotation="10 MB",
            retention="30 days",
            level=settings.LOG_LEVEL,
            format=file_format,
        )
    except Exception as e:
        # Fallback if we can't write to file (e.g. permissions)
        logger.warning(f"Could not setup file logging at {log_path}: {e}")

    return logger

# Configure logging on import
setup_logging()
