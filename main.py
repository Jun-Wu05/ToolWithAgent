import os
import tkinter as tk
from reference.gui.data_processor import DataProcessor
from reference.gui.gui_handler import GUIHandler

class MappingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("JSON数据映射工具")
        self.root.geometry("800x600")
        self.root.minsize(600, 500)
        
        # 创建数据处理器
        self.data_processor = DataProcessor(self)
        
        # 创建GUI处理器
        self.gui_handler = GUIHandler(root, self.data_processor)
        
        # 暴露必要的属性和方法给数据处理器
        self.base64_file_path = self.gui_handler.base64_file_path
        self.excel_file_path = self.gui_handler.excel_file_path
        self.index_value = self.gui_handler.index_value
        self.output_json = self.gui_handler.output_json
        self.processing = self.gui_handler.processing
        
    def log_message(self, message):
        """线程安全的日志输出"""
        self.gui_handler.log_message(message)
    
    def finish_processing(self):
        """处理完成后恢复UI状态"""
        self.gui_handler.finish_processing()

def main():
    # 创建主窗口
    root = tk.Tk()
    root.configure(bg='white')  # 设置主窗口背景为白色
    
    # 设置应用样式
    try:
        from tkinter import ttk
        style = ttk.Style()
        
        # 配置样式为白色背景
        style.configure('TFrame', background='white')
        style.configure('TLabel', background='white')
        style.configure('TButton', background='white')
        style.configure('TEntry', fieldbackground='white')
        style.configure('TCheckbutton', background='white')
        style.configure('Horizontal.TProgressbar', background='lightgray')
    except tk.TclError as e:
        print(f"设置主题时出错: {e}")
    
    app = MappingApp(root)
    
    # 运行应用
    root.mainloop()

if __name__ == "__main__":
    # 设置Windows控制台编码（仅当需要在控制台显示非ASCII字符时）
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        except Exception:
            pass  # 忽略编码设置失败的错误
    
    # 只需调用一次main()
    main()