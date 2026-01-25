# tools/duplicate_finder/duplicate_ui.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import queue
import threading
from datetime import datetime
from duplicate_core import DuplicateCore   # 同目录核心类


class FileDuplicateFinderUI:
    def __init__(self, root):
        self.root = root
        self.root.title("文件去重工具 - Python多线程版")
        self.root.geometry("1200x800")
        self.core = DuplicateCore(max_workers=8)

        # ---------- 样式/变量 ----------
        self.colors = {'primary': '#3775A9', 'success': '#4CAF50',
                       'warning': '#FF9800', 'danger': '#f44336'}
        style = ttk.Style()
        style.theme_use('clam')

        self.target_path = tk.StringVar(value="C:\\")
        self.max_workers = tk.IntVar(value=8)
        self.scan_status = tk.StringVar(value="就绪")
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="0%")

        self.duplicate_groups = []
        self.progress_queue = queue.Queue()
        self.result_queue = queue.Queue()

        # ---------- 一键布局 ----------
        self._build_ui()

    # ==================== UI 搭建 ====================
    def _build_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill=tk.BOTH, expand=True)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # 顶部控制
        ctrl = ttk.LabelFrame(main, text="扫描设置", padding=10)
        ctrl.pack(fill=tk.X, pady=(0, 10))
        ttk.Label(ctrl, text="扫描路径:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        ttk.Entry(ctrl, textvariable=self.target_path, width=50).grid(row=0, column=1, padx=(0, 10))
        ttk.Button(ctrl, text="浏览", command=self._browse).grid(row=0, column=2, padx=(0, 10))
        ttk.Label(ctrl, text="线程数:").grid(row=0, column=3, padx=(20, 10))
        ttk.Spinbox(ctrl, from_=1, to=16, textvariable=self.max_workers, width=5).grid(row=0, column=4, padx=(0, 10))
        self.scan_btn = ttk.Button(ctrl, text="开始扫描", command=self._start_scan)
        self.scan_btn.grid(row=0, column=5, padx=(20, 0))

        # 进度条
        prog = ttk.LabelFrame(main, text="扫描进度", padding=10)
        prog.pack(fill=tk.X, pady=(0, 10))
        ttk.Progressbar(prog, variable=self.progress_value, maximum=100, length=600).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        ttk.Label(prog, textvariable=self.progress_text, width=10).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(prog, textvariable=self.scan_status, width=30).pack(side=tk.LEFT)

        # 统计信息
        stats = ttk.LabelFrame(main, text="统计信息", padding=10)
        stats.pack(fill=tk.X, pady=(0, 10))
        self.stats_vars = {k: tk.StringVar(value="0") for k in ['total_files', 'duplicate_groups', 'total_duplicates', 'space_saved']}
        for i, (label, var) in enumerate([("总文件数:", self.stats_vars['total_files']),
                                          ("重复组数:", self.stats_vars['duplicate_groups']),
                                          ("重复文件数:", self.stats_vars['total_duplicates']),
                                          ("可节省空间:", self.stats_vars['space_saved'])]):
            ttk.Label(stats, text=label).grid(row=0, column=i*2, padx=(0, 5))
            ttk.Label(stats, textvariable=var, font=('Arial', 10, 'bold')).grid(row=0, column=i*2+1, padx=(0, 20))

        # 结果表格
        table = ttk.LabelFrame(main, text="重复文件列表", padding=10)
        table.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        columns = ('group', 'file_path', 'file_size', 'similarity', 'category', 'status')
        self.tree = ttk.Treeview(table, columns=columns, show='headings', selectmode='extended')
        for col, text, width in zip(columns, ['组ID', '文件路径', '文件大小', '相似度', '相似度分类', '状态'],
                                    [60, 500, 100, 80, 100, 80]):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor=tk.CENTER if col != 'file_path' else tk.W)
        vsb = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self.tree.yview)
        hsb = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')
        hsb.grid(row=1, column=0, sticky='ew')
        table.columnconfigure(0, weight=1)
        table.rowconfigure(0, weight=1)
        self.tree.bind('<Double-Button-1>', self._open_folder)

        # 按钮区
        btn_bar = ttk.Frame(main)
        btn_bar.pack(fill=tk.X)
        ttk.Button(btn_bar, text="删除选中文件", command=self._delete_selected).pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(btn_bar, text="导出报告", command=self._export_report).pack(side=tk.LEFT, padx=(0, 10))
        self.select_all_btn = ttk.Button(btn_bar, text="全选", command=self._toggle_select)
        self.select_all_btn.pack(side=tk.LEFT)

    # ==================== 功能实现 ====================
    def _browse(self):
        path = filedialog.askdirectory()
        if path:
            self.target_path.set(path)

    def _start_scan(self):
        if not os.path.exists(self.target_path.get()):
            messagebox.showerror("错误", "路径不存在！")
            return
        self.scan_btn.config(state='disabled')
        self.tree.delete(*self.tree.get_children())
        self.duplicate_groups.clear()
        for v in self.stats_vars.values():
            v.set("0")
        threading.Thread(target=self._scan_thread, daemon=True).start()
        self._poll_progress()

    def _scan_thread(self):
        try:
            self.progress_queue.put(('status', '正在扫描...'))
            results = self.core.scan_and_group(
                self.target_path.get(),
                progress_cb=lambda p: self.progress_queue.put(('progress', p))
            )
            for r in results:
                self.result_queue.put(r)
            self.progress_queue.put(('status', '扫描完成'))
        except Exception as e:
            self.progress_queue.put(('error', str(e)))

    def _poll_progress(self):
        while not self.progress_queue.empty():
            msg_type, value = self.progress_queue.get_nowait()
            if msg_type == 'progress':
                self.progress_value.set(value)
                self.progress_text.set(f"{value:.1f}%")
            elif msg_type == 'status':
                self.scan_status.set(value)
            elif msg_type == 'error':
                messagebox.showerror("错误", value)
                self.scan_btn.config(state='normal')
                return
        while not self.result_queue.empty():
            self._add_result_to_table(self.result_queue.get())
        self.stats_vars['duplicate_groups'].set(str(len(self.duplicate_groups)))
        self.root.after(100, self._poll_progress)

    def _add_result_to_table(self, result):
        group_id = len(self.duplicate_groups) + 1
        self.duplicate_groups.append(result)
        for fp in result['files']:
            size = os.path.getsize(fp)
            self.tree.insert('', 'end', values=(
                group_id, fp, self._fmt_size(size),
                f"{result['similarity']:.1f}%", result['category'], "正常"
            ), tags=('duplicate' if result['type'] == 'duplicate' else 'similar'))

    # ---------- 删除 / 导出 / 工具函数 ----------
    def _delete_selected(self):
        items = self.tree.selection()
        if not items:
            messagebox.showwarning("警告", "请先选择要删除的文件！")
            return
        if not messagebox.askyesno("确认", f"确定删除选中的 {len(items)} 个文件吗？"):
            return
        deleted = freed = 0
        for item in items:
            fp = self.tree.item(item)['values'][1]
            try:
                freed += os.path.getsize(fp)
                os.remove(fp)
                deleted += 1
                self.tree.set(item, 'status', '已删除')
            except Exception as e:
                messagebox.showerror("删除错误", f"{fp}\n{str(e)}")
        if deleted:
            messagebox.showinfo("完成", f"已删除 {deleted} 个文件，释放 {self._fmt_size(freed)}")

    def _export_report(self):
        if not self.duplicate_groups:
            messagebox.showwarning("警告", "没有可导出的数据！")
            return
        fn = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile=f"重复文件报告_{datetime.now():%Y%m%d_%H%M%S}.txt")
        if not fn:
            return
        with open(fn, 'w', encoding='utf-8') as f:
            f.write("=== 文件去重分析报告 ===\n")
            f.write(f"扫描路径: {self.target_path.get()}\n")
            f.write(f"分析时间: {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            for idx, g in enumerate(self.duplicate_groups, 1):
                f.write(f"\n--- 文件组 {idx} ---\n")
                f.write(f"类型: {'完全重复' if g['type']=='duplicate' else '相似文件'}\n")
                f.write(f"相似度: {g['similarity']:.1f}%\n")
                for fp in g['files']:
                    f.write(f"  📄 {fp}  ({self._fmt_size(os.path.getsize(fp))})\n")
        messagebox.showinfo("导出成功", f"报告已保存到:\n{fn}")

    def _toggle_select(self):
        if self.select_all_btn['text'] == '全选':
            self.tree.selection_add(self.tree.get_children())
            self.select_all_btn.config(text='取消全选')
        else:
            self.tree.selection_remove(self.tree.get_children())
            self.select_all_btn.config(text='全选')

    def _open_folder(self, event):
        item = self.tree.selection()
        if item:
            fp = self.tree.item(item[0])['values'][1]
            folder = os.path.dirname(fp)
            os.startfile(folder) if os.name == 'nt' else os.system(f'xdg-open "{folder}"')

    # ---------- 通用工具 ----------
    def _fmt_size(self, size):
        for u in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {u}"
            size /= 1024
        return f"{size:.1f} TB"