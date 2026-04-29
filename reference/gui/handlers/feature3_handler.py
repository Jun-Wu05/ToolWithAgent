import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pandas as pd
import json
import os
import openpyxl
import threading
import time
from datetime import datetime
import chardet

class Feature3Handler:
    def __init__(self, main_gui):
        self.main_gui = main_gui
        self.dev_frame = None
        self.csv_frame = None
    
    def show_development_panel(self):
        # 获取内容区域 - 修复属性访问路径
        content_frame = self.main_gui.field_mapping.field_mapping_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            widget.pack_forget()
        
        # 创建开发中面板
        self.dev_frame = ttk.Frame(content_frame)
        self.dev_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建垂直居中的标签容器
        label_frame = ttk.Frame(self.dev_frame)
        label_frame.pack(expand=True)
        
        ttk.Label(
            label_frame,
            text="开发中...",
            font=("SimHei", 16, "bold")
        ).pack(pady=20)
        
        ttk.Label(
            label_frame,
            text="该功能正在开发中，敬请期待",
            font=("SimHei", 10)
        ).pack()
    
    def show_csv_conversion_panel(self):
        # 获取内容区域
        content_frame = self.main_gui.field_mapping.field_mapping_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            widget.pack_forget()
        
        # 只在第一次创建时创建面板
        if not hasattr(self, 'csv_frame') or not self.csv_frame:
            self.create_csv_panel(content_frame)
        else:
            self.csv_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
    
    def create_csv_panel(self, content_frame):
        """创建CSV转换面板"""
        # 创建CSV转换面板
        self.csv_frame = ttk.Frame(content_frame)
        self.csv_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)
        
        # 标题
        ttk.Label(
            self.csv_frame,
            text="CSV转JSON格式工具",
            font=("SimHei", 16, "bold")
        ).pack(pady=(0, 20))
        
        # 模式选择
        mode_frame = ttk.Frame(self.csv_frame)
        mode_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(mode_frame, text="处理模式:", 
                 font=("SimHei", 10, "bold")).pack(side=tk.LEFT, padx=(0, 10))
        
        self.process_mode = tk.StringVar(value="single")
        ttk.Radiobutton(mode_frame, text="单文件处理", variable=self.process_mode,
                       value="single", command=self.switch_mode).pack(side=tk.LEFT, padx=5)
        ttk.Radiobutton(mode_frame, text="批量处理（自动识别）", variable=self.process_mode,
                       value="batch", command=self.switch_mode).pack(side=tk.LEFT, padx=5)
        
        # 单文件选择区域
        self.single_file_frame = ttk.Frame(self.csv_frame)
        self.single_file_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(self.single_file_frame, text="文件路径:").pack(side=tk.LEFT)
        self.csv_path_var = tk.StringVar()
        ttk.Entry(self.single_file_frame, textvariable=self.csv_path_var,
                       width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(self.single_file_frame, text="浏览", command=self.browse_csv_file).pack(side=tk.LEFT)

        # 文件夹选择区域
        self.batch_frame = ttk.Frame(self.csv_frame)
        
        folder_frame = ttk.Frame(self.batch_frame)
        folder_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(folder_frame, text="输入路径（文件或文件夹）:").pack(side=tk.LEFT)
        self.folder_path_var = tk.StringVar()
        self.folder_path_entry = ttk.Entry(folder_frame, textvariable=self.folder_path_var, width=50)
        self.folder_path_entry.pack(side=tk.LEFT, padx=5)
        ttk.Button(folder_frame, text="浏览", command=self.browse_folder).pack(side=tk.LEFT)
        
        # 绑定输入路径变化事件
        self.folder_path_var.trace_add("write", self._on_input_path_changed)
        
        # 输出文件夹区域
        batch_output_frame = ttk.Frame(self.batch_frame)
        batch_output_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(batch_output_frame, text="输出文件夹:").pack(side=tk.LEFT)
        self.batch_output_var = tk.StringVar()
        ttk.Entry(batch_output_frame, textvariable=self.batch_output_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(batch_output_frame, text="浏览", command=self.browse_output_folder).pack(side=tk.LEFT)

        # 单文件输出区域
        output_frame = ttk.Frame(self.csv_frame)
        output_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(output_frame, text="输出JSON文件:").pack(side=tk.LEFT)
        self.json_path_var = tk.StringVar()
        ttk.Entry(output_frame, textvariable=self.json_path_var, width=50).pack(side=tk.LEFT, padx=5)
        ttk.Button(output_frame, text="浏览", command=self.browse_json_file).pack(side=tk.LEFT)
        
        # 进度显示区域（批量处理时使用）
        self.progress_frame = ttk.Frame(self.csv_frame)
        
        progress_info_frame = ttk.Frame(self.progress_frame)
        progress_info_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(progress_info_frame, text="处理进度:").pack(side=tk.LEFT)
        self.progress_label = ttk.Label(progress_info_frame, text="0/0 (0%)")
        self.progress_label.pack(side=tk.LEFT, padx=10)
        
        ttk.Label(progress_info_frame, text="成功:").pack(side=tk.LEFT, padx=(20, 0))
        self.success_count_label = ttk.Label(progress_info_frame, text="0", foreground="green")
        self.success_count_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(progress_info_frame, text="失败:").pack(side=tk.LEFT, padx=(10, 0))
        self.fail_count_label = ttk.Label(progress_info_frame, text="0", foreground="red")
        self.fail_count_label.pack(side=tk.LEFT, padx=5)
        
        ttk.Label(progress_info_frame, text="剩余时间:").pack(side=tk.LEFT, padx=(10, 0))
        self.time_remaining_label = ttk.Label(progress_info_frame, text="--:--")
        self.time_remaining_label.pack(side=tk.LEFT, padx=5)
        
        # 进度条
        self.progress_bar = ttk.Progressbar(self.progress_frame, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=5)
        
        # 转换按钮
        button_frame = ttk.Frame(self.csv_frame)
        button_frame.pack(pady=20)
        
        self.convert_button = ttk.Button(
            button_frame,
            text="开始转换",
            command=self.start_conversion,
            style="Accent.TButton"
        )
        self.convert_button.pack(side=tk.LEFT, padx=10)
        
        ttk.Button(
            button_frame,
            text="清空",
            command=self.clear_fields
        ).pack(side=tk.LEFT, padx=10)
        
        ttk.Button(
            button_frame,
            text="停止",
            command=self.stop_conversion,
            state=tk.DISABLED
        ).pack(side=tk.LEFT, padx=10)
        
        # 状态显示
        self.status_var = tk.StringVar()
        self.status_var.set("准备就绪")
        ttk.Label(self.csv_frame, textvariable=self.status_var, foreground="blue").pack(pady=10)

        # 处理日志区域
        log_frame = ttk.LabelFrame(self.csv_frame, text="处理日志", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.csv_log_text = tk.Text(log_frame, height=8, width=60, font=("Consolas", 9))
        self.csv_log_text.pack(fill=tk.BOTH, expand=True)

        # 添加滚动条
        log_scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.csv_log_text.yview)
        self.csv_log_text.configure(yscrollcommand=log_scrollbar.set)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 初始化控制变量
        self.processing = False
        self.stop_requested = False
        
        # 添加日志方法
        self.log_csv_message("CSV转JSON工具已就绪")
        
        # 初始化模式
        self.switch_mode()
    
    def detect_encoding(self, file_path):
        """自动检测文件编码"""
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1', 'cp1252']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    # 尝试读取前几行来检测编码
                    f.read(1024)
                self.log_csv_message(f"检测到文件编码: {encoding}")
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        self.log_csv_message("警告: 无法自动检测编码，使用utf-8作为默认编码")
        return 'utf-8'

    def log_csv_message(self, message):
        """记录日志消息到CSV转换日志框"""
        if hasattr(self, 'csv_log_text') and self.csv_log_text:
            self.csv_log_text.insert(tk.END, message + "\n")
            self.csv_log_text.see(tk.END)
            self.main_gui.root.update()

    def browse_csv_file(self):
        file_path = filedialog.askopenfilename(
            title="选择文件",
            filetypes=[("支持格式", "*.csv *.xlsx"), ("CSV文件", "*.csv"),
                          ("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            self.csv_path_var.set(file_path)
            # 自动生成JSON文件路径
            if not self.json_path_var.get():
                if file_path.endswith('.xlsx'):
                    json_path = file_path.replace('.xlsx', '.txt')
                else:
                    json_path = file_path.replace('.csv', '.txt')
                self.json_path_var.set(json_path)
    
    def browse_json_file(self):
        file_path = filedialog.asksaveasfilename(
            title="保存JSON文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.json_path_var.set(file_path)
    
    def clear_fields(self):
        """清空所有输入框、输出框、文件列表和日志"""
        try:
            # 清空所有StringVar变量
            self.csv_path_var.set("")
            self.json_path_var.set("")
            self.folder_path_var.set("")
            self.batch_output_var.set("")
            self.status_var.set("准备就绪")
            
            # 清空日志文本框
            self.csv_log_text.delete(1.0, tk.END)
            
            # 重置处理状态
            self.processing = False
            self.stop_requested = False
            
            # 重置按钮状态
            if hasattr(self, 'convert_button'):
                self.convert_button.config(state=tk.NORMAL)
            if hasattr(self, 'stop_button'):
                self.stop_button.config(state=tk.DISABLED)
            
            # 重置进度条
            if hasattr(self, 'progress_bar'):
                self.progress_bar['value'] = 0
            
            # 重置进度标签
            if hasattr(self, 'progress_label'):
                self.progress_label.config(text="")
            
            # 重置文件列表显示
            if hasattr(self, 'file_list_text'):
                self.file_list_text.delete(1.0, tk.END)
            
            # 重置模式为单文件处理
            self.process_mode.set("single")
            self.switch_mode()
            
            # 添加清空成功日志
            self.log_csv_message("所有字段已清空，界面已重置")
            
        except Exception as e:
            # 静默处理异常，不记录错误日志
            pass
    
    def convert_csv_to_json(self):
        csv_path = self.csv_path_var.get()
        json_path = self.json_path_var.get()

        if not csv_path or not json_path:
            self.log_csv_message("错误: 请选择CSV文件和输出JSON文件路径")
            messagebox.showerror("错误", "请选择CSV文件和输出JSON文件路径")
            return

        if not os.path.exists(csv_path):
            self.log_csv_message(f"错误: CSV文件不存在: {csv_path}")
            messagebox.showerror("错误", f"CSV文件不存在: {csv_path}")
            return

        try:
            # 根据文件类型选择读取方式
            if csv_path.endswith('.xlsx'):
                self.log_csv_message(f"正在读取Excel文件: {csv_path}")
                self.status_var.set("正在读取Excel文件...")
                self.main_gui.root.update()

                # 读取Excel文件
                df = pd.read_excel(csv_path)
                self.log_csv_message(f"成功读取Excel文件，共 {len(df)} 行数据")
                self.status_var.set(f"成功读取Excel文件，共 {len(df)} 行数据")
            else:
                # 使用高级编码检测和utf-8-sig导出
                df = self._safe_read_csv_with_encoding(csv_path)
                self.log_csv_message(f"成功读取CSV文件，共 {len(df)} 行数据")
                self.status_var.set(f"成功读取CSV文件，共 {len(df)} 行数据")
                self.main_gui.root.update()

            # 转换数据格式
            self.log_csv_message("正在转换数据格式...")
            self.status_var.set("正在转换数据格式...")
            self.main_gui.root.update()

            # 转换为JSON格式（每行一个JSON对象）
            json_lines = []
            for _, row in df.iterrows():
                # 处理空值，将NaN转换为None
                row_dict = {}
                for col in df.columns:
                    value = row[col]
                    is_nan = bool(pd.isna(value))
                    if is_nan or value is None or value == '':
                        row_dict[col] = None
                    else:
                        # 处理字符串类型的特殊字符
                        if isinstance(value, str):
                            # 处理CSV中的转义序列
                            value = value.replace('\\0D\\0A', '\\\\0D\\\\0A')
                        row_dict[col] = value

                json_lines.append(json.dumps(row_dict, ensure_ascii=False))

            self.log_csv_message(f"数据转换完成，共 {len(json_lines)} 条记录")
            self.status_var.set("正在写入JSON文件...")
            self.main_gui.root.update()

            # 写入文件，每行一个JSON对象，使用utf-8-sig编码确保Excel打开不乱码
            with open(json_path, 'w', encoding='utf-8-sig') as f:
                for json_line in json_lines:
                    f.write(json_line + '\n')

            self.log_csv_message(f"JSON文件已保存: {json_path}")
            self.log_csv_message(f"转换完成！共转换 {len(json_lines)} 条记录")
            self.status_var.set(f"转换完成！共转换 {len(json_lines)} 条记录")
            messagebox.showinfo("成功", 
                             f"CSV文件已成功转换为JSON格式！\n输出文件: {json_path}\n共转换 {len(json_lines)} 条记录")

        except Exception as e:
            self.log_csv_message(f"错误: {str(e)}")
            self.status_var.set("转换失败")
            messagebox.showerror("错误", f"转换过程中发生错误:\n{str(e)}")

        # 最后更新一次UI
        self.main_gui.root.update()
    
    def switch_mode(self):
        """切换处理模式"""
        mode = self.process_mode.get()
        if mode == "single":
            # 显示单文件界面，隐藏批量界面
            self.single_file_frame.pack(fill=tk.X, pady=10)
            self.batch_frame.pack_forget()
            self.progress_frame.pack_forget()
            output_frame = self.csv_frame.winfo_children()[4]  # 单文件输出区域
            output_frame.pack(fill=tk.X, pady=10)
        else:
            # 显示批量界面，隐藏单文件界面
            self.single_file_frame.pack_forget()
            self.batch_frame.pack(fill=tk.X, pady=10)
            self.progress_frame.pack(fill=tk.X, pady=10)
            output_frame = self.csv_frame.winfo_children()[4]  # 单文件输出区域
            output_frame.pack_forget()
    
    def browse_folder(self):
        """选择文件或文件夹"""
        # 创建选择对话框
        dialog = tk.Toplevel(self.main_gui.root)
        dialog.title("选择输入路径")
        dialog.geometry("400x150")
        dialog.transient(self.main_gui.root)
        dialog.grab_set()
        
        def select_file():
            file_path = filedialog.askopenfilename(
                title="选择CSV或Excel文件",
                filetypes=[
                    ("支持的文件", "*.csv;*.xlsx;*.xls"),
                    ("CSV文件", "*.csv"),
                    ("Excel文件", "*.xlsx;*.xls"),
                    ("所有文件", "*.*")
                ]
            )
            if file_path:
                self.folder_path_var.set(file_path)
                # 自动生成输出文件夹路径（使用output子目录）
                if not self.batch_output_var.get():
                    output_folder = self._generate_output_path(file_path)
                    self.batch_output_var.set(output_folder)
            dialog.destroy()
        
        def select_folder():
            folder_path = filedialog.askdirectory(
                title="选择包含CSV文件的文件夹"
            )
            if folder_path:
                self.folder_path_var.set(folder_path)
                # 自动生成输出文件夹路径（使用output子目录）
                if not self.batch_output_var.get():
                    output_folder = self._generate_output_path(folder_path)
                    self.batch_output_var.set(output_folder)
            dialog.destroy()
        
        # 居中显示
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        
        # 添加按钮
        ttk.Label(dialog, text="请选择输入类型:", font=("SimHei", 12)).pack(pady=20)
        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=10)
        ttk.Button(button_frame, text="选择文件", command=select_file, width=15).pack(side=tk.LEFT, padx=10)
        ttk.Button(button_frame, text="选择文件夹", command=select_folder, width=15).pack(side=tk.LEFT, padx=10)
    
    def _generate_output_path(self, input_path):
        """生成输出文件夹路径，如果已存在则添加时间戳"""
        # 获取输入路径的父目录
        if os.path.isfile(input_path):
            parent_dir = os.path.dirname(input_path)
        else:
            parent_dir = input_path
        
        # 生成output文件夹路径
        output_folder = os.path.join(parent_dir, "output")
        
        # 检查文件夹是否存在，如果存在则添加时间戳
        if os.path.exists(output_folder):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_folder = os.path.join(parent_dir, f"output_{timestamp}")
        
        # 检查权限并创建文件夹
        try:
            os.makedirs(output_folder, exist_ok=True)
            # 清理历史输出文件（保留文件夹结构）
            self._clean_output_folder(output_folder)
            return output_folder
        except PermissionError:
            # 如果权限不足，使用用户文档目录
            user_docs = os.path.expanduser("~/Documents")
            output_folder = os.path.join(user_docs, "csv_json_output")
            os.makedirs(output_folder, exist_ok=True)
            return output_folder
        except Exception:
            # 其他异常，返回默认路径
            return os.path.join(parent_dir, "output")
    
    def _clean_output_folder(self, folder_path):
        """清理输出文件夹中的历史文件"""
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.endswith(('.json', '.txt', '.log')):
                        file_path = os.path.join(root, file)
                        try:
                            os.remove(file_path)
                        except:
                            pass
        except:
            pass
    
    def _on_input_path_changed(self, *args):
        """输入路径变化时的回调函数"""
        try:
            input_path = self.folder_path_var.get().strip()
            if not input_path:
                return
            
            # 检查路径是否存在
            if not os.path.exists(input_path):
                return
            
            # 获取当前输出路径
            current_output = self.batch_output_var.get().strip()
            
            # 如果输出路径为空或者是默认的converted_json路径，则自动更新
            if not current_output or "converted_json" in current_output:
                new_output = self._generate_output_path(input_path)
                self.batch_output_var.set(new_output)
                self.log_csv_message(f"输出路径已自动更新为: {new_output}")
        except:
            pass
    
    def browse_output_folder(self):
        """选择输出文件夹"""
        folder_path = filedialog.askdirectory(title="选择输出文件夹")
        if folder_path:
            self.batch_output_var.set(folder_path)
    
    def start_conversion(self):
        """开始转换（根据模式选择单文件或批量处理）"""
        if self.processing:
            return
        
        mode = self.process_mode.get()
        if mode == "single":
            self.convert_csv_to_json()
        else:
            # 在新线程中运行批量处理
            thread = threading.Thread(target=self.batch_convert_csv_to_json)
            thread.daemon = True
            thread.start()
    
    def stop_conversion(self):
        """停止转换"""
        self.stop_requested = True
        self.log_csv_message("正在停止处理...")
        self.convert_button.config(state=tk.DISABLED)
    
    def collect_csv_files(self, folder_path):
        """递归收集文件夹中的所有CSV文件"""
        csv_files = []
        try:
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith(('.csv', '.xlsx', '.xls')):
                        full_path = os.path.join(root, file)
                        rel_path = os.path.relpath(full_path, folder_path)
                        csv_files.append((full_path, rel_path))
        except Exception as e:
            self.log_csv_message(f"收集文件时出错: {str(e)}")
        
        return csv_files
    
    def detect_encoding_advanced(self, file_path):
        """高级编码检测"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(20000)  # 读取前20000字节进行检测
                result = chardet.detect(raw_data)
                detected_encoding = result['encoding']
                confidence = result['confidence']
                
                self.log_csv_message(f"检测到文件编码: {detected_encoding} (置信度: {confidence:.2f})")
                
                if confidence > 0.7:
                    return detected_encoding
        except Exception as e:
            self.log_csv_message(f"编码检测异常: {str(e)}")
        
        # 回退到基础检测
        encodings = ['utf-8', 'gbk', 'gb2312', 'gb18030', 'latin1', 'cp1252']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1024)
                self.log_csv_message(f"回退检测到编码: {encoding}")
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        self.log_csv_message("警告: 无法自动检测编码，使用utf-8作为默认编码")
        return 'utf-8'
    
    def _safe_read_csv_with_encoding(self, input_file):
        """安全读取CSV文件，自动检测编码并使用utf-8-sig导出"""
        try:
            # 1. 自动检测文件的原始编码
            self.log_csv_message(f"正在读取CSV文件: {input_file}")
            self.status_var.set("正在读取CSV文件...")
            self.main_gui.root.update()
            
            with open(input_file, 'rb') as f:
                raw_data = f.read(20000)  # 读取前20000字节进行检测
                result = chardet.detect(raw_data)
                encoding = result['encoding']
                confidence = result['confidence']
            
            self.log_csv_message(f"检测到文件编码: {encoding} (置信度: {confidence:.2f})")
            
            # 2. 根据检测结果读取文件
            # 优先尝试中文编码，特别是对于中文CSV文件
            encodings_to_try = []
            
            # 如果检测到GB系列编码，优先尝试
            if encoding and ('gb' in encoding.lower() or 'gbk' in encoding.lower()):
                encodings_to_try.append(encoding)
                encodings_to_try.append('gb18030')
                encodings_to_try.append('gbk')
                encodings_to_try.append('utf-8')
            else:
                # 否则按顺序尝试
                encodings_to_try.append(encoding)
                encodings_to_try.append('gb18030')
                encodings_to_try.append('gbk')
                encodings_to_try.append('utf-8')
            
            # 尝试不同的编码
            for enc in encodings_to_try:
                if not enc:
                    continue
                    
                try:
                    self.log_csv_message(f"尝试使用编码: {enc}")
                    df = pd.read_csv(input_file, encoding=enc, low_memory=False, on_bad_lines='skip')
                    self.log_csv_message(f"使用编码 {enc} 成功读取文件")
                    return df
                except Exception as e:
                    self.log_csv_message(f"编码 {enc} 读取失败: {str(e)}")
                    continue
            
            # 如果所有编码都失败，使用utf-8并忽略错误
            self.log_csv_message("所有编码尝试失败，使用utf-8并忽略错误")
            df = pd.read_csv(input_file, encoding='utf-8', errors='replace', low_memory=False, on_bad_lines='skip')
            return df
            
        except Exception as e:
            self.log_csv_message(f"读取CSV文件失败: {str(e)}")
            raise
    
    def update_progress(self, current, total, success_count, fail_count, start_time):
        """更新进度显示"""
        percentage = (current / total * 100) if total > 0 else 0
        self.progress_label.config(text=f"{current}/{total} ({percentage:.1f}%)")
        self.success_count_label.config(text=str(success_count))
        self.fail_count_label.config(text=str(fail_count))
        
        # 计算剩余时间
        if current > 0 and not self.stop_requested:
            elapsed_time = time.time() - start_time
            avg_time_per_file = elapsed_time / current
            remaining_files = total - current
            remaining_time = remaining_files * avg_time_per_file
            
            minutes = int(remaining_time // 60)
            seconds = int(remaining_time % 60)
            self.time_remaining_label.config(text=f"{minutes:02d}:{seconds:02d}")
        
        # 更新进度条
        self.progress_bar['value'] = percentage
        
        # 更新UI
        self.main_gui.root.update()
    
    def batch_convert_csv_to_json(self):
        """批量转换CSV文件到JSON，自动判断输入是文件还是文件夹"""
        try:
            # 获取输入和输出路径
            input_path = self.folder_path_var.get().strip()
            output_folder = self.batch_output_var.get().strip()
            
            if not input_path or not output_folder:
                self.log_csv_message("错误: 请选择输入路径和输出文件夹")
                messagebox.showerror("错误", "请选择输入路径和输出文件夹")
                return
            
            if not os.path.exists(input_path):
                self.log_csv_message(f"错误: 输入路径不存在: {input_path}")
                messagebox.showerror("错误", f"输入路径不存在: {input_path}")
                return
            
            # 创建输出文件夹
            os.makedirs(output_folder, exist_ok=True)
            
            # 判断输入是文件还是文件夹
            if os.path.isfile(input_path):
                # 单文件处理
                if not input_path.lower().endswith(('.csv', '.xlsx', '.xls')):
                    self.log_csv_message("错误: 不支持的文件格式")
                    messagebox.showerror("错误", "不支持的文件格式")
                    return
                
                csv_files = [(input_path, os.path.basename(input_path))]
                self.log_csv_message(f"检测到单文件: {os.path.basename(input_path)}")
            elif os.path.isdir(input_path):
                # 文件夹批量处理
                self.log_csv_message("正在收集CSV文件...")
                csv_files = self.collect_csv_files(input_path)
            else:
                self.log_csv_message("错误: 输入路径既不是文件也不是文件夹")
                messagebox.showerror("错误", "输入路径无效")
                return
            
            if not csv_files:
                self.log_csv_message("未找到任何CSV或Excel文件")
                messagebox.showinfo("提示", "未找到任何CSV或Excel文件")
                return
            
            total_files = len(csv_files)
            self.log_csv_message(f"找到 {total_files} 个文件，开始批量转换...")
            
            # 初始化处理状态
            self.processing = True
            self.stop_requested = False
            success_count = 0
            fail_count = 0
            failed_files = []
            start_time = time.time()
            
            # 更新UI状态
            self.convert_button.config(state=tk.DISABLED)
            self.status_var.set("正在批量处理...")
            self.progress_bar['maximum'] = 100
            
            # 处理每个文件
            for i, (file_path, rel_path) in enumerate(csv_files):
                if self.stop_requested:
                    self.log_csv_message("用户停止了处理")
                    break
                
                try:
                    # 生成输出文件路径
                    base_rel_path, ext = os.path.splitext(rel_path)
                    output_rel_path = base_rel_path + ".txt"
                    output_path = os.path.join(output_folder, output_rel_path)
                    
                    # 确保输出子文件夹存在
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    
                    # 更新当前处理状态
                    self.log_csv_message(f"正在处理 ({i+1}/{total_files}): {rel_path}")
                    
                    # 根据文件类型选择读取方式
                    if ext.lower() in ('.xlsx', '.xls'):
                        # Excel文件处理
                        df = pd.read_excel(file_path)
                    else:
                        # CSV文件处理
                        encoding = self.detect_encoding_advanced(file_path)
                        df = pd.read_csv(file_path, encoding=encoding)
                    
                    # 转换数据格式
                    json_lines = []
                    for _, row in df.iterrows():
                        row_dict = {}
                        for col in df.columns:
                            value = row[col]
                            if pd.isna(value) or value is None or value == '':
                                row_dict[col] = None
                            else:
                                # 处理Timestamp对象（Excel日期时间字段）
                                if hasattr(value, 'strftime'):
                                    value = value.strftime('%Y-%m-%d %H:%M:%S')
                                elif isinstance(value, str):
                                    value = value.replace('\\0D\\0A', '\\\\0D\\\\0A')
                                row_dict[col] = value
                        json_lines.append(json.dumps(row_dict, ensure_ascii=False))
                    
                    # 写入文件
                    with open(output_path, 'w', encoding='utf-8') as f:
                        for json_line in json_lines:
                            f.write(json_line + '\n')
                    
                    success_count += 1
                    self.log_csv_message(f"✓ 转换成功: {output_rel_path} ({len(json_lines)} 条记录)")
                    
                except Exception as e:
                    fail_count += 1
                    failed_files.append((rel_path, str(e)))
                    self.log_csv_message(f"✗ 转换失败: {rel_path} - {str(e)}")
                
                # 更新进度
                self.update_progress(i + 1, total_files, success_count, fail_count, start_time)
            
            # 生成汇总报告
            self.generate_summary_report(input_path, output_folder, total_files, 
                                       success_count, fail_count, failed_files, start_time)
            
            # 完成处理
            self.processing = False
            self.convert_button.config(state=tk.NORMAL)
            
            if not self.stop_requested:
                self.status_var.set(f"批量处理完成！成功: {success_count}, 失败: {fail_count}")
                messagebox.showinfo("完成", 
                    f"批量处理完成！\n成功: {success_count} 个文件\n失败: {fail_count} 个文件\n详细报告已保存到输出文件夹")
            else:
                self.status_var.set("处理已停止")
            
        except Exception as e:
            self.log_csv_message(f"批量处理过程中发生错误: {str(e)}")
            self.status_var.set("处理失败")
            messagebox.showerror("错误", f"批量处理过程中发生错误:\n{str(e)}")
            self.processing = False
            self.convert_button.config(state=tk.NORMAL)
    
    def generate_summary_report(self, input_folder, output_folder, total_files, 
                              success_count, fail_count, failed_files, start_time):
        """生成汇总报告"""
        try:
            end_time = time.time()
            total_time = end_time - start_time
            
            report = {
                "summary": {
                    "input_folder": input_folder,
                    "output_folder": output_folder,
                    "total_files": total_files,
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "success_rate": f"{(success_count/total_files*100):.1f}%" if total_files > 0 else "0%",
                    "total_time_seconds": round(total_time, 2),
                    "avg_time_per_file": round(total_time/total_files, 2) if total_files > 0 else 0,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                },
                "failed_files": [
                    {"file": file_path, "error": error} 
                    for file_path, error in failed_files
                ]
            }
            
            # 保存JSON格式报告
            report_json_path = os.path.join(output_folder, "conversion_report.json")
            with open(report_json_path, 'w', encoding='utf-8-sig') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            # 保存CSV格式报告
            report_csv_path = os.path.join(output_folder, "conversion_report.csv")
            with open(report_csv_path, 'w', encoding='utf-8-sig') as f:
                f.write("项目,值\n")
                for key, value in report["summary"].items():
                    f.write(f"{key},{value}\n")
                f.write("\n失败文件列表:\n")
                f.write("文件路径,错误信息\n")
                for file_path, error in failed_files:
                    f.write(f"{file_path},{error}\n")
            
            self.log_csv_message(f"汇总报告已保存:")
            self.log_csv_message(f"  JSON格式: {os.path.basename(report_json_path)}")
            self.log_csv_message(f"  CSV格式: {os.path.basename(report_csv_path)}")
            
        except Exception as e:
            self.log_csv_message(f"生成汇总报告时出错: {str(e)}")

    def toolbar_btn3_click(self):
        # 替换为CSV转换功能
        self.show_csv_conversion_panel()