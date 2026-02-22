from __future__ import annotations

import argparse
import sys
import logging

from common.types import TaskConfig, Progress
from core.downloader import DownloaderCore

logging.basicConfig(level=logging.INFO)


def _print_progress(p: Progress) -> None:
    pct = f"{p.percent:.1f}%" if p.percent is not None else "?%"
    msg = p.message or p.status.value
    print(f"{pct} - {msg}", end='\r', flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog='BTM')
    sub = parser.add_subparsers(dest='cmd')

    d0 = sub.add_parser('download')
    d0.add_argument('-u', required=True, help='URL')
    d0.add_argument('-p', required=True, help='Save path (file or directory)')
    d0.add_argument('-t', type=int, default=4, help='Threads')
    d0.add_argument('-n', default=None, help='Optional filename')

    args = parser.parse_args(argv)

    if not args.cmd:
        parser.print_help()
        return 1

    if args.cmd == 'download':
        cfg = TaskConfig(url=args.u, save_path=args.p, threads=args.t, name=args.n)
        try:
            res = DownloaderCore(cfg).set_progress_callback(_print_progress).start()
        except Exception as e:
            logging.exception('Download failed')
            print('Download failed:', e)
            return 1

        print()

        if res.success:
            print('Download completed:', res.data)
            return 0
        else:
            print('Download failed:', res.error_message)
            return 1

    parser.print_help()
    return 1


if __name__ == '__main__':
    sys.exit(main())
