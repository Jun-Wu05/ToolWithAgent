import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import threading
from src.handlers.field_mapping_handler import FieldMappingHandler
from src.handlers.base64_error_handler import Base64ErrorHandler
from src.handlers.feature3_handler import Feature3Handler
from src.handlers.standard_field_mapping_handler import StandardFieldMappingHandler
from src.handlers.feature5_mappingall import Feature5MappingAll

class GUIHandler:
    def __init__(self, root, data_processor):
        self.root = root
        self.data_processor = data_processor
        self.processing = False
        self.base64_error_help_window = None
        
        # 创建变量
        self.base64_file_path = tk.StringVar()
        self.excel_file_path = tk.StringVar()
        self.index_value = tk.StringVar(value="content.sessionproto")
        self.output_json = tk.BooleanVar(value=False)
        
        # 功能2变量
        self.base64_error_file_path = tk.StringVar()
        self.base64_error_output_path = tk.StringVar()
        
        # 创建UI
        self.create_widgets()
        
        # 这些UI组件将在create_widgets方法中创建
        # self.title_label 和 self.log_frame 会在create_widgets中初始化
    
    def create_widgets(self):
        """创建UI组件"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 左侧工具栏
        toolbar_frame = ttk.Frame(main_frame, width=100)
        toolbar_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10), pady=5)
        
        # 右侧内容区域
        self.content_frame = ttk.Frame(main_frame)
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 初始化功能模块
        self.field_mapping = FieldMappingHandler(self)
        self.base64_error = Base64ErrorHandler(self)
        self.feature3 = Feature3Handler(self)
        self.standard_field_mapping = StandardFieldMappingHandler(self)
        self.feature5_mappingall = Feature5MappingAll(self)
        
        # 工具栏按钮
        ttk.Button(
            toolbar_frame, 
            text="标准字段映射", 
            command=self.standard_field_mapping.show_standard_field_mapping_panel, 
            width=15
        ).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar_frame, 
            text="字段枚举批量处理", 
            command=self.field_mapping.show_field_mapping_panel, 
            width=10
        ).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar_frame, 
            text="字段映射枚举集合", 
            command=self.feature5_mappingall.show_feature5_panel, 
            width=15
        ).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar_frame, 
            text="base64错误处理", 
            command=self.base64_error.show_base64_error_panel, 
            width=15
        ).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Button(
            toolbar_frame, 
            text="CSV格式转换", 
            command=self.feature3.toolbar_btn3_click, 
            width=15
        ).pack(fill=tk.X, pady=(0, 5))
        
        # 标题和公共UI组件
        self.title_label = ttk.Label(
            self.content_frame,
            text="解析工具",
            font=("SimHei", 16, "bold")
        )
        
        # 进度条
        self.progress = ttk.Progressbar(self.content_frame, mode="indeterminate")
        
        # 日志区域
        self.log_frame = ttk.Frame(self.content_frame)
        ttk.Label(self.log_frame, text="处理日志:", anchor="w").pack(fill=tk.X, pady=(0, 5))
        
        self.log_text = tk.Text(self.log_frame, height=10, wrap=tk.WORD)
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        scrollbar = ttk.Scrollbar(self.log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.config(yscrollcommand=scrollbar.set)
        
        # 初始显示字段映射面板
        self.field_mapping.show_field_mapping_panel()
        
    # 保留公共方法
    def log_message(self, message):
        def update_log():
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
        self.root.after(0, update_log)
    
    def clear_fields(self):
        if not self.processing:
            self.base64_file_path.set("")
            self.excel_file_path.set("")
            self.index_value.set("content.sessionproto")
            self.output_json.set(False)
            self.log_text.delete(1.0, tk.END)
            self.log_message("已清空所有字段")
        else:
            messagebox.showinfo("提示", "正在处理数据，请稍后再试")
    
    def start_process_thread(self):
        if not self.processing:
            self.processing = True
            self.field_mapping.process_btn.config(state=tk.DISABLED)
            self.progress.start()
            threading.Thread(target=self.data_processor.process_data, daemon=True).start()
        else:
            messagebox.showinfo("提示", "正在处理数据，请耐心等待")
    
    def finish_processing(self):
        self.processing = False
        self.field_mapping.process_btn.config(state=tk.NORMAL)
        self.progress.stop()

    def create_base64_error_panel(self, parent_frame):
        """创建base64错误处理面板"""
        self.base64_error_frame = ttk.Frame(parent_frame)
        
        # 标题
        ttk.Label(
            self.base64_error_frame,
            text="base64错误处理",
            font=('SimHei', 12, 'bold')
        ).pack(pady=10)
        
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
        """显示base64错误处理面板"""
        # 获取内容区域
        content_frame = self.base64_error_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            widget.pack_forget()
        
        # 确保组件存在后再显示
        if hasattr(self, 'title_label') and self.title_label:
            self.title_label.pack(pady=10)
        
        # 显示base64错误处理面板
        self.base64_error_frame.pack(fill=tk.BOTH, expand=True)
        
        # 禁用下载按钮
        self.download_base64_btn.config(state=tk.DISABLED)
        self.base64_error_output_path.set('')

    def browse_base64_error_file(self):
        """浏览并选择base64错误处理文件"""
        file_path = filedialog.askopenfilename(
            title="选择base64编码文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.base64_error_file_path.set(file_path)
            self.status_message(f"已选择base64文件: {os.path.basename(file_path)}")

    def process_base64_error(self):
        """处理base64错误文件"""
        base64_file = self.base64_error_file_path.get().strip()
        
        # 验证输入
        if not base64_file or not os.path.exists(base64_file):
            self.status_message("错误: 请选择有效的base64编码文件")
            return
        
        self.status_message("开始处理base64文件...")
        
        # 处理数据在后台线程
        threading.Thread(target=self._process_base64_error_thread, args=(base64_file,)).start()
        
    def status_message(self, message):
        """线程安全的状态消息输出"""
        def update_status():
            self.status_text.insert(tk.END, message + "\n")
            self.status_text.see(tk.END)
        self.root.after(0, update_status)
    
    def _process_base64_error_thread(self, base64_file):
        """后台线程处理base64错误文件"""
        try:
            import base64
            import json
            import binascii
            
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
            try:
                # 遍历data中的每个规则
                if isinstance(data, list):
                    for rule in data:
                        # 查找parser.filter数组
                        if isinstance(rule, dict) and 'parser' in rule and isinstance(rule['parser'], dict):
                            parser = rule['parser']
                            if 'filter' in parser and isinstance(parser['filter'], list):
                                # 过滤掉name为decoding的项
                                original_count = len(parser['filter'])
                                # 存储被删除的field值
                                removed_fields = []
                                new_filter = []
                                for item in parser['filter']:
                                    if isinstance(item, dict) and item.get('name') == 'decoding':
                                        # 记录被删除的field值
                                        if 'field' in item:
                                            removed_fields.append(item['field'])
                                    else:
                                        new_filter.append(item)
                                
                                parser['filter'] = new_filter
                                removed_count = original_count - len(parser['filter'])
                                
                                # 为每个删除的field添加新的addFields JSON对象
                                for field in removed_fields:
                                    add_field_obj = {
                                        "name": "addFields",
                                        "fields": {
                                            field: f"<%@com.hansight.dataviewer.utils.Base64@Base64Decode({field})%>"
                                        }
                                    }
                                    parser['filter'].append(add_field_obj)
                                    self.status_message(f"成功添加name为'addFields'的field: {field}")
                                
                                if removed_count > 0:
                                    self.status_message(f"成功删除 {removed_count} 个name为'decoding'的field")
                                else:
                                    self.status_message("未找到name为'decoding'的field")
                else:
                    self.status_message("错误: JSON数据格式不正确，应为数组")
                    return
            except Exception as e:
                self.status_message(f"处理数据时出错: {str(e)}")
                return
            
            # 序列化处理后的JSON
            try:
                processed_json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
                # 编码为base64
                processed_base64 = base64.b64encode(processed_json_str.encode('utf-8')).decode('utf-8')
                
                # 保存到临时变量
                self.processed_base64_data = processed_base64
                self.base64_error_output_path.set('已处理完成')
                
                # 启用下载按钮
                self.root.after(0, lambda: self.download_base64_btn.config(state=tk.NORMAL))
                self.status_message("数据处理完成，请点击'下载处理后文件'按钮")
            except Exception as e:
                self.status_message(f"处理后数据编码失败: {str(e)}")
                return
        except Exception as e:
            self.status_message(f"处理文件时发生未预期错误: {str(e)}")

    def download_processed_base64(self):
        """下载处理后的base64文件"""
        if not hasattr(self, 'processed_base64_data') or not self.processed_base64_data:
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
        """显示base64错误处理帮助"""
        # 如果帮助窗口已存在，先关闭
        if hasattr(self, 'base64_error_help_window') and self.base64_error_help_window and self.base64_error_help_window.winfo_exists():
            self.base64_error_help_window.destroy()
        
        # 创建帮助窗口
        self.base64_error_help_window = tk.Toplevel(self.root)
        self.base64_error_help_window.title("base64错误处理帮助")
        
        # 设置窗口大小与主窗口成比例
        root_width = self.root.winfo_width()
        root_height = self.root.winfo_height()
        # 设置为父窗口的80%大小
        help_width = int(root_width * 0.8)
        help_height = int(root_height * 0.8)
        self.base64_error_help_window.geometry(f"{help_width}x{help_height}")
        
        # 当主窗口大小变化时，同步调整帮助窗口
        def update_help_window_size(event):
            # 检查帮助窗口是否存在且不为None
            if hasattr(self, 'base64_error_help_window') and self.base64_error_help_window:
                try:
                    # 调整窗口大小为主窗口的80%
                    new_width = int(event.width * 0.8)
                    new_height = int(event.height * 0.8)
                    self.base64_error_help_window.geometry(f"{new_width}x{new_height}")
                except tk.TclError:
                    # 如果窗口不存在，解绑事件
                    try:
                        self.root.unbind("<Configure>", update_help_window_id)
                    except tk.TclError:
                        pass  # 忽略解绑失败的错误
        
        # 绑定主窗口大小变化事件并保存绑定ID
        update_help_window_id = self.root.bind("<Configure>", update_help_window_size)
        
        # 当帮助窗口关闭时解绑事件
        def on_help_window_close():
            try:
                # 尝试解绑事件
                self.root.unbind("<Configure>", update_help_window_id)
            except tk.TclError:
                pass  # 忽略解绑失败的错误
            
            # 确保销毁的是正确的窗口
            if hasattr(self, 'base64_error_help_window') and self.base64_error_help_window:
                try:
                    self.base64_error_help_window.destroy()
                except tk.TclError:
                    pass  # 忽略销毁失败的错误
        self.base64_error_help_window.protocol("WM_DELETE_WINDOW", on_help_window_close)
        
        # 删除这行代码: help_window.destroy()
        
        # 以下是创建帮助窗口内容的代码...
        # help_window.destroy()  <-- 删除这行代码
        
        # 帮助窗口内容创建代码...
        # 创建滚动框架
        scroll_frame = ttk.Frame(self.base64_error_help_window)
        scroll_frame.pack(fill=tk.BOTH, expand=True)  # 确保填充整个窗口
        
        # 创建滚动条
        scrollbar = ttk.Scrollbar(scroll_frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建画布
        canvas = tk.Canvas(scroll_frame, yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)  # 确保填充并扩展
        
        # 配置滚动条
        scrollbar.config(command=canvas.yview)
        
        # 创建内部框架
        frame = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=frame, anchor="nw")
        
        # 更新画布大小
        def update_canvas_size(event):
            # 调整画布大小以适应窗口
            canvas.config(width=event.width, height=event.height)
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))
        frame.bind("<Configure>", update_canvas_size)
        
        # 创建标题
        title_label = ttk.Label(
            frame,
            text="base64错误处理功能帮助",
            font=('SimHei', 14, 'bold')
        )
        title_label.pack(pady=10)
        
        # 功能说明
        ttk.Label(frame, text="功能说明:", font=('SimHei', 10, 'bold')).pack(anchor="w", pady=(10, 5))
        ttk.Label(frame, text="   本功能用于处理JSON格式的base64编码文件，删除其中key为'name'且值为'decoding'的整个field。", anchor="w").pack(fill=tk.X)
        
        # 使用步骤
        ttk.Label(frame, text="使用步骤:", font=('SimHei', 10, 'bold')).pack(anchor="w", pady=(10, 5))
        steps_frame = ttk.Frame(frame)
        steps_frame.pack(fill=tk.X, pady=5)
        
        for i, step in enumerate([
            "点击'浏览'按钮选择需要处理的base64编码文件",
            "点击'删除base64字段'按钮开始处理文件",
            "处理完成后，点击'下载处理后文件'按钮保存结果"
        ], 1):
            ttk.Label(steps_frame, text=f"{i}. {step}", anchor="w").pack(fill=tk.X)
        
        # 注意事项
        ttk.Label(frame, text="注意事项:", font=('SimHei', 10, 'bold')).pack(anchor="w", pady=(10, 5))
        ttk.Label(frame, text="   1. 请确保输入文件是有效的base64编码文件", anchor="w").pack(fill=tk.X)
        ttk.Label(frame, text="   2. 处理后的文件默认命名为'处理后解析.txt'", anchor="w").pack(fill=tk.X)
        
        # 关闭按钮
        ttk.Button(self.base64_error_help_window, text="关闭", command=self.base64_error_help_window.destroy).pack(pady=20)