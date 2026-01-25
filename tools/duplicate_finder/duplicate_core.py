# tools/duplicate_finder/duplicate_core.py
import os
import hashlib
import difflib
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
from pathlib import Path

class DuplicateCore:
    """纯算法：返回重复/相似文件分组"""
    def __init__(self, max_workers=8):
        self.max_workers = max_workers
        self.similarity_thresholds = {'low': 70, 'medium': 80, 'high': 90}

    # ---------- 下面照搬你原来的 process_file_group / analyze_similarity 等 ----------
    def scan_and_group(self, root_path, progress_cb=None):
        """扫盘 + 返回 [{'type':'duplicate'|'similar', 'files':[...], 'similarity':float, 'category':str}, ...]"""
        file_groups = defaultdict(list)
        for root, _, files in os.walk(root_path):
            for file in files:
                fp = Path(root) / file
                try:
                    size = fp.stat().st_size
                    if size > 0:
                        file_groups[size].append(str(fp))
                except OSError:
                    continue

        candidate_groups = [g for g in file_groups.values() if len(g) > 1]
        results = []
        total = len(candidate_groups)

        for idx, group in enumerate(candidate_groups, 1):
            if progress_cb:
                progress_cb(idx / total * 100)
            results.extend(self._process_group(group))
        return results

    def _process_group(self, file_paths):
        # 哈希去重 + 相似度计算，返回 list[dict]
        hash_groups = defaultdict(list)
        for fp in file_paths:
            h = self._file_hash(fp)
            if h:
                hash_groups[h].append(fp)

        out = []
        for files in hash_groups.values():
            if len(files) > 1:
                out.append({'type': 'duplicate', 'files': files, 'similarity': 100.0, 'category': '完全相同'})

        # 剩余唯一文件再算相似度
        unique = [fp for fp in file_paths if not any(fp in v for v in hash_groups.values() if len(v) > 1)]
        for i in range(len(unique)):
            for j in range(i + 1, len(unique)):
                sim, cat = self._analyze_similarity(unique[i], unique[j])
                if sim >= self.similarity_thresholds['low']:
                    out.append({'type': 'similar', 'files': [unique[i], unique[j]], 'similarity': sim, 'category': cat})
        return out

    # -------------------- 内部工具函数 --------------------
    def _file_hash(self, file_path, algorithm='md5'):
        try:
            h = hashlib.new(algorithm)
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _analyze_similarity(self, f1, f2):
        try:
            with open(f1, 'r', encoding='utf-8', errors='ignore') as fp1, \
                 open(f2, 'r', encoding='utf-8', errors='ignore') as fp2:
                ratio = difflib.SequenceMatcher(None, fp1.read(), fp2.read()).ratio()
        except Exception:
            # 二进制则比对哈希
            ratio = 1.0 if self._file_hash(f1) == self._file_hash(f2) else 0.0
        sim = ratio * 100
        if sim >= self.similarity_thresholds['high']:
            cat = "高度相似"
        elif sim >= self.similarity_thresholds['medium']:
            cat = "中度相似"
        elif sim >= self.similarity_thresholds['low']:
            cat = "低度相似"
        else:
            cat = "不相似"
        return sim, cat