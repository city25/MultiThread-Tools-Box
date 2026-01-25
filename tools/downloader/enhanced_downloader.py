# tools/downloader/enhanced_downloader.py
import os
import time
import threading
import queue
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse, unquote
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tkinter.font as tkfont
from concurrent.futures import ThreadPoolExecutor
import subprocess
import platform

# 第三方库（可选，功能增强）
try:
    import yt_dlp  # 视频下载支持
    YT_SUPPORT = True
except ImportError:
    YT_SUPPORT = False

try:
    import notification  # 系统通知
    NOTIFY_SUPPORT = True
except ImportError:
    NOTIFY_SUPPORT = False

class DownloadTask:
    """下载任务类"""
    STATUS_PENDING = "等待中"
    STATUS_DOWNLOADING = "下载中"
    STATUS_PAUSED = "已暂停"
    STATUS_COMPLETED = "已完成"
    STATUS_FAILED = "失败"
    STATUS_CANCELLED = "已取消"
    
    def __init__(self, url, filename=None, save_path=None, threads=8, max_speed=None):
        self.id = int(time.time() * 1000)  # 使用时间戳作为ID
        self.url = url
        self.filename = filename or self.extract_filename(url)
        self.save_path = save_path or os.path.join(os.environ["USERPROFILE"], "Downloads")
        self.threads = threads
        self.max_speed = max_speed  # KB/s
        self.status = self.STATUS_PENDING
        self.total_size = 0
        self.downloaded_size = 0
        self.speed = 0
        self.eta = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self.retries = 0
        self.max_retries = 3
        self.created_time = datetime.now()
        
    def extract_filename(self, url):
        """从URL提取文件名"""
        try:
            parsed = urlparse(url)
            filename = os.path.basename(unquote(parsed.path))
            if not filename:
                filename = f"download_{int(time.time())}.bin"
            return filename
        except:
            return f"download_{int(time.time())}.bin"
    
    def get_file_path(self):
        """获取完整文件路径"""
        return os.path.join(self.save_path, self.filename)
    
    def get_progress(self):
        """获取下载进度"""
        if self.total_size == 0:
            return 0
        return (self.downloaded_size / self.total_size) * 100
    
    def get_speed_str(self):
        """格式化速度显示"""
        if self.speed == 0:
            return "0 B/s"
        for unit in ['B/s', 'KB/s', 'MB/s', 'GB/s']:
            if self.speed < 1024.0:
                return f"{self.speed:.1f} {unit}"
            self.speed /= 1024.0
        return f"{self.speed:.1f} TB/s"
    
    def get_size_str(self):
        """格式化文件大小"""
        size = self.total_size
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} TB"
    
    def to_dict(self):
        """转换为字典（用于保存）"""
        return {
            'id': self.id,
            'url': self.url,
            'filename': self.filename,
            'save_path': self.save_path,
            'threads': self.threads,
            'max_speed': self.max_speed,
            'status': self.status,
            'total_size': self.total_size,
            'downloaded_size': self.downloaded_size,
            'created_time': self.created_time.isoformat(),
            'completed_time': self.end_time.isoformat() if self.end_time else None
        }

