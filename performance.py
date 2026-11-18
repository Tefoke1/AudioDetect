"""Conservative CPU scheduling shared by both local inference engines."""
from contextlib import contextmanager
import logging
import os

import psutil


def cpu_threads():
    logical = psutil.cpu_count() or os.cpu_count() or 2
    physical = psutil.cpu_count(logical=False) or max(1, logical // 2)
    return max(1, min(8, physical, logical))


@contextmanager
def background_priority():
    """Temporarily let interactive applications take precedence on Windows."""
    process = psutil.Process()
    previous = None
    try:
        if os.name == 'nt':
            previous = process.nice()
            process.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
    except psutil.Error:
        logging.info('Could not reduce processing priority', exc_info=True)
    try:
        yield
    finally:
        if previous is not None:
            try:
                process.nice(previous)
            except psutil.Error:
                logging.info('Could not restore processing priority', exc_info=True)
