"""Packaged entry point with a recoverable startup error log."""
from pathlib import Path
import sys
import traceback


def run():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == '--apply-update':
            from updater import apply_update
            return 0 if apply_update(Path(sys.argv[2]))['ok'] else 1
        from main import main
        return main()
    except Exception:
        root = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent.parent
        report = traceback.format_exc()
        try:
            log = root / 'data' / 'startup-error.log'
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(report, encoding='utf-8')
        except OSError:
            log = root
        if '--screenshot' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f'程序未能启动。错误详情已保存至：\n{log}', 'ACG Game Library', 0x10)
        return 1


if __name__ == '__main__':
    sys.exit(run())