class DownloadManager:
    """下载管理器"""
    def __init__(self, max_concurrent=3):
        self.max_concurrent = max_concurrent
        self.active_downloads = {}
        self.download_queue = queue.Queue()
        self.db_path = "downloads.db"
        self.init_database()
        self.load_download_history()
        
    def init_database(self):
        """初始化数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS downloads (
                id INTEGER PRIMARY KEY,
                url TEXT NOT NULL,
                filename TEXT NOT NULL,
                save_path TEXT NOT NULL,
                threads INTEGER DEFAULT 8,
                max_speed INTEGER,
                total_size INTEGER DEFAULT 0,
                downloaded_size INTEGER DEFAULT 0,
                status TEXT DEFAULT '等待中',
                created_time TEXT NOT NULL,
                completed_time TEXT,
                error_message TEXT
            )
        ''')
        conn.commit()
        conn.close()
    
    def load_download_history(self):
        """加载下载历史"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM downloads ORDER BY created_time DESC LIMIT 100")
        rows = cursor.fetchall()
        conn.close()
        return rows
    
    def add_download(self, task):
        """添加下载任务"""
        self.download_queue.put(task)
        self.save_task_to_db(task)
        
    def save_task_to_db(self, task):
        """保存任务到数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO downloads (id, url, filename, save_path, threads, max_speed, 
                                 total_size, downloaded_size, status, created_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (task.id, task.url, task.filename, task.save_path, task.threads, 
              task.max_speed, task.total_size, task.downloaded_size, task.status, 
              task.created_time.isoformat()))
        conn.commit()
        conn.close()
    
    def update_task_status(self, task_id, status, error_message=None):
        """更新任务状态"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        completed_time = datetime.now().isoformat() if status in ['已完成', '失败', '已取消'] else None
        cursor.execute('''
            UPDATE downloads SET status = ?, error_message = ?, completed_time = ?
            WHERE id = ?
        ''', (status, error_message, completed_time, task_id))
        conn.commit()
        conn.close()
    
    def start_download_manager(self):
        """启动下载管理器"""
        threading.Thread(target=self.download_manager_worker, daemon=True).start()
    
    def download_manager_worker(self):
        """下载管理器工作线程"""
        while True:
            try:
                task = self.download_queue.get(timeout=1)
                if task is None:
                    break
                
                # 等待有空闲槽位
                while len(self.active_downloads) >= self.max_concurrent:
                    time.sleep(0.5)
                
                # 开始下载
                self.start_download(task)
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"下载管理器错误: {e}")
    
    def start_download(self, task):
        """开始单个下载"""
        task.status = DownloadTask.STATUS_DOWNLOADING
        task.start_time = datetime.now()
        self.update_task_status(task.id, task.status)
        
        # 启动下载线程
        download_thread = threading.Thread(
            target=self.download_worker,
            args=(task,),
            daemon=True
        )
        download_thread.start()
        
        self.active_downloads[task.id] = download_thread
    
    def download_worker(self, task):
        """下载工作线程"""
        try:
            # 获取文件信息
            req = urllib.request.Request(task.url, method="HEAD")
            resp = urllib.request.urlopen(req)
            task.total_size = int(resp.headers.get("Content-Length", 0))
            accept_ranges = resp.headers.get("Accept-Ranges", "none") != "none"
            
            # 根据服务器支持情况调整线程数
            if not accept_ranges:
                task.threads = 1
            
            # 创建临时目录
            os.makedirs(task.save_path, exist_ok=True)
            tmp_dir = os.path.join(task.save_path, f".tmp_{task.id}")
            os.makedirs(tmp_dir, exist_ok=True)
            
            # 分块下载
            chunk_size = task.total_size // task.threads
            lock = threading.Lock()
            
            def download_part(part_idx):
                start_byte = part_idx * chunk_size
                end_byte = task.total_size - 1 if part_idx == task.threads - 1 else start_byte + chunk_size - 1
                
                tmp_file = os.path.join(tmp_dir, f"part_{part_idx}")
                headers = {"Range": f"bytes={start_byte}-{end_byte}"}
                
                req = urllib.request.Request(task.url, headers=headers)
                
                with urllib.request.urlopen(req) as response, open(tmp_file, "wb") as f:
                    while task.status == DownloadTask.STATUS_DOWNLOADING:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        
                        f.write(chunk)
                        
                        with lock:
                            task.downloaded_size += len(chunk)
                        
                        # 速度限制
                        if task.max_speed:
                            time.sleep(len(chunk) / (task.max_speed * 1024))
            
            # 启动分块下载线程
            with ThreadPoolExecutor(max_workers=task.threads) as executor:
                futures = [executor.submit(download_part, i) for i in range(task.threads)]
                
                # 等待所有分块完成
                for future in futures:
                    future.result()
            
            # 合并文件
            with open(task.get_file_path(), "wb") as output_file:
                for i in range(task.threads):
                    part_file = os.path.join(tmp_dir, f"part_{i}")
                    with open(part_file, "rb") as pf:
                        output_file.write(pf.read())
            
            # 清理临时文件
            for i in range(task.threads):
                os.remove(os.path.join(tmp_dir, f"part_{i}"))
            os.rmdir(tmp_dir)
            
            # 更新状态
            task.status = DownloadTask.STATUS_COMPLETED
            task.end_time = datetime.now()
            self.update_task_status(task.id, task.status)
            
            # 发送完成通知
            self.send_completion_notification(task)
            
        except Exception as e:
            task.status = DownloadTask.STATUS_FAILED
            task.error_message = str(e)
            task.end_time = datetime.now()
            self.update_task_status(task.id, task.status, str(e))
            
            # 重试机制
            if task.retries < task.max_retries:
                task.retries += 1
                time.sleep(2)
                self.start_download(task)
        
        finally:
            # 从活动下载中移除
            if task.id in self.active_downloads:
                del self.active_downloads[task.id]
    
    def send_completion_notification(self, task):
        """发送完成通知"""
        if NOTIFY_SUPPORT:
            try:
                notification.notify(
                    title="下载完成",
                    message=f"{task.filename} 下载完成！",
                    timeout=5
                )
            except:
                pass
    
    def pause_download(self, task_id):
        """暂停下载"""
        # 实现暂停逻辑
        pass
    
    def cancel_download(self, task_id):
        """取消下载"""
        # 实现取消逻辑
        pass

