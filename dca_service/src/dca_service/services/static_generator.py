"""
Static File Generator Service

Triggers regeneration of static files (charts, data, etc.) by running the main.py script.
This is typically called after a DCA transaction to ensure the website data is up-to-date.
"""
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from dca_service.core.logging import logger


def resolve_project_root() -> Path:
    """Resolve repository root from this module location."""
    # dca_service/src/dca_service/services/static_generator.py -> project_root
    return Path(__file__).parent.parent.parent.parent.parent


def get_static_generation_log_path() -> Path:
    """Return background static generation log path."""
    return resolve_project_root() / "data" / "static_generation.log"


def trigger_static_generation(background: bool = True) -> Optional[subprocess.Popen]:
    """
    Trigger static file generation by running main.py as a subprocess.
    
    This runs the main analysis script which:
    - Fetches latest Bitcoin price data
    - Recalculates all valuation metrics
    - Regenerates all charts and visualizations
    - Updates wealth distribution data
    
    Args:
        background: If True, run as non-blocking background process.
                   If False, wait for completion (blocks for 30-60 seconds).
    
    Returns:
        subprocess.Popen object if background=True, None otherwise
        
    Raises:
        FileNotFoundError: If main.py cannot be found
        subprocess.CalledProcessError: If main.py execution fails (only when background=False)
    """
    try:
        project_root = resolve_project_root()
        main_py_path = project_root / "main.py"
        
        if not main_py_path.exists():
            raise FileNotFoundError(f"main.py not found at {main_py_path}")
        
        logger.info(f"Triggering static file generation: {main_py_path}")
        
        # Use the same Python interpreter that's running this code
        python_executable = sys.executable
        
        if background:
            # Run as background process (non-blocking)
            # Write full output to a dedicated log file for diagnostics.
            # Avoid PIPE here; long-running verbose jobs can block when pipe
            # buffers fill up and nobody drains them.
            log_path = get_static_generation_log_path()
            log_path.parent.mkdir(parents=True, exist_ok=True)
            start_banner = (
                f"\n\n=== Static generation started at "
                f"{datetime.now(timezone.utc).isoformat()} "
                f"(pid pending) ===\n"
            )
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(start_banner)
                log_file.flush()
            log_handle = log_path.open("a", encoding="utf-8")
            process = subprocess.Popen(
                [python_executable, str(main_py_path), "--strict-update"],
                cwd=str(project_root),
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True
            )
            log_handle.close()
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"PID: {process.pid}\n")
                log_file.flush()
            logger.info(f"Started static generation process (PID: {process.pid})")
            return process
        else:
            # Run synchronously and wait for completion
            result = subprocess.run(
                [python_executable, str(main_py_path), "--strict-update"],
                cwd=str(project_root),
                capture_output=True,
                text=True,
                check=True,
                timeout=300  # 5 minute timeout
            )
            logger.info("Static generation completed successfully")
            if result.stdout:
                logger.debug(f"Static generation output: {result.stdout[:500]}")
            return None
            
    except FileNotFoundError as e:
        logger.error(f"Failed to find main.py: {e}")
        raise
    except subprocess.CalledProcessError as e:
        logger.error(f"Static generation failed with exit code {e.returncode}: {e.stderr[:500]}")
        raise
    except subprocess.TimeoutExpired as e:
        logger.error(f"Static generation timed out after {e.timeout} seconds")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during static generation: {e}")
        raise


def check_static_generation_status(process: subprocess.Popen) -> dict:
    """
    Check the status of a background static generation process.
    
    Args:
        process: subprocess.Popen object returned by trigger_static_generation()
    
    Returns:
        dict with keys:
            - running (bool): True if still running
            - exit_code (int|None): Exit code if completed, None if still running
            - stdout (str): Standard output (if completed)
            - stderr (str): Standard error (if completed)
    """
    poll_result = process.poll()
    
    if poll_result is None:
        # Still running
        return {
            "running": True,
            "exit_code": None,
            "stdout": "",
            "stderr": ""
        }
    else:
        # Completed
        stdout, stderr = process.communicate()
        return {
            "running": False,
            "exit_code": poll_result,
            "stdout": stdout or "",
            "stderr": stderr or ""
        }
