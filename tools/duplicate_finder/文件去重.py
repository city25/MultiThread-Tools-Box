import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import queue
import os
import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import difflib
from datetime import datetime
import pathlib

class FileDuplicateFinderUI:
    def __init__(self, root):
        self.root = root
        self.root.title("文件去重工具 - Python多线程版")
        self.root.geometry("1200x800")
        
        # 设置主题
        self.style = ttk.Style()
        self.style.theme_use('clam')
        
        # 配置颜色
        self.colors = {
            'bg': '#f0f0f0',
            'primary': '#2196F3',
            'success': '#4CAF50',
            'warning': '#FF9800',
            'danger': '#f44336',
            'dark': '#333333'
        }
        
        self.root.configure(bg=self.colors['bg'])
        
        # 初始化变量
        self.target_path = tk.StringVar(value="C:\\")
        self.max_workers = tk.IntVar(value=8)
        self.scan_status = tk.StringVar(value="就绪")
        self.progress_value = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="0%")
        
        self.file_groups = defaultdict(list)
        self.duplicate_groups = []
        self.selected_items = []
        
        # 线程通信队列
        self.progress_queue = queue.Queue()
        self.result_queue = queue.Queue()
        
        # 相似度阈值
        self.similarity_thresholds = {
            'low': 70,
            'medium': 80,
            'high': 90
        }
        
        self.setup_ui()
        
    def setup_ui(self):
        """设置用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # 配置网格权重
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(0, weight=1)
        main_frame.rowconfigure(3, weight=1)
        
        # === 顶部控制面板 ===
        control_frame = ttk.LabelFrame(main_frame, text="扫描设置", padding="10")
        control_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 路径选择
        ttk.Label(control_frame, text="扫描路径:").grid(row=0, column=0, sticky=tk.W, padx=(0, 10))
        path_entry = ttk.Entry(control_frame, textvariable=self.target_path, width=50)
        path_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), padx=(0, 10))
        
        browse_btn = ttk.Button(control_frame, text="浏览", command=self.browse_path)
        browse_btn.grid(row=0, column=2, padx=(0, 10))
        
        # 线程数设置
        ttk.Label(control_frame, text="线程数:").grid(row=0, column=3, sticky=tk.W, padx=(20, 10))
        thread_spinbox = ttk.Spinbox(control_frame, from_=1, to=16, textvariable=self.max_workers, width=5)
        thread_spinbox.grid(row=0, column=4, padx=(0, 10))
        
        # 开始扫描按钮
        self.scan_btn = ttk.Button(control_frame, text="开始扫描", command=self.start_scan)
        self.scan_btn.grid(row=0, column=5, padx=(20, 0))
        
        # 配置控制框架的列权重
        control_frame.columnconfigure(1, weight=1)
        
        # === 进度条区域 ===
        progress_frame = ttk.LabelFrame(main_frame, text="扫描进度", padding="10")
        progress_frame.grid(row=1, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_value, maximum=100, length=600)
        self.progress_bar.grid(row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 10))
        
        progress_label = ttk.Label(progress_frame, textvariable=self.progress_text, width=10)
        progress_label.grid(row=0, column=1)
        
        status_label = ttk.Label(progress_frame, textvariable=self.scan_status, width=30)
        status_label.grid(row=0, column=2, padx=(20, 0))
        
        progress_frame.columnconfigure(0, weight=1)
        
        # === 统计信息区域 ===
        stats_frame = ttk.LabelFrame(main_frame, text="统计信息", padding="10")
        stats_frame.grid(row=2, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        self.stats_vars = {
            'total_files': tk.StringVar(value="0"),
            'duplicate_groups': tk.StringVar(value="0"),
            'total_duplicates': tk.StringVar(value="0"),
            'space_saved': tk.StringVar(value="0 MB")
        }
        
        stats_items = [
            ("总文件数:", self.stats_vars['total_files']),
            ("重复组数:", self.stats_vars['duplicate_groups']),
            ("重复文件数:", self.stats_vars['total_duplicates']),
            ("可节省空间:", self.stats_vars['space_saved'])
        ]
        
        for i, (label, var) in enumerate(stats_items):
            ttk.Label(stats_frame, text=label).grid(row=0, column=i*2, sticky=tk.W, padx=(0, 5))
            ttk.Label(stats_frame, textvariable=var, font=('Arial', 10, 'bold')).grid(row=0, column=i*2+1, sticky=tk.W, padx=(0, 20))
        
        # === 结果表格区域 ===
        table_frame = ttk.LabelFrame(main_frame, text="重复文件列表", padding="10")
        table_frame.grid(row=3, column=0, columnspan=2, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 10))
        
        # 创建Treeview表格
        columns = ('group', 'file_path', 'file_size', 'similarity', 'category', 'status')
        self.tree = ttk.Treeview(table_frame, columns=columns, show='headings', selectmode='extended')
        
        # 定义列标题
        self.tree.heading('group', text='组ID')
        self.tree.heading('file_path', text='文件路径')
        self.tree.heading('file_size', text='文件大小')
        self.tree.heading('similarity', text='相似度')
        self.tree.heading('category', text='相似度分类')
        self.tree.heading('status', text='状态')
        
        # 配置列宽和对齐方式
        self.tree.column('group', width=60, anchor=tk.CENTER)
        self.tree.column('file_path', width=500, anchor=tk.W)
        self.tree.column('file_size', width=100, anchor=tk.E)
        self.tree.column('similarity', width=80, anchor=tk.CENTER)
        self.tree.column('category', width=100, anchor=tk.CENTER)
        self.tree.column('status', width=80, anchor=tk.CENTER)
        
        # 添加滚动条
        v_scrollbar = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        h_scrollbar = ttk.Scrollbar(table_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        
        # 布局表格和滚动条
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        v_scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        h_scrollbar.grid(row=1, column=0, sticky=(tk.W, tk.E))
        
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        
        # === 按钮操作区域 ===
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=4, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))
        
        # 删除按钮
        self.delete_btn = ttk.Button(button_frame, text="删除选中文件", command=self.delete_selected)
        self.delete_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # 导出报告按钮
        self.export_btn = ttk.Button(button_frame, text="导出报告", command=self.export_report)
        self.export_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        # 全选/取消全选按钮
        self.select_all_btn = ttk.Button(button_frame, text="全选", command=self.toggle_select_all)
        self.select_all_btn.pack(side=tk.LEFT)
        
        # 绑定双击事件
        self.tree.bind('<Double-Button-1>', self.on_item_double_click)
        
    def browse_path(self):
        """浏览选择路径"""
        path = filedialog.askdirectory()
        if path:
            self.target_path.set(path)
    
    def start_scan(self):
        """开始扫描"""
        if not os.path.exists(self.target_path.get()):
            messagebox.showerror("错误", "指定的路径不存在！")
            return
        
        # 禁用扫描按钮
        self.scan_btn.config(state='disabled')
        
        # 清空之前的結果
        self.file_groups.clear()
        self.duplicate_groups.clear()
        for item in self.tree.get_children():
            self.tree.delete(item)
        
        # 重置统计信息
        for var in self.stats_vars.values():
            var.set("0")
        
        # 启动扫描线程
        scan_thread = threading.Thread(target=self.scan_files_thread)
        scan_thread.daemon = True
        scan_thread.start()
        
        # 启动进度更新循环
        self.update_progress()
    
    def scan_files_thread(self):
        """扫描文件的线程函数"""
        try:
            self.progress_queue.put(('status', '正在扫描文件...'))
            self.progress_queue.put(('progress', 0))
            
            target_path = self.target_path.get()
            total_files = 0
            
            # 第一阶段：收集文件信息
            for root, dirs, files in os.walk(target_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        file_size = os.path.getsize(file_path)
                        if file_size > 0:
                            self.file_groups[file_size].append(file_path)
                            total_files += 1
                            
                            # 更新进度（每100个文件更新一次）
                            if total_files % 100 == 0:
                                self.progress_queue.put(('progress', min(30, total_files / 1000 * 30)))
                                self.progress_queue.put(('status', f'已发现 {total_files} 个文件...'))
                    
                    except OSError:
                        continue
            
            self.progress_queue.put(('total_files', total_files))
            self.progress_queue.put(('progress', 30))
            self.progress_queue.put(('status', '正在分析重复文件...'))
            
            # 第二阶段：分析重复文件
            candidate_groups = [files for files in self.file_groups.values() if len(files) > 1]
            total_groups = len(candidate_groups)
            
            if total_groups == 0:
                self.progress_queue.put(('status', '未找到重复文件'))
                self.progress_queue.put(('progress', 100))
                return
            
            # 处理重复文件组
            processed_groups = 0
            with ThreadPoolExecutor(max_workers=self.max_workers.get()) as executor:
                future_to_group = {
                    executor.submit(self.process_file_group, group): group 
                    for group in candidate_groups
                }
                
                for future in as_completed(future_to_group):
                    try:
                        result = future.result()
                        if result:
                            self.result_queue.put(result)
                        
                        processed_groups += 1
                        progress = 30 + (processed_groups / total_groups) * 70
                        self.progress_queue.put(('progress', progress))
                        self.progress_queue.put(('status', f'已处理 {processed_groups}/{total_groups} 个文件组'))
                        
                    except Exception as e:
                        print(f"处理文件组出错: {e}")
            
            self.progress_queue.put(('status', '扫描完成'))
            self.progress_queue.put(('progress', 100))
            
        except Exception as e:
            self.progress_queue.put(('error', str(e)))
    
    def process_file_group(self, file_paths):
        """处理文件组"""
        if len(file_paths) < 2:
            return []
        
        # 通过哈希值查找完全重复文件
        hash_groups = defaultdict(list)
        for file_path in file_paths:
            file_hash = self.get_file_hash(file_path)
            if file_hash:
                hash_groups[file_hash].append(file_path)
        
        results = []
        
        # 处理完全重复文件
        for files in hash_groups.values():
            if len(files) > 1:
                results.append({
                    'type': 'duplicate',
                    'files': files,
                    'similarity': 100.0,
                    'category': '完全相同'
                })
        
        # 对于哈希值不同的文件，计算相似度
        unique_files = []
        for file_path in file_paths:
            file_hash = self.get_file_hash(file_path)
            if file_hash and not any(file_path in group for group in hash_groups.values() if len(group) > 1):
                unique_files.append(file_path)
        
        # 对剩余文件进行相似度分析
        for i in range(len(unique_files)):
            for j in range(i + 1, len(unique_files)):
                file1, file2 = unique_files[i], unique_files[j]
                similarity, category = self.analyze_similarity(file1, file2)
                
                if similarity >= self.similarity_thresholds['low']:
                    results.append({
                        'type': 'similar',
                        'files': [file1, file2],
                        'similarity': similarity,
                        'category': category
                    })
        
        return results
    
    def get_file_hash(self, file_path, algorithm='md5'):
        """计算文件哈希值"""
        try:
            hash_obj = hashlib.new(algorithm)
            with open(file_path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_obj.update(chunk)
            return hash_obj.hexdigest()
        except Exception:
            return None
    
    def analyze_similarity(self, file1_path, file2_path):
        """分析文件相似度"""
        try:
            # 尝试作为文本文件读取
            with open(file1_path, 'r', encoding='utf-8', errors='ignore') as f1:
                content1 = f1.read()
            with open(file2_path, 'r', encoding='utf-8', errors='ignore') as f2:
                content2 = f2.read()
            
            similarity = difflib.SequenceMatcher(None, content1, content2).ratio() * 100
            
        except Exception:
            # 二进制文件，使用哈希值比较
            hash1 = self.get_file_hash(file1_path)
            hash2 = self.get_file_hash(file2_path)
            similarity = 100 if hash1 and hash2 and hash1 == hash2 else 0
        
        # 分类
        if similarity >= self.similarity_thresholds['high']:
            category = "高度相似"
        elif similarity >= self.similarity_thresholds['medium']:
            category = "中度相似"
        elif similarity >= self.similarity_thresholds['low']:
            category = "低度相似"
        else:
            category = "不相似"
        
        return similarity, category
    
    def update_progress(self):
        """更新进度"""
        try:
            # 处理进度队列
            while not self.progress_queue.empty():
                msg_type, value = self.progress_queue.get_nowait()
                
                if msg_type == 'progress':
                    self.progress_value.set(value)
                    self.progress_text.set(f"{value:.1f}%")
                elif msg_type == 'status':
                    self.scan_status.set(value)
                elif msg_type == 'total_files':
                    self.stats_vars['total_files'].set(f"{value:,}")
                elif msg_type == 'error':
                    messagebox.showerror("错误", f"扫描出错: {value}")
                    self.scan_btn.config(state='normal')
                    return
            
            # 处理结果队列
            while not self.result_queue.empty():
                results = self.result_queue.get_nowait()
                self.add_results_to_table(results)
            
            # 继续更新
            self.root.after(100, self.update_progress)
            
        except queue.Empty:
            # 继续更新
            self.root.after(100, self.update_progress)
        except Exception as e:
            print(f"更新进度出错: {e}")
            self.root.after(100, self.update_progress)
    
    def add_results_to_table(self, results):
        """添加结果到表格"""
        for result in results:
            group_id = len(self.duplicate_groups) + 1
            self.duplicate_groups.append(result)
            
            for file_path in result['files']:
                file_size = os.path.getsize(file_path)
                file_size_str = self.format_file_size(file_size)
                
                # 根据类型设置不同的标签
                if result['type'] == 'duplicate':
                    tags = ('duplicate',)
                    status = "完全相同"
                else:
                    tags = ('similar',)
                    status = "正常"
                
                self.tree.insert('', 'end', values=(
                    group_id,
                    file_path,
                    file_size_str,
                    f"{result['similarity']:.1f}%",
                    result['category'],
                    status
                ), tags=tags)
        
        # 更新统计信息
        self.update_statistics()
    
    def format_file_size(self, size):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    def update_statistics(self):
        """更新统计信息"""
        total_duplicates = 0
        total_space_saved = 0
        
        for result in self.duplicate_groups:
            if result['type'] == 'duplicate':
                # 完全重复文件，可以删除所有副本保留一个
                file_size = os.path.getsize(result['files'][0])
                duplicate_count = len(result['files']) - 1
                total_duplicates += duplicate_count
                total_space_saved += file_size * duplicate_count
            else:
                # 相似文件，只统计数量
                total_duplicates += len(result['files'])
        
        self.stats_vars['duplicate_groups'].set(f"{len(self.duplicate_groups)}")
        self.stats_vars['total_duplicates'].set(f"{total_duplicates}")
        self.stats_vars['space_saved'].set(self.format_file_size(total_space_saved))
        
        # 重新启用扫描按钮
        if self.progress_value.get() >= 100:
            self.scan_btn.config(state='normal')
    
    def delete_selected(self):
        """删除选中的文件"""
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("警告", "请先选择要删除的文件！")
            return
        
        # 获取选中的文件信息
        files_to_delete = []
        for item in selected_items:
            values = self.tree.item(item)['values']
            if len(values) >= 2:
                group_id = values[0]
                file_path = values[1]
                files_to_delete.append((group_id, file_path))
        
        if not files_to_delete:
            return
        
        # 显示确认对话框
        confirm_msg = f"确定要删除选中的 {len(files_to_delete)} 个文件吗？\n\n此操作不可撤销！"
        if messagebox.askyesno("确认删除", confirm_msg, icon='warning'):
            self.perform_deletion(files_to_delete)
    
    def perform_deletion(self, files_to_delete):
        """执行删除操作"""
        deleted_count = 0
        total_freed_space = 0
        
        for group_id, file_path in files_to_delete:
            try:
                if os.path.exists(file_path):
                    file_size = os.path.getsize(file_path)
                    os.remove(file_path)
                    total_freed_space += file_size
                    deleted_count += 1
                    
                    # 更新表格中的状态
                    for item in self.tree.get_children():
                        values = self.tree.item(item)['values']
                        if len(values) >= 2 and values[1] == file_path:
                            self.tree.set(item, 'status', '已删除')
                            self.tree.item(item, tags=('deleted',))
            except Exception as e:
                messagebox.showerror("删除错误", f"删除文件失败:\n{file_path}\n错误: {str(e)}")
        
        # 显示删除结果
        if deleted_count > 0:
            freed_space_str = self.format_file_size(total_freed_space)
            messagebox.showinfo("删除完成", 
                              f"成功删除 {deleted_count} 个文件\n"
                              f"释放空间: {freed_space_str}")
            
            # 重新扫描以更新列表
            self.root.after(1000, lambda: self.start_scan())
    
    def toggle_select_all(self):
        """全选/取消全选"""
        if self.select_all_btn['text'] == '全选':
            self.tree.selection_add(self.tree.get_children())
            self.select_all_btn.config(text='取消全选')
        else:
            self.tree.selection_remove(self.tree.get_children())
            self.select_all_btn.config(text='全选')
    
    def on_item_double_click(self, event):
        """双击项目时打开文件位置"""
        item = self.tree.selection()[0]
        values = self.tree.item(item)['values']
        if len(values) >= 2:
            file_path = values[1]
            if os.path.exists(file_path):
                # 在资源管理器中打开文件位置
                folder_path = os.path.dirname(file_path)
                os.startfile(folder_path)
    
    def export_report(self):
        """导出报告"""
        if not self.duplicate_groups:
            messagebox.showwarning("警告", "没有可导出的数据！")
            return
        
        # 选择保存位置
        filename = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=f"重复文件报告_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        if not filename:
            return
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("=== 文件去重分析报告 ===\n")
                f.write(f"扫描路径: {self.target_path.get()}\n")
                f.write(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"线程数: {self.max_workers.get()}\n\n")
                
                for i, result in enumerate(self.duplicate_groups, 1):
                    f.write(f"\n--- 文件组 {i} ---\n")
                    f.write(f"类型: {'完全重复' if result['type'] == 'duplicate' else '相似文件'}\n")
                    f.write(f"相似度: {result['similarity']:.1f}%\n")
                    f.write(f"分类: {result['category']}\n")
                    f.write("文件列表:\n")
                    
                    for file_path in result['files']:
                        file_size = os.path.getsize(file_path)
                        f.write(f"  📄 {file_path}\n")
                        f.write(f"     大小: {self.format_file_size(file_size)}\n")
                
                # 添加统计信息
                f.write(f"\n=== 统计信息 ===\n")
                f.write(f"重复组数: {self.stats_vars['duplicate_groups'].get()}\n")
                f.write(f"重复文件数: {self.stats_vars['total_duplicates'].get()}\n")
                f.write(f"可节省空间: {self.stats_vars['space_saved'].get()}\n")
            
            messagebox.showinfo("导出成功", f"报告已保存到:\n{filename}")
            
        except Exception as e:
            messagebox.showerror("导出失败", f"导出报告时出错:\n{str(e)}")

def main():
    """主函数"""
    root = tk.Tk()
    app = FileDuplicateFinderUI(root)
    
    # 配置样式
    style = ttk.Style()
    
    # 配置标签颜色
    if 'tree' in app.__dict__:
        app.tree.tag_configure('duplicate', background='#e8f5e8')
        app.tree.tag_configure('similar', background='#fff3e0')
        app.tree.tag_configure('deleted', background='#ffebee', foreground='#666666')
    
    root.mainloop()

if __name__ == "__main__":
    main()
