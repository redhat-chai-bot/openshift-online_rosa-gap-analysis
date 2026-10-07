#!/usr/bin/env python3
"""Common utilities for gap analysis scripts."""

import shutil
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request


# ANSI color codes
class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[0;33m'
    BLUE = '\033[0;34m'
    RESET = '\033[0m'


def log_info(message):
    """Log an info message."""
    print(f"{Colors.BLUE}[INFO]{Colors.RESET} {message}", file=sys.stderr)


def log_success(message):
    """Log a success message."""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.RESET} {message}", file=sys.stderr)


def log_warning(message):
    """Log a warning message."""
    print(f"{Colors.YELLOW}[WARNING]{Colors.RESET} {message}", file=sys.stderr)


def log_error(message):
    """Log an error message."""
    print(f"{Colors.RED}[ERROR]{Colors.RESET} {message}", file=sys.stderr)


def check_command(command):
    """Check if a command is available in PATH."""
    if not shutil.which(command):
        log_error(f"{command} not found. Please install {command}.")
        sys.exit(1)


def get_project_root():
    """Get the project root directory."""
    # Script is in scripts/lib, so project root is two levels up
    return Path(__file__).parent.parent.parent.resolve()


RETRYABLE_HTTP_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def fetch_url(url, timeout=30, max_retries=2, retry_delay=2):
    """
    Fetch content from URL, retrying transient network failures.

    Args:
        url: URL to fetch
        timeout: Request timeout in seconds (default: 30)
        max_retries: Number of retries after the initial attempt (default: 2)
        retry_delay: Initial retry delay in seconds (default: 2)

    Returns:
        Response data as bytes

    Raises:
        HTTPError: If HTTP request fails after retries, or is not retryable
        URLError: If connection fails after retries
        TimeoutError: If the request times out after retries
        ValueError: If retry controls are invalid
    """
    if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    if retry_delay < 0:
        raise ValueError("retry_delay must be non-negative")

    req = Request(url, headers={'User-Agent': 'gap-analysis-script'})
    attempts = max_retries + 1

    for attempt in range(1, attempts + 1):
        try:
            with urlopen(req, timeout=timeout) as response:
                return response.read()
        except HTTPError as error:
            if error.code not in RETRYABLE_HTTP_STATUS_CODES:
                raise
            last_error = error
        except (URLError, TimeoutError) as error:
            last_error = error

        if attempt == attempts:
            log_error(
                f"HTTP fetch failed for {url} after {attempts} attempts "
                f"(timeout={timeout}s): {last_error}"
            )
            raise last_error

        delay = retry_delay * (2 ** (attempt - 1))
        log_warning(
            f"HTTP fetch failed for {url} (attempt {attempt}/{attempts}, "
            f"timeout={timeout}s): {last_error}; retrying in {delay}s"
        )
        time.sleep(delay)


def is_pre_ga_version(version):
    """Check if a version string is pre-GA (alpha, beta, nightly)."""
    pre_ga_markers = ['-alpha.', '-beta.', '-nightly']
    return any(marker in version for marker in pre_ga_markers)


def is_version_5x(minor_version):
    """Check if minor version is 5.x or higher (AWS/STS-only, no GCP/WIF)."""
    try:
        return int(minor_version.split('.')[0]) >= 5
    except (ValueError, IndexError):
        return False


def check_yaml_installed():
    """Check if PyYAML is installed and exit if not."""
    try:
        import yaml
    except ImportError:
        log_error("PyYAML is not installed. Install it with: pip install pyyaml")
        sys.exit(1)
