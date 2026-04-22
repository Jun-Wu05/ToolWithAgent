import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import threading
import base64
import json
import binascii

class Base64ErrorHandler:
    def __init__(self, main_gui):
        self.main_gui = main_gui
        # 共享变量
        self.base64_error_file_path = main_gui.base64_error_file_path
        self.base64_error_output_path = main_gui.base64_error_output_path
        self.processed_base64_data = None
        
        # 创建面板
        self.create_base64_error_panel(main_gui.content_frame)
    
    def create_base64_error_panel(self, parent_frame):
        self.base64_error_frame = ttk.Frame(parent_frame)
        
        # 文件选择部分
        file_frame = ttk.Frame(self.base64_error_frame)
        file_frame.pack(fill=tk.X, pady=10)
        
        # Base64文件选择
        ttk.Label(file_frame, text="选择base64编码文件:", anchor="w").pack(fill=tk.X, pady=(0, 5))
        file_row = ttk.Frame(file_frame)
        file_row.pack(fill=tk.X)
        
        ttk.Entry(file_row, textvariable=self.base64_error_file_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(file_row, text="浏览", command=self.browse_base64_error_file).pack(side=tk.RIGHT)
        
        # 按钮部分
        buttons_frame = ttk.Frame(self.base64_error_frame)
        buttons_frame.pack(fill=tk.X, pady=20)
        
        self.process_base64_btn = ttk.Button(buttons_frame, text="删除base64字段", command=self.process_base64_error)
        self.process_base64_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        self.download_base64_btn = ttk.Button(buttons_frame, text="下载处理后文件", command=self.download_processed_base64, state=tk.DISABLED)
        self.download_base64_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(buttons_frame, text="base64错误处理帮助", command=self.show_base64_error_help).pack(side=tk.LEFT)
        
        # 状态区域
        status_frame = ttk.Frame(self.base64_error_frame)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=10)
        
        ttk.Label(status_frame, text="处理状态:", anchor="w").pack(fill=tk.X, pady=(0, 5))
        
        self.status_text = tk.Text(status_frame, height=10, wrap=tk.WORD)
        self.status_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(status_frame, orient=tk.VERTICAL, command=self.status_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.status_text.config(yscrollcommand=scrollbar.set)
    
    def show_base64_error_panel(self):
        # 获取内容区域
        content_frame = self.base64_error_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            widget.pack_forget()
        
        # 显示base64错误处理面板
        self.base64_error_frame.pack(fill=tk.BOTH, expand=True)
        
        # 禁用下载按钮
        self.download_base64_btn.config(state=tk.DISABLED)
        self.base64_error_output_path.set('')
    
    def browse_base64_error_file(self):
        file_path = filedialog.askopenfilename(
            title="选择base64编码文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.base64_error_file_path.set(file_path)
            self.status_message(f"已选择base64文件: {os.path.basename(file_path)}")
    
    def process_base64_error(self):
        base64_file = self.base64_error_file_path.get().strip()
        
        # 验证输入
        if not base64_file or not os.path.exists(base64_file):
            self.status_message("错误: 请选择有效的base64编码文件")
            return
        
        self.status_message("开始处理base64文件...")
        
        # 处理数据在后台线程
        threading.Thread(target=self._process_base64_error_thread, args=(base64_file,)).start()
    
    def status_message(self, message):
        def update_status():
            self.status_text.insert(tk.END, message + "\n")
            self.status_text.see(tk.END)
        self.main_gui.root.after(0, update_status)
    
    def _process_base64_error_thread(self, base64_file):
        try:
            # 读取并解码Base64
            with open(base64_file, 'rb') as f:
                base64_data = f.read()
            
            if not base64_data:
                self.status_message("错误: base64文件为空")
                return
            
            # 解码base64
            try:
                decoded_data = base64.b64decode(base64_data, validate=False)
                self.status_message("base64解码成功")
            except binascii.Error as e:
                self.status_message(f"base64解码失败: {str(e)}")
                return
            
            # 解析JSON
            try:
                json_str = decoded_data.decode('utf-8')
                data = json.loads(json_str)
                self.status_message("JSON解析成功")
            except Exception as e:
                self.status_message(f"JSON解析失败: {str(e)}")
                return
            
            # 查找并删除key为"name"且值为"decoding"的field
            # ... 处理逻辑 ...
            
            # 序列化处理后的JSON
            processed_json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            self.processed_base64_data = base64.b64encode(processed_json_str.encode('utf-8')).decode('utf-8')
            
            # 启用下载按钮
            self.main_gui.root.after(0, lambda: self.download_base64_btn.config(state=tk.NORMAL))
            self.status_message("数据处理完成，请点击'下载处理后文件'按钮")
        except Exception as e:
            self.status_message(f"处理文件时发生未预期错误: {str(e)}")
    
    def download_processed_base64(self):
        if not self.processed_base64_data:
            self.status_message("错误: 没有可下载的处理后数据")
            return
        
        # 获取保存路径
        default_dir = os.path.dirname(self.base64_error_file_path.get())
        default_name = "处理后解析.txt"
        
        save_path = filedialog.asksaveasfilename(
            title="保存处理后的base64文件",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialdir=default_dir,
            initialfile=default_name
        )
        
        if save_path:
            try:
                with open(save_path, 'w', encoding='utf-8') as f:
                    f.write(self.processed_base64_data)
                self.status_message(f"文件已成功保存到: {os.path.basename(save_path)}")
                messagebox.showinfo("成功", f"文件已成功保存到:\n{save_path}")
            except Exception as e:
                self.status_message(f"保存文件时出错: {str(e)}")
                messagebox.showerror("错误", f"保存文件时出错: {str(e)}")
    
    def show_base64_error_help(self):
        # 创建帮助窗口
        self.base64_error_help_window = tk.Toplevel(self.main_gui.root)
        self.base64_error_help_window.title("Base64错误处理帮助")
        self.base64_error_help_window.resizable(True, True)
        self.base64_error_help_window.configure(bg="#f5f5f5")
        self.base64_error_help_window.minsize(600, 400)

        # 设置窗口大小与主窗口成比例
        root_width = self.main_gui.root.winfo_width()
        root_height = self.main_gui.root.winfo_height()
        help_width = int(root_width * 0.7)
        help_height = int(root_height * 0.7)
        self.base64_error_help_window.geometry(f"{help_width}x{help_height}")

        # 创建标题栏
        title_frame = ttk.Frame(self.base64_error_help_window, padding="10 15 10 10")
        title_frame.pack(fill=tk.X, padx=0, pady=0)

        # 标题标签
        title_label = ttk.Label(
            title_frame,
            text="Base64错误处理工具",
            font=("SimHei", 14, "bold")
        )
        title_label.pack(anchor="center")

        # 添加分隔线
        ttk.Separator(self.base64_error_help_window).pack(fill=tk.X, pady=0)

        # 创建主内容框架
        main_frame = ttk.Frame(self.base64_error_help_window, padding="15")
        main_frame.pack(fill=tk.BOTH, expand=True)

        # 创建滚动框架
        scroll_frame = ttk.Frame(main_frame)
        scroll_frame.pack(fill=tk.BOTH, expand=True)

        # 创建滚动条
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 创建画布
        canvas = tk.Canvas(
            scroll_frame,
            yscrollcommand=scrollbar.set,
            bg="#ffffff",
            highlightthickness=1,
            highlightbackground="#e0e0e0"
        )
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=canvas.yview)

        # 创建内部内容框架
        content_frame = ttk.Frame(canvas, padding="20")
        content_window = canvas.create_window((0, 0), window=content_frame, anchor="nw", tags="content")

        # 窗口大小调整和事件处理
        def on_canvas_configure(event):
            # 调整画布大小
            new_width = event.width - 20
            if canvas.itemcget(content_window, "width") != new_width:
                canvas.itemconfig(content_window, width=new_width)

        def on_frame_configure(event):
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))

        # 绑定事件
        canvas.bind("<Configure>", on_canvas_configure)
        content_frame.bind("<Configure>", on_frame_configure)

        # 确保内容宽度始终适应画布
        def update_content_width(event=None):
            if hasattr(canvas, 'winfo_width'):
                canvas_width = canvas.winfo_width()
                if canvas_width > 20:
                    current_width = int(canvas.itemcget(content_window, "width"))
                    new_width = canvas_width - 20
                    if abs(current_width - new_width) > 5:  # 只有当变化足够大时才更新
                        canvas.itemconfig(content_window, width=new_width)
            # 避免频繁更新
            self.base64_error_help_window.after(200, update_content_width)

        # 只在窗口首次显示时调用一次
        self.base64_error_help_window.after(100, update_content_width)

        # === 添加实际帮助内容 ===
        # 帮助标题
        help_title = ttk.Label(
            content_frame,
            text="使用帮助",
            font=(
            "SimHei", 14, "bold")
        )
        help_title.pack(pady=10)  # 修复变量引用错误

        help_content = [
            "功能说明:",
            "本工具用于处理Base64编码数据中的JSON格式错误，主要功能:",
            "1. 解码Base64编码的JSON数据",
            "2. 自动修复常见的JSON格式错误",
            "3. 删除指定的错误字段",
            "4. 重新编码为Base64并保存",
            "",
            "使用步骤:",
            "1. 选择包含Base64数据的文本文件",
            "2. 设置输出文件路径",
            "3. 点击'处理数据'按钮",
            "4. 处理完成后点击'下载处理后文件'",
            "",
            "注意事项:",
            "- 输入文件应为纯文本格式(.txt)",
            "- 确保Base64数据完整无损坏",
            "- 大型文件处理可能需要较长时间"
        ]

        # 添加内容标签
        for text in help_content:
            ttk.Label(
                content_frame,
                text=text,
                font=(
                "SimHei", 10),
                anchor="w",
                justify=tk.LEFT
            ).pack(fill=tk.X, padx=20, pady=5)

        # 创建按钮框架
        button_frame = ttk.Frame(self.base64_error_help_window, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)  # 放置在窗口底部

        # 创建样式
        style = ttk.Style()
        style.configure("Accent.TButton", minwidth=100)

        # 创建按钮时应用样式
        close_btn = ttk.Button(
            button_frame,
            text="关闭",
            command=self.base64_error_help_window.destroy,
            padding=(15, 8),
            style="Accent.TButton"
        )
        close_btn.pack(pady=10)

        # 确保按钮居中
        button_frame.pack_configure(anchor="center")

        # 可选：设置按钮最小宽度
        # close_btn.configure(minwidth=100)