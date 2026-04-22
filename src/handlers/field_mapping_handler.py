# 在文件顶部导入缺失的模块
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import base64  # 添加缺失的base64模块导入
import binascii  # 添加缺失的binascii模块导入
import json  # 添加缺失的json模块导入
from openpyxl import Workbook, load_workbook  # 添加缺失的load_workbook导入

from src.threat_type_manager import ThreatTypeManager

class FieldMappingHandler:
    def __init__(self, main_gui):
        self.main_gui = main_gui
        # 共享变量
        self.base64_file_path = main_gui.base64_file_path
        self.excel_file_path = main_gui.excel_file_path
        self.index_value = main_gui.index_value
        self.output_json = main_gui.output_json
        
        # 初始化ThreatTypeManager实例 - 修复self.threat_manager未定义的问题
        self.threat_manager = ThreatTypeManager()
        
        # 创建面板
        self.create_field_mapping_panel(main_gui.content_frame)
        
    def create_field_mapping_panel(self, parent_frame):
        self.field_mapping_frame = ttk.Frame(parent_frame)
        
        # 文件选择部分
        file_frame = ttk.Frame(self.field_mapping_frame)
        file_frame.pack(fill=tk.X, pady=10)
        
        # Base64文件选择
        ttk.Label(file_frame, text="Base64编码文件:", anchor="w").pack(fill=tk.X, pady=(0, 5))
        file_row = ttk.Frame(file_frame)
        file_row.pack(fill=tk.X)
        
        ttk.Entry(file_row, textvariable=self.base64_file_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(file_row, text="浏览", command=self.browse_base64_file).pack(side=tk.RIGHT)
        
        # Excel文件选择
        ttk.Label(file_frame, text="Excel映射文件:", anchor="w").pack(fill=tk.X, pady=(10, 5))
        excel_row = ttk.Frame(file_frame)
        excel_row.pack(fill=tk.X)
        
        ttk.Entry(excel_row, textvariable=self.excel_file_path).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        ttk.Button(excel_row, text="浏览", command=self.browse_excel_file).pack(side=tk.RIGHT)
        
        # 索引输入和选项
        options_frame = ttk.Frame(self.field_mapping_frame)
        options_frame.pack(fill=tk.X, pady=10)
        
        ttk.Label(options_frame, text="原始字段名 (多个值用逗号分隔):", anchor="w").pack(fill=tk.X, pady=(0, 5))
        ttk.Entry(options_frame, textvariable=self.index_value).pack(fill=tk.X, pady=(0, 10))
        ttk.Label(options_frame, text="提示: 输入的字段名称应与Excel中的sheet名称对应", anchor="w", font=('SimHei', 8, 'italic')).pack(fill=tk.X, pady=(0, 5))
        
        ttk.Checkbutton(options_frame, text="同时保存JSON文件", variable=self.output_json).pack(anchor="w", pady=(0, 10))
        
        # 按钮部分
        buttons_frame = ttk.Frame(self.field_mapping_frame)
        buttons_frame.pack(fill=tk.X, pady=10)
        
        self.process_btn = ttk.Button(buttons_frame, text="处理数据", command=self.main_gui.start_process_thread)
        self.process_btn.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(buttons_frame, text="清空", command=self.main_gui.clear_fields).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(buttons_frame, text="下载模板", command=self.download_template).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(buttons_frame, text="格式帮助", command=self.show_format_help).pack(side=tk.LEFT, padx=(0, 10))
        
        # 添加新按钮：自动填充threat_type
        ttk.Button(buttons_frame, text="填充threat_type", command=self.fill_threat_type).pack(side=tk.LEFT)
        
    def show_field_mapping_panel(self):
        # 获取内容区域
        content_frame = self.field_mapping_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            if isinstance(widget, (tk.Frame, ttk.Frame, tk.Label, ttk.Label, tk.Button, ttk.Button, tk.Entry, ttk.Entry)):
                widget.pack_forget()
        
        # 显示字段映射面板
        self.field_mapping_frame.pack(fill=tk.BOTH, expand=True)
        
        if hasattr(self.main_gui, 'progress') and self.main_gui.progress:
            self.main_gui.progress.pack(fill=tk.X, pady=10)
        
        if hasattr(self.main_gui, 'log_frame') and self.main_gui.log_frame:
            self.main_gui.log_frame.pack(fill=tk.BOTH, expand=True, pady=10)
    
    def browse_base64_file(self):
        file_path = filedialog.askopenfilename(
            title="选择Base64编码文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.base64_file_path.set(file_path)
            self.main_gui.log_message(f"已选择Base64文件: {os.path.basename(file_path)}")
    
    def browse_excel_file(self):
        file_path = filedialog.askopenfilename(
            title="选择Excel映射文件",
            filetypes=[("Excel文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        if file_path:
            self.excel_file_path.set(file_path)
            self.main_gui.log_message(f"已选择Excel文件: {os.path.basename(file_path)}")
    
    def download_template(self):
        save_path = filedialog.asksaveasfilename(
            title="保存Excel模板",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
            initialfile="字段映射模板.xlsx"
        )
        
        if save_path:
            try:
                wb = Workbook()
                # 确保获取有效的工作表对象
                ws = wb.active
                if ws is None:
                    ws = wb.create_sheet(title="映射表", index=0)
                
                # 设置表头
                ws['A1'] = "mappingType"
                ws['B1'] = "orgValue"
                ws['C1'] = "mappingValue(若标准字段为威胁类型，此列可删除，后台自动匹配)"
                
                # 添加示例数据
                ws['A2'] = "EQUAL"
                ws['B2'] = "示例值1"
                ws['C2'] = "映射后的值1"
                
                ws['A3'] = "REGULAR"
                ws['B3'] = "^正则.*匹配$"
                ws['C3'] = "映射后的值2"
                
                wb.save(save_path)
                self.main_gui.log_message(f"Excel模板已保存到: {os.path.basename(save_path)}")
                messagebox.showinfo("成功", f"Excel模板已成功保存到:\n{save_path}")
            except Exception as e:
                self.main_gui.log_message(f"保存模板时出错: {str(e)}")
                messagebox.showerror("错误", f"保存模板时出错: {str(e)}")
    
    def show_format_help(self):
        # 创建帮助窗口
        help_window = tk.Toplevel(self.main_gui.root)
        help_window.title("格式帮助")
        self.main_gui.format_help_window = help_window  # 保存引用
        help_window.resizable(True, True)
        help_window.minsize(600, 400)
        help_window.configure(bg="#f5f5f5")

        # 设置帮助窗口大小与主窗口成比例
        root_width = self.main_gui.root.winfo_width()
        root_height = self.main_gui.root.winfo_height()
        help_width = int(root_width * 0.8)
        help_height = int(root_height * 0.8)
        help_window.geometry(f"{help_width}x{help_height}")

        # 创建标题栏
        title_frame = ttk.Frame(help_window, padding="10 15 10 10")
        title_frame.pack(fill=tk.X, padx=0, pady=0)

        # 标题标签
        title_label = ttk.Label(
            title_frame,
            text="字段映射工具 - 格式帮助",
            font=("SimHei", 14, "bold")
        )
        title_label.pack(anchor="center")

        # 添加分隔线
        ttk.Separator(help_window).pack(fill=tk.X, pady=0)

        # 创建主内容区域
        main_frame = ttk.Frame(help_window, padding="15")
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

        # 配置滚动条
        scrollbar.config(command=canvas.yview)

        # 创建内部框架
        frame = ttk.Frame(canvas)
        content_window = canvas.create_window((0, 0), window=frame, anchor="nw", tags="content")

        # 更新画布大小
        def on_canvas_configure(event):
            new_width = event.width - 20
            if canvas.itemcget(content_window, "width") != new_width:
                canvas.itemconfig(content_window, width=new_width)

        def on_frame_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", on_canvas_configure)
        frame.bind("<Configure>", on_frame_configure)


        # === 表格1: Excel模板列说明 ===
        ttk.Label(frame, text="Excel模板列说明:", font=("SimHei", 10, "bold"), anchor="w").pack(fill=tk.X, padx=20, pady=(15,5))
        columns_table = ttk.Treeview(frame, columns=("column", "description"), show="headings", height=3)
        columns_table.heading("column", text="列名")
        columns_table.heading("description", text="说明")
        columns_table.column("column", width=100, anchor="center")
        columns_table.column("description", width=400, anchor="w")
        columns_table.insert("", "end", values=("A列(mappingType)", "映射类型，支持EQUAL(等于)和REGULAR(正则)"))
        columns_table.insert("", "end", values=("B列(orgValue)", "原始值，EQUAL时为具体值，REGULAR时为正则表达式"))
        columns_table.insert("", "end", values=("C列(mappingValue)", "映射后的值"))
        columns_table.pack(fill=tk.X, padx=30, pady=5)

        # === 表格2: 示例数据 ===
        ttk.Label(frame, text="示例数据:", font=("SimHei", 10, "bold"), anchor="w").pack(fill=tk.X, padx=20, pady=(15,5))
        examples_table = ttk.Treeview(frame, columns=("mappingType", "orgValue", "mappingValue"), show="headings", height=2)
        examples_table.heading("mappingType", text="mappingType")
        examples_table.heading("orgValue", text="orgValue")
        examples_table.heading("mappingValue", text="mappingValue")
        examples_table.column("mappingType", width=120, anchor="center")
        examples_table.column("orgValue", width=200, anchor="center")
        examples_table.column("mappingValue", width=200, anchor="center")
        examples_table.insert("", "end", values=("EQUAL", "示例值1", "映射后的值1"))
        examples_table.insert("", "end", values=("REGULAR", "^正则.*匹配$", "映射后的值2"))
        examples_table.pack(fill=tk.X, padx=30, pady=5)

        # === 注意事项 ===
        ttk.Label(frame, text="注意事项:", font=("SimHei", 10, "bold"), anchor="w").pack(fill=tk.X, padx=20, pady=(15,5))
        notes = [
            "• Excel文件需使用.xlsx格式",
            "• 正则表达式使用Python语法",
            "• 多个字段名称用逗号分隔"
        ]
        for note in notes:
            ttk.Label(frame, text=note, anchor="w").pack(fill=tk.X, padx=30, pady=2)

        # === 填充threat_type功能说明 ===
        ttk.Label(frame, text="填充threat_type功能说明:", font=('SimHei', 10, 'bold'), anchor="w").pack(fill=tk.X, padx=20, pady=(15,5))

        # 功能描述
        ttk.Label(frame, text="功能描述:", font=('SimHei', 9, 'bold'), anchor="w").pack(fill=tk.X, padx=30, pady=(10,2))
        ttk.Label(frame, text="• 该功能用于自动填充Base64编码文件中normalize数组中field为'threat_type'的项的映射关系。", anchor="w").pack(fill=tk.X, padx=40, pady=2)
        ttk.Label(frame, text="• 映射关系将被设置为: mappingType='REGULAR', mappingValue='其他', orgValue为Excel中的威胁类型值。", anchor="w").pack(fill=tk.X, padx=40, pady=2)
        ttk.Label(frame, text="• 系统会为每个威胁类型值添加一个独立的映射关系。", anchor="w").pack(fill=tk.X, padx=40, pady=2)

        # Excel样例格式
        ttk.Label(frame, text="Excel样例格式:", font=('SimHei', 9, 'bold'), anchor="w").pack(fill=tk.X, padx=30, pady=(10,2))
        ttk.Label(frame, text="• Excel文件只需包含一列数据（A列），无需表头。", anchor="w").pack(fill=tk.X, padx=40, pady=2)
        ttk.Label(frame, text="• 数据从第一行开始，每行一个威胁类型值。", anchor="w").pack(fill=tk.X, padx=40, pady=2)

        # Excel样例数据表格
        ttk.Label(frame, text="Excel样例数据:", font=('SimHei', 9, 'bold'), anchor="w").pack(fill=tk.X, padx=30, pady=(10,2))
        threat_type_table = ttk.Treeview(frame, columns=('threat_type'), show="headings", height=3, style="Custom.Treeview")
        # 配置列属性
        threat_type_table.column('threat_type', width=250, anchor="center", stretch=False)

        # 插入数据
        threat_type_table.insert('', 'end', values=("恶意软件",))
        threat_type_table.insert('', 'end', values=("网络攻击",))
        threat_type_table.insert('', 'end', values=("数据泄露",))

        # 添加滚动条（如果需要）
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=threat_type_table.yview)
        threat_type_table.configure(yscrollcommand=scrollbar.set)

        # 放置表格和滚动条
        threat_type_table.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(40, 0), pady=10)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10)

        # 操作步骤
        ttk.Label(frame, text="操作步骤:", font=('SimHei', 9, 'bold'), anchor="w").pack(fill=tk.X, padx=30, pady=(10,2))
        steps = [
            "1. 点击'填充threat_type'按钮",
            "2. 选择包含threat_type数据的Excel文件",
            "3. 系统将自动处理并生成新的Base64编码文件",
            "4. 新文件将保存在原文件所在目录，文件名后添加'_modified'后缀"
        ]
        for i, step in enumerate(steps):
            ttk.Label(frame, text=step, anchor="w").pack(fill=tk.X, padx=40, pady=2)

        # 创建按钮区域
        button_frame = ttk.Frame(help_window, padding="10")
        button_frame.pack(fill=tk.X, side=tk.BOTTOM)

        # 关闭按钮
        close_btn = ttk.Button(
            button_frame,
            text="关闭",
            command=help_window.destroy,
            width=10,  # 设置按钮宽度
            padding=(10, 5)  # 设置内边距(左右, 上下)
        )
        close_btn.pack(pady=10)

        # 确保按钮居中
        button_frame.pack_configure(anchor="center")

        # 绑定窗口大小变化事件
        def on_window_configure(event):
            # 确保画布宽度适应窗口变化
            canvas_width = main_frame.winfo_width() - scrollbar.winfo_width() - 20
            canvas.itemconfig(content_window, width=canvas_width)
            # 更新滚动区域
            canvas.configure(scrollregion=canvas.bbox("all"))

        help_window.bind("<Configure>", on_window_configure)
        self.main_gui.root.wait_window(help_window)

    def fill_threat_type(self):
        """导入Excel数据并自动填充threat_type字段的映射关系"""
        base64_file = self.base64_file_path.get().strip()
        
        # 验证base64文件是否存在
        if not base64_file or not os.path.exists(base64_file):
            messagebox.showerror("错误", "请先选择有效的Base64编码文件")
            return
        
        # 选择Excel文件
        excel_file = filedialog.askopenfilename(
            title="选择包含threat_type数据的Excel文件",
            filetypes=[("Excel文件", "*.xlsx *.xls"), ("所有文件", "*.*")]
        )
        
        if not excel_file:
            return  # 用户取消选择
        
        try:
            # 读取Excel数据
            wb = load_workbook(excel_file, read_only=True, data_only=True)
            
            # 确保获取有效的工作表对象
            ws = wb.active
            if ws is None:
                # 尝试获取第一个工作表
                if wb.sheetnames:
                    ws = wb[wb.sheetnames[0]]
                else:
                    messagebox.showerror("错误", "Excel文件中没有找到工作表")
                    wb.close()
                    return
            
            # 读取第一列数据
            threat_types = []
            for row in ws.iter_rows(min_row=1, max_col=1, values_only=True):
                if row[0] is not None:
                    threat_types.append(str(row[0]))
            
            wb.close()
            
            if not threat_types:
                messagebox.showinfo("提示", "Excel文件中没有找到有效数据")
                return
            
            # 解码Base64并解析JSON
            with open(base64_file, 'rb') as f:
                base64_data = f.read()
            
            try:
                decoded_data = base64.b64decode(base64_data, validate=False)
                json_str = decoded_data.decode('utf-8')
                data = json.loads(json_str)
            except (binascii.Error, json.JSONDecodeError) as e:
                messagebox.showerror("错误", f"Base64解码或JSON解析失败: {str(e)}")
                return
            
            # 初始化统计变量
            total_items = 0
            matched_items = 0
            new_mappings = []
            
            # 检查并填充threat_type字段
            if not isinstance(data, list):
                data = [data]  # 确保是列表格式
            
            updated_count = 0
            for item in data:
                if isinstance(item, dict) and "normalize" in item:
                    normalize_array = item["normalize"]
                    if isinstance(normalize_array, list):
                        # 遍历normalize数组
                        for normalize_item in normalize_array:
                            if isinstance(normalize_item, dict) and normalize_item.get("field") == "threat_type":
                                # 检查是否已有mappings字段
                                if "mappings" not in normalize_item:
                                    normalize_item["mappings"] = []
                                
                                # 为每个威胁类型添加映射
                                for threat_value in threat_types:
                                    # 使用管理器查找匹配的威胁类型
                                    matched_type = self.threat_manager.find_matching_threat_type(threat_value, "REGULAR")
                                    
                                    # 创建映射项
                                    mapping_item = {
                                        "mappingType": "REGULAR",
                                        "mappingValue": matched_type,
                                        "orgValue": f".*{threat_value}.*"
                                    }
                                    
                                    # 检查是否已存在相同的映射
                                    exists = any(m.get("orgValue") == mapping_item["orgValue"] for m in normalize_item["mappings"])
                                    if not exists:
                                        normalize_item["mappings"].append(mapping_item)
                                        new_mappings.append(mapping_item)
                                        updated_count += 1
                                        # 如果匹配到非默认类型，增加匹配计数
                                        if matched_type != self.threat_manager.default_type:
                                            matched_items += 1
            
            total_items = len(threat_types)
            
            # 保存修改后的数据
            modified_json_str = json.dumps(data, ensure_ascii=False, separators=(',', ':'))
            modified_base64 = base64.b64encode(modified_json_str.encode('utf-8')).decode('utf-8')
            
            # 保存到临时文件
            temp_file = os.path.splitext(base64_file)[0] + "_modified.txt"
            with open(temp_file, 'w', encoding='utf-8') as f:
                f.write(modified_base64)
            
            # 更新文件路径
            self.base64_file_path.set(temp_file)
            
            # 更新界面显示结果，增加统计信息
            result_message = f"威胁类型填充完成！\n"
            result_message += f"共处理 {total_items} 个项目\n"
            result_message += f"成功匹配 {matched_items} 个威胁类型\n"
            result_message += f"新增 {len(new_mappings)} 条映射关系"
            
            messagebox.showinfo("成功", result_message + f"\n文件已保存至: {temp_file}")
            
            # 记录详细日志
            self.main_gui.log_message(result_message)
            for mapping in new_mappings[:5]:  # 只显示前5条作为示例
                self.main_gui.log_message(f"映射: '{mapping['orgValue']}' -> '{mapping['mappingValue']}'")
            if len(new_mappings) > 5:
                self.main_gui.log_message(f"... 还有 {len(new_mappings) - 5} 条映射未显示")
                # 如果有超过5条映射，显示所有映射的弹出窗口
                self.show_all_mappings(new_mappings)
        
        except Exception as e:
            error_message = f"处理威胁类型时出错: {str(e)}"
            self.main_gui.log_message(error_message)
            messagebox.showerror("错误", error_message)

    def show_all_mappings(self, mappings):
        """显示所有映射关系的弹出窗口，优先显示映射值为'其他'的项"""
        # 创建新窗口
        mapping_window = tk.Toplevel(self.main_gui.root)
        mapping_window.title(f"所有映射关系 ({len(mappings)} 条)")
        mapping_window.geometry("800x600")
        mapping_window.minsize(600, 400)
        
        # 创建滚动条和文本框
        frame = ttk.Frame(mapping_window)
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建垂直滚动条
        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # 创建文本框用于显示映射关系
        text_widget = tk.Text(frame, wrap=tk.WORD, yscrollcommand=scrollbar.set, font=('SimHei', 10))
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 配置滚动条
        scrollbar.config(command=text_widget.yview)
        
        # 对映射进行排序：优先显示映射值为'其他'的项
        # 分离'其他'映射和非'其他'映射
        other_mappings = []
        regular_mappings = []
        
        for mapping in mappings:
            if mapping['mappingValue'] == '其他':  # 或 self.threat_manager.default_type
                other_mappings.append(mapping)
            else:
                regular_mappings.append(mapping)
        
        # 合并排序后的列表：先'其他'映射，然后是其他映射
        sorted_mappings = other_mappings + regular_mappings
        
        # 添加所有映射关系到文本框
        for i, mapping in enumerate(sorted_mappings, 1):
            text_widget.insert(tk.END, f"{i}. 映射: '{mapping['orgValue']}' -> '{mapping['mappingValue']}'\n")
        
        # 设置文本框为只读
        text_widget.config(state=tk.DISABLED)
        
        # 添加关闭按钮
        button_frame = ttk.Frame(mapping_window)
        button_frame.pack(fill=tk.X, pady=10)
        
        close_btn = ttk.Button(
            button_frame,
            text="关闭",
            command=mapping_window.destroy,
            width=10,
            padding=(10, 5)
        )
        close_btn.pack(pady=10)
        button_frame.pack_configure(anchor="center")
        
        # 设置窗口模态，等待用户关闭
        mapping_window.transient(self.main_gui.root)  # 设置为主窗口的子窗口
        mapping_window.grab_set()  # 模态对话框
        self.main_gui.root.wait_window(mapping_window)  # 等待窗口关闭