# tools/duplicate_finder/__init__.py
from duplicate_ui import FileDuplicateFinderUI
import tkinter as tk

def open_duplicate_finder(parent=None):
    """主工具箱统一入口"""
    root = tk.Toplevel(parent) if parent else tk.Tk()
    FileDuplicateFinderUI(root)
    if not parent:
        root.mainloop()