#!/usr/bin/env python3
"""VRCX Cloud 的本地应用入口。"""
if __name__ == '__main__':
    # Frozen subprocesses must divert before parsing application arguments.
    from multiprocessing import freeze_support
    freeze_support()
    from src.application.launcher import main
    raise SystemExit(main())
