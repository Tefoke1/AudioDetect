"""Portable GUI and isolated console worker entry point."""
import os
import sys
os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
os.environ.setdefault('DO_NOT_TRACK', '1')
if __name__ == '__main__':
    if 'worker' in os.path.basename(sys.executable).lower():
        from pipeline_worker import main
    else:
        from app import main
    raise SystemExit(main())
