"""Isolated inference process. Its stdout is a JSON-lines event channel."""
import json
from pathlib import Path
import sys
import threading
import traceback


def emit(event, **payload):
    print(json.dumps({'event': event, **payload}, ensure_ascii=False), flush=True)


def main():
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')
    config = json.loads(sys.stdin.readline())
    from engine import transcribe_batch
    from semantic import analyze_batch
    cancel = threading.Event()
    progress = lambda i,n,message,percent: emit('progress', index=i, total=n, message=message, percent=percent)
    changed = lambda: emit('changed')
    result = {'ok': 0, 'failed': 0, 'stopped': False}
    try:
        if not config['analysis_only']:
            result.update(transcribe_batch(config['db'], config['models'], config['model'], cancel,
                progress, changed, recording_ids=config['recording_ids']))
        if config['analysis_only']:
            result.update(analyze_batch(config['db'], Path(config['models']).parent/'analysis-model',
                config['query'], config['fuzzy'], cancel, progress, changed,
                recording_ids=config['recording_ids'], search_mode=config.get('search_mode', 'phrase'),
                keyword_rule=config.get('keyword_rule', 'all')))
        emit('completed', result=result)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit('failed', message=str(exc))
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