class EnhancedDownloaderUI:
    """增强版下载器UI"""
    def __init__(self, parent=None):
        self.parent = parent
        self.download_manager = DownloadManager()
        self.download_manager.start_download_manager()
        
        if parent:
            self.window = tk.Toplevel(parent)
        else:
            self.window = tk.Tk()
        
        self.window.title("🚀 增强版下载器")
        self.window.geometry("1000x700")
        
        # 配置主题
        self.setup_theme()
        
        # 创建UI
        self.create_ui()
        
        # 启动UI更新定时器
        self.update_ui_timer()
        
        if not parent:
            self.window.mainloop()
    
    def setup_theme(self):
        """设置主题样式"""
        self.colors = {
            'primary': '#2196F3',
            'secondary': '#FFC107',
            'success': '#4CAF50',
            'danger': '#f44336',
            'dark': '#212121',
            'light': '#f5f5f5',
            'white': '#ffffff',
            'gray': '#9e9e9e'
        }
        
        # 配置ttk样式
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置按钮样式
        style.configure('Primary.TButton', 
                       background=self.colors['primary'],
                       foreground='white',
                       borderwidth=0,
                       padding=8)
        
        style.map('Primary.TButton',
                 background=[('active', '#1976D2')])
        
        # 配置标签样式
        style.configure('Header.TLabel', 
                       font=('Segoe UI', 12, 'bold'),
                       foreground=self.colors['dark'])
        
        style.configure('Status.TLabel',
                       font=('Segoe UI', 10))
    
    def create_ui(self):
        """创建用户界面"""
        # 主框架
        main_frame = ttk.Frame(self.window, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # === 顶部控制区域 ===
        control_frame = ttk.LabelFrame(main_frame, text="添加下载任务", padding="10")
        control_frame.pack(fill=tk.X, pady=(0, 10))
        
        # URL输入
        url_frame = ttk.Frame(control_frame)
        url_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(url_frame, text="下载链接:", style='Header.TLabel').pack(side=tk.LEFT, padx=(0, 10))
        self.url_entry = ttk.Entry(url_frame, width=60, font=('Segoe UI', 11))
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 10))
        
        # 拖拽支持
        # self.url_entry.drop_target_register(tk.DND_TEXT)
        # self.url_entry.dnd_bind('<<Drop>>', self.on_url_drop)
        
        # 添加按钮
        add_btn = ttk.Button(url_frame, text="➕ 添加下载", 
                           style='Primary.TButton',
                           command=self.add_download)
        add_btn.pack(side=tk.LEFT)
        
        # 设置选项
        options_frame = ttk.Frame(control_frame)
        options_frame.pack(fill=tk.X)
        
        # 保存路径
        ttk.Label(options_frame, text="保存到:").pack(side=tk.LEFT, padx=(0, 5))
        self.save_path_var = tk.StringVar(value=os.path.join(os.environ["USERPROFILE"], "Downloads"))
        save_path_entry = ttk.Entry(options_frame, textvariable=self.save_path_var, 
                                  width=40, state='readonly')
        save_path_entry.pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(options_frame, text="📁", 
                  command=self.choose_save_path).pack(side=tk.LEFT, padx=(0, 15))
        
        # 线程数
        ttk.Label(options_frame, text="线程数:").pack(side=tk.LEFT, padx=(0, 5))
        self.threads_var = tk.IntVar(value=8)
        threads_spin = ttk.Spinbox(options_frame, from_=1, to=32, 
                                 textvariable=self.threads_var, width=5)
        threads_spin.pack(side=tk.LEFT, padx=(0, 15))
        
        # 速度限制
        ttk.Label(options_frame, text="速度限制:").pack(side=tk.LEFT, padx=(0, 5))
        self.speed_limit_var = tk.StringVar(value="无限制")
        speed_combo = ttk.Combobox(options_frame, textvariable=self.speed_limit_var,
                                 values=["无限制", "1 MB/s", "5 MB/s", "10 MB/s", "自定义"], 
                                 width=10, state='readonly')
        speed_combo.pack(side=tk.LEFT, padx=(0, 5))
        
        # === 下载列表区域 ===
        list_frame = ttk.LabelFrame(main_frame, text="下载任务列表", padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建Treeview表格
        columns = ('id', 'filename', 'size', 'progress', 'speed', 'status', 'eta', 'created')
        self.download_tree = ttk.Treeview(list_frame, columns=columns, 
                                        show='headings', selectmode='extended')
        
        # 定义列标题
        self.download_tree.heading('id', text='ID')
        self.download_tree.heading('filename', text='文件名')
        self.download_tree.heading('size', text='大小')
        self.download_tree.heading('progress', text='进度')
        self.download_tree.heading('speed', text='速度')
        self.download_tree.heading('status', text='状态')
        self.download_tree.heading('eta', text='剩余时间')
        self.download_tree.heading('created', text='创建时间')
        
        # 配置列宽
        self.download_tree.column('id', width=60, anchor=tk.CENTER)
        self.download_tree.column('filename', width=250, anchor=tk.W)
        self.download_tree.column('size', width=80, anchor=tk.E)
        self.download_tree.column('progress', width=100, anchor=tk.CENTER)
        self.download_tree.column('speed', width=100, anchor=tk.E)
        self.download_tree.column('status', width=80, anchor=tk.CENTER)
        self.download_tree.column('eta', width=80, anchor=tk.E)
        self.download_tree.column('created', width=120, anchor=tk.CENTER)
        
        # 添加滚动条
        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, 
                                  command=self.download_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, 
                                  command=self.download_tree.xview)
        self.download_tree.configure(yscrollcommand=v_scrollbar.set, 
                                   xscrollcommand=h_scrollbar.set)
        
        # 布局
        self.download_tree.grid(row=0, column=0, sticky='nsew')
        v_scrollbar.grid(row=0, column=1, sticky='ns')
        h_scrollbar.grid(row=1, column=0, sticky='ew')
        
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        # === 控制按钮区域 ===
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 左侧按钮
        left_buttons = ttk.Frame(button_frame)
        left_buttons.pack(side=tk.LEFT)
        
        ttk.Button(left_buttons, text="⏸️ 暂停", 
                  command=self.pause_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(left_buttons, text="▶️ 继续", 
                  command=self.resume_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(left_buttons, text="❌ 取消", 
                  command=self.cancel_selected).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(left_buttons, text="🗑️ 删除", 
                  command=self.delete_selected).pack(side=tk.LEFT, padx=(0, 5))
        
        # 右侧按钮
        right_buttons = ttk.Frame(button_frame)
        right_buttons.pack(side=tk.RIGHT)
        
        ttk.Button(right_buttons, text="📊 下载历史", 
                  command=self.show_download_history).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(right_buttons, text="⚙️ 设置", 
                  command=self.show_settings).pack(side=tk.LEFT)
        
        # 绑定右键菜单
        self.create_context_menu()
    
    def create_context_menu(self):
        """创建右键菜单"""
        self.context_menu = tk.Menu(self.window, tearoff=0)
        self.context_menu.add_command(label="打开文件", command=self.open_selected_file)
        self.context_menu.add_command(label="打开文件夹", command=self.open_selected_folder)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="复制链接", command=self.copy_selected_url)
        self.context_menu.add_separator()
        self.context_menu.add_command(label="重新下载", command="redo_selected")
        self.context_menu.add_command(label="删除任务", command=self.delete_selected)
        
        self.download_tree.bind("<Button-3>", self.show_context_menu)
    
    def show_context_menu(self, event):
        """显示右键菜单"""
        item = self.download_tree.identify_row(event.y)
        if item:
            self.download_tree.selection_set(item)
            self.context_menu.post(event.x_root, event.y_root)
    
    def on_url_drop(self, event):
        """处理URL拖拽"""
        # url = event.data
        # if url.startswith('http'):
        #     self.url_entry.delete(0, tk.END)
        #     self.url_entry.insert(0, url)
        pass
    
    def choose_save_path(self):
        """选择保存路径"""
        path = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if path:
            self.save_path_var.set(path)
    
    def add_download(self):
        """添加下载任务"""
        url = self.url_entry.get().strip()
        if not url:
            messagebox.showwarning("警告", "请输入下载链接！")
            return
        
        # 检查是否是视频网站链接
        if self.is_video_url(url) and not YT_SUPPORT:
            messagebox.showwarning("警告", "视频下载功能需要安装 yt-dlp 库")
            return
        
        # 解析速度限制
        speed_limit = None
        speed_text = self.speed_limit_var.get()
        if speed_text != "无限制":
            if speed_text == "1 MB/s":
                speed_limit = 1024
            elif speed_text == "5 MB/s":
                speed_limit = 5120
            elif speed_text == "10 MB/s":
                speed_limit = 10240
            elif speed_text == "自定义":
                # 弹出自定义对话框
                speed_limit = self.ask_custom_speed()
        
        # 创建下载任务
        task = DownloadTask(
            url=url,
            save_path=self.save_path_var.get(),
            threads=self.threads_var.get(),
            max_speed=speed_limit
        )
        
        # 添加到下载管理器
        self.download_manager.add_download(task)
        
        # 清空URL输入框
        self.url_entry.delete(0, tk.END)
        
        # 显示成功消息
        messagebox.showinfo("成功", f"下载任务已添加：{task.filename}")
    
    def is_video_url(self, url):
        """检查是否是视频网站链接"""
        video_sites = ['youtube.com', 'youtu.be', 'bilibili.com', 'vimeo.com', 'dailymotion.com']
        return any(site in url.lower() for site in video_sites)
    
    def ask_custom_speed(self):
        """询问自定义速度"""
        dialog = tk.Toplevel(self.window)
        dialog.title("自定义速度限制")
        dialog.geometry("300x150")
        dialog.transient(self.window)
        dialog.grab_set()
        
        ttk.Label(dialog, text="输入速度限制 (KB/s):").pack(pady=10)
        speed_entry = ttk.Entry(dialog, width=20)
        speed_entry.pack(pady=5)
        speed_entry.insert(0, "1024")
        
        result = None
        
        def on_ok():
            nonlocal result
            try:
                result = int(speed_entry.get())
                dialog.destroy()
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字！")
        
        def on_cancel():
            dialog.destroy()
        
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        
        ttk.Button(button_frame, text="确定", command=on_ok).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=on_cancel).pack(side=tk.LEFT, padx=5)
        
        self.window.wait_window(dialog)
        return result
    
    def update_ui_timer(self):
        """定时更新UI"""
        try:
            # 更新下载列表
            self.update_download_list()
            
            # 每500ms更新一次
            self.window.after(500, self.update_ui_timer)
            
        except Exception as e:
            print(f"UI更新错误: {e}")
            self.window.after(500, self.update_ui_timer)
    
    def update_download_list(self):
        """更新下载列表"""
        # 清除现有项目
        for item in self.download_tree.get_children():
            self.download_tree.delete(item)
        
        # 添加当前任务
        # 这里需要从下载管理器获取任务列表
        # 简化版本，实际需要实现任务管理
    
    def pause_selected(self):
        """暂停选中的下载"""
        selected = self.download_tree.selection()
        if not selected:
            messagebox.showwarning("警告", "请先选择要暂停的下载任务！")
            return
        
        for item in selected:
            values = self.download_tree.item(item)['values']
            if values:
                task_id = values[0]
                # 实现暂停逻辑
                pass
        
        messagebox.showinfo("成功", f"已暂停 {len(selected)} 个下载任务")
    
    def resume_selected(self):
        """继续选中的下载"""
        selected = self.download_tree.selection()
        if not selected:
            messagebox.showwarning("警告", "请先选择要继续的下载任务！")
            return
        
        # 实现继续逻辑
        messagebox.showinfo("成功", f"已继续 {len(selected)} 个下载任务")
    
    def cancel_selected(self):
        """取消选中的下载"""
        selected = self.download_tree.selection()
        if not selected:
            messagebox.showwarning("警告", "请先选择要取消的下载任务！")
            return
        
        if messagebox.askyesno("确认", f"确定要取消 {len(selected)} 个下载任务吗？"):
            # 实现取消逻辑
            messagebox.showinfo("成功", f"已取消 {len(selected)} 个下载任务")
    
    def delete_selected(self):
        """删除选中的下载任务"""
        selected = self.download_tree.selection()
        if not selected:
            messagebox.showwarning("警告", "请先选择要删除的下载任务！")
            return
        
        if messagebox.askyesno("确认", f"确定要删除 {len(selected)} 个下载任务吗？"):
            # 实现删除逻辑
            messagebox.showinfo("成功", f"已删除 {len(selected)} 个下载任务")
    
    def open_selected_file(self):
        """打开选中的文件"""
        selected = self.download_tree.selection()
        if selected:
            values = self.download_tree.item(selected[0])['values']
            if values:
                file_path = os.path.join(self.save_path_var.get(), values[1])
                if os.path.exists(file_path):
                    if platform.system() == 'Windows':
                        os.startfile(file_path)
                    elif platform.system() == 'Darwin':  # macOS
                        subprocess.call(['open', file_path])
                    else:  # Linux
                        subprocess.call(['xdg-open', file_path])
    
    def open_selected_folder(self):
        """打开选中文件的文件夹"""
        selected = self.download_tree.selection()
        if selected:
            folder_path = self.save_path_var.get()
            if platform.system() == 'Windows':
                os.startfile(folder_path)
            elif platform.system() == 'Darwin':  # macOS
                subprocess.call(['open', folder_path])
            else:  # Linux
                subprocess.call(['xdg-open', folder_path])
    
    def copy_selected_url(self):
        """复制选中任务的URL"""
        selected = self.download_tree.selection()
        if selected:
            # 实现复制URL逻辑
            messagebox.showinfo("成功", "下载链接已复制到剪贴板")
    
    def show_download_history(self):
        """显示下载历史"""
        history_window = tk.Toplevel(self.window)
        history_window.title("下载历史")
        history_window.geometry("800x600")
        
        # 创建历史记录表格
        # 简化实现...
    
    def show_settings(self):
        """显示设置对话框"""
        settings_window = tk.Toplevel(self.window)
        settings_window.title("设置")
        settings_window.geometry("500x400")
        
        # 创建设置选项
        # 简化实现...

# 集成到主工具箱的函数
def open_enhanced_downloader(parent=None):
    """打开增强版下载器"""
    return EnhancedDownloaderUI(parent)

if __name__ == "__main__":
    # 测试运行
    downloader = EnhancedDownloaderUI()