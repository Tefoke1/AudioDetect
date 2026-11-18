"""Termination of only the subprocess tree owned by a particular task."""
import subprocess
import psutil


def stop_process_tree(process):
    if process is None or process.poll() is not None:
        return
    try:
        owner = psutil.Process(process.pid)
        # Stop the owner first so it cannot create another inference child.
        owner.suspend()
        for child in owner.children(recursive=True):
            try:
                child.suspend()
            except psutil.NoSuchProcess:
                pass
        children = owner.children(recursive=True)
        for child in reversed(children):
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass
        owner.kill()
        psutil.wait_procs(children + [owner], timeout=1)
    except psutil.NoSuchProcess:
        pass
    finally:
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
