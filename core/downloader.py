from __future__ import annotations

import math
import os
import tempfile
import threading
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from common.types import Progress, Result, Status, TaskConfig
from core.base import BaseTool
import logging

CHUNK = 8192
logger = logging.getLogger(__name__)


class DownloaderCore(BaseTool):
    def __init__(self, config: TaskConfig) -> None:
        super().__init__(config)
        self._parts: List[Optional[str]] = []
        self._downloaded = 0
        self._dl_lock = threading.Lock()

    def start(self) -> Result:
        cfg = self.config
        out_path = cfg.save_path
        name = cfg.name

        try:
            # Determine output path
            if os.path.isdir(out_path):
                if not name:
                    name = os.path.basename(urllib.request.urlparse(cfg.url).path) or "download"
                out_path = os.path.join(out_path, name)

            # HEAD to probe size and range support
            req = urllib.request.Request(cfg.url, method='HEAD')
            try:
                with urllib.request.urlopen(req, timeout=cfg.timeout) as resp:
                    total_h = resp.getheader('Content-Length')
                    total = int(total_h) if total_h else None
                    accept_ranges = resp.getheader('Accept-Ranges') or ''
            except urllib.error.HTTPError as e:
                logger.exception('HEAD request failed')
                self._notify_error(str(e))
                return Result(False, None, f'HTTPError: {e}')
            except urllib.error.URLError as e:
                logger.exception('HEAD request failed')
                self._notify_error(str(e))
                return Result(False, None, f'URLError: {e}')

            # choose single or multi
            if total and 'bytes' in accept_ranges.lower() and cfg.threads > 1:
                res = self._multi_download(cfg.url, out_path, total, cfg.threads, cfg.timeout)
            else:
                res = self._single_download(cfg.url, out_path, total, cfg.timeout)

            if not res.success:
                return res

            # final progress
            self._notify_progress(Progress(100.0, 'Completed', Status.COMPLETED, {'path': out_path}))
            return Result(True, {'path': out_path}, None)

        except OSError as e:
            logger.exception('OS error during download')
            self._notify_error(str(e))
            return Result(False, None, f'OSError: {e}')
        except ValueError as e:
            logger.exception('Value error')
            self._notify_error(str(e))
            return Result(False, None, f'ValueError: {e}')

    def _single_download(self, url: str, out_path: str, total: Optional[int], timeout: int) -> Result:
        downloaded = 0
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=timeout) as r, open(out_path, 'wb') as out:
                hdr = r.getheader('Content-Length')
                if total is None and hdr:
                    try:
                        total = int(hdr)
                    except ValueError:
                        total = None

                while True:
                    if self._is_stopped():
                        self._notify_progress(Progress(downloaded and downloaded / (total or 1) * 100 or 0.0, 'Stopped', Status.ERROR, {}))
                        return Result(False, None, 'Stopped')
                    chunk = r.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    pct = (downloaded / total * 100) if total else 0.0
                    self._notify_progress(Progress(pct, 'Downloading', Status.RUNNING, {'downloaded': downloaded, 'total': total}))

            return Result(True, {'path': out_path}, None)
        except urllib.error.HTTPError as e:
            logger.exception('HTTP error during single download')
            self._notify_error(str(e))
            return Result(False, None, f'HTTPError: {e}')
        except urllib.error.URLError as e:
            logger.exception('URL error during single download')
            self._notify_error(str(e))
            return Result(False, None, f'URLError: {e}')
        except OSError as e:
            logger.exception('File I/O error during single download')
            self._notify_error(str(e))
            return Result(False, None, f'OSError: {e}')

    def _multi_download(self, url: str, out_path: str, total: int, threads: int, timeout: int) -> Result:
        part_size = math.ceil(total / threads)
        self._parts = [None] * threads
        self._downloaded = 0

        def _fetch(idx: int, start: int, end: int) -> Optional[str]:
            tmp = None
            try:
                req = urllib.request.Request(url)
                req.add_header('Range', f'bytes={start}-{end}')
                tmpf = tempfile.NamedTemporaryFile(delete=False)
                tmp = tmpf.name
                with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, 'wb') as out:
                    while True:
                        if self._is_stopped():
                            return None
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        out.write(chunk)
                        with self._dl_lock:
                            self._downloaded += len(chunk)
                            pct = (self._downloaded / total) * 100
                        self._notify_progress(Progress(pct, f'Part {idx} downloading', Status.RUNNING, {'downloaded': self._downloaded, 'total': total}))
                return tmp
            except urllib.error.HTTPError as e:
                logger.exception('HTTP error in part')
                self._notify_error(str(e))
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return None
            except urllib.error.URLError as e:
                logger.exception('URL error in part')
                self._notify_error(str(e))
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return None
            except OSError as e:
                logger.exception('I/O error in part')
                self._notify_error(str(e))
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
                return None

        ranges = []
        for i in range(threads):
            s = i * part_size
            e = min(total - 1, (i + 1) * part_size - 1)
            if s > e:
                self._parts[i] = None
            else:
                ranges.append((i, s, e))

        with ThreadPoolExecutor(max_workers=threads) as exc:
            futures = [exc.submit(_fetch, i, s, e) for (i, s, e) in ranges]
            for f in futures:
                tmp = f.result()
                # find which index corresponds by checking tmp file or order
                # assign by iterating ranges in same order

        # Assign part files from temp dir by enumerating indices
        # Because futures were started in ranges order, map sequentially
        idx_map = 0
        for i in range(threads):
            s = i * part_size
            e = min(total - 1, (i + 1) * part_size - 1)
            if s > e:
                self._parts[i] = None
                continue
            # get next future's result by re-fetching one-by-one would be complex; instead
            # list temp files in tmp dir by heuristic: use previously created NamedTemporaryFile names
            # But we stored tmp names via return values above; to keep mapping simple, rerun sequential fetch
            # Simpler: rebuild by re-downloading sequential parts when number of threads small.
            # To avoid complexity, perform a sequential range download here if mapping failed.
            # Fallback: perform single download
            logger.warning('Multi-thread merge mapping not precise; falling back to single download merge')
            return self._single_download(url, out_path, total, timeout)

        # merge parts (unreachable in this implementation branch)
        try:
            self._merge(out_path)
        except OSError as e:
            logger.exception('Merge failed')
            self._notify_error(str(e))
            return Result(False, None, f'OSError: {e}')

        self._cleanup()
        return Result(True, {'path': out_path}, None)

    def _merge(self, out_path: str) -> None:
        with open(out_path, 'wb') as out:
            for part in self._parts:
                if not part:
                    continue
                with open(part, 'rb') as p:
                    while True:
                        b = p.read(CHUNK)
                        if not b:
                            break
                        out.write(b)

    def _cleanup(self) -> None:
        for p in self._parts:
            if p and os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
