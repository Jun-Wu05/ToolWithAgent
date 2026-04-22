import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import json
import base64
import binascii
import threading
from openpyxl import load_workbook
from collections import defaultdict

class StandardFieldMappingHandler:
    def __init__(self, main_gui):
        self.main_gui = main_gui
        self.standard_mapping_frame = None
        # 初始化变量为None，在create_standard_field_mapping_panel中创建
        self.original_rules_path = None  # 原始解析规则文件路径（base64编码）
        self.mapping_file_path = None     # 标准字段映射表文件路径
        self.parsed_config = None         # 解析后的配置数据
        self.status_text = None           # 调试信息文本框
        
    def create_standard_field_mapping_panel(self, parent_frame):
        """创建标准字段映射面板，从上至下：原始解析规则上传、标准字段映射表上传、调试信息展示框"""
        self.standard_mapping_frame = ttk.Frame(parent_frame)
        
        # 在创建UI组件之前创建tkinter变量
        # 使用main_gui.root作为master窗口
        self.original_rules_path = tk.StringVar(master=self.main_gui.root)  # 原始解析规则文件路径（base64编码）
        self.mapping_file_path = tk.StringVar(master=self.main_gui.root)     # 标准字段映射表文件路径
        
        # 1. 原始解析规则上传（base64编码格式）
        ttk.Label(
            self.standard_mapping_frame,
            text="原始解析规则上传 (Base64格式):",
            anchor="w"
        ).pack(fill=tk.X, padx=10, pady=(10, 5))
        
        original_rules_frame = ttk.Frame(self.standard_mapping_frame)
        original_rules_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Entry(
            original_rules_frame, 
            textvariable=self.original_rules_path,
            width=50
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(
            original_rules_frame, 
            text="浏览", 
            command=self.browse_original_rules,
            width=10
        ).pack(side=tk.RIGHT)
        
        # 2. 标准字段映射表上传
        ttk.Label(
            self.standard_mapping_frame,
            text="标准字段映射表上传:",
            anchor="w"
        ).pack(fill=tk.X, padx=10, pady=(10, 5))
        
        mapping_file_frame = ttk.Frame(self.standard_mapping_frame)
        mapping_file_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Entry(
            mapping_file_frame, 
            textvariable=self.mapping_file_path,
            width=50
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
        
        ttk.Button(
            mapping_file_frame, 
            text="浏览", 
            command=self.browse_mapping_file,
            width=10
        ).pack(side=tk.RIGHT)
        
        # 操作按钮区域
        button_frame = ttk.Frame(self.standard_mapping_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10)
        
        ttk.Button(
            button_frame,
            text="处理映射",
            command=self.process_standard_mapping,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame,
            text="使用说明",
            command=self.show_usage_help,
            width=12
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame,
            text="下载模板",
            command=self.download_template,
            width=12
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame,
            text="保存修改后规则",
            command=self.save_modified_rules,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Button(
            button_frame,
            text="清空",
            command=self.clear_fields,
            width=10
        ).pack(side=tk.RIGHT)
        
        # 3. 调试信息展示框（固定在下方）
        debug_frame = ttk.Frame(self.standard_mapping_frame)
        debug_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        ttk.Label(
            debug_frame,
            text="调试信息:",
            anchor="w",
            font=('SimHei', 10, 'bold')
        ).pack(fill=tk.X, pady=(0, 5))
        
        # 调试信息文本框
        self.status_text = tk.Text(
            debug_frame, 
            height=20, 
            wrap=tk.WORD,
            bg="#f0f0f0",
            font=('Courier New', 9)
        )
        
        scrollbar = ttk.Scrollbar(
            debug_frame, 
            orient=tk.VERTICAL, 
            command=self.status_text.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.status_text.pack(fill=tk.BOTH, expand=True)
        self.status_text.config(yscrollcommand=scrollbar.set)
        
        # 设置文本框为只读模式
        self.status_text.config(state=tk.DISABLED)
        
    def show_standard_field_mapping_panel(self):
        """显示标准字段映射面板"""
        # 获取内容区域
        content_frame = self.main_gui.field_mapping.field_mapping_frame.master
        
        # 隐藏内容区域中的所有组件
        for widget in content_frame.winfo_children():
            widget.pack_forget()
        
        # 如果面板尚未创建，则创建面板
        if not self.standard_mapping_frame:
            self.create_standard_field_mapping_panel(content_frame)
            self.status_message("准备就绪")
        
        # 显示标准字段映射面板
        if self.standard_mapping_frame:
            self.standard_mapping_frame.pack(fill=tk.BOTH, expand=True)
        
        # 清空状态文本（仅当有内容时）
        if self.status_text and self.status_text.get(1.0, tk.END).strip():
            self.status_text.delete(1.0, tk.END)
    
    def browse_original_rules(self):
        """浏览并选择原始解析规则文件（base64编码）"""
        file_path = filedialog.askopenfilename(
            title="选择原始解析规则文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            if self.original_rules_path:
                self.original_rules_path.set(file_path)
                self.status_message(f"已选择原始解析规则文件: {os.path.basename(file_path)}")
            else:
                self.status_message("错误: 原始规则路径变量未初始化")
    
    def browse_mapping_file(self):
        """浏览并选择标准映射文件"""
        file_path = filedialog.askopenfilename(
            title="选择标准映射文件",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            if self.mapping_file_path:
                self.mapping_file_path.set(file_path)
                self.status_message(f"已选择映射文件: {os.path.basename(file_path)}")
            else:
                self.status_message("错误: 映射文件路径变量未初始化")
    
    def process_standard_mapping(self):
        """处理标准字段映射"""
        # 检查变量是否已初始化
        if not self.original_rules_path:
            self.status_message("错误: 原始规则路径变量未初始化")
            return
        
        if not self.mapping_file_path:
            self.status_message("错误: 映射文件路径变量未初始化")
            return
        
        original_rules_path = self.original_rules_path.get().strip()
        mapping_file = self.mapping_file_path.get().strip()
        
        # 验证输入
        if not original_rules_path or not os.path.exists(original_rules_path):
            self.status_message("错误: 请选择有效的原始解析规则文件")
            return
        
        if not mapping_file or not os.path.exists(mapping_file):
            self.status_message("错误: 请选择有效的标准映射文件")
            return
        
        self.status_message("开始处理标准字段映射...")
        
        # 在后台线程处理映射
        threading.Thread(target=self._process_mapping_thread, args=(original_rules_path, mapping_file), daemon=True).start()
    
    def _process_mapping_thread(self, original_rules_path, mapping_file):
        """后台线程处理标准字段映射"""
        try:
            # 1. 读取并解码base64格式的原始解析规则
            self.status_message(f"读取原始解析规则文件: {os.path.basename(original_rules_path)}")
            
            # 读取base64文件
            with open(original_rules_path, 'rb') as f:
                base64_data = f.read()
            
            # 检查文件是否为空
            if not base64_data:
                self.status_message("Base64文件为空")
                return
            
            # 解码base64数据，参考data_processor.py的实现
            try:
                decoded_data = base64.b64decode(base64_data, validate=False)
                json_str = decoded_data.decode('utf-8')
                self.parsed_config = json.loads(json_str)
                self.status_message("成功解码base64并读取JSON配置")
            except binascii.Error as e:
                self.status_message(f"Base64解码失败: {str(e)}")
                return
            except json.JSONDecodeError as e:
                self.status_message(f"JSON解析失败: {str(e)}")
                return
            except Exception as e:
                self.status_message(f"处理原始规则文件时出错: {str(e)}")
                return
            
            # 2. 加载标准字段映射表
            self.status_message(f"读取标准映射文件: {os.path.basename(mapping_file)}")
            
            # 只支持Excel格式的映射文件
            mapping_rules = []
            if mapping_file.endswith('.xlsx'):
                # 实现Excel文件处理功能
                mapping_rules = self.read_mappings_from_excel(mapping_file)
                if mapping_rules is None:
                    self.status_message("错误: 无法读取映射文件中的数据")
                    return
                if not mapping_rules:
                    self.status_message("错误: 映射文件中没有找到有效映射规则")
                    return
            else:
                self.status_message("不支持的映射文件格式，请选择Excel文件(.xlsx)")
                return
            
            # 3. 实现映射逻辑（参考field_mapping_demo.py）
            self.status_message("开始处理字段映射...")
            
            # 获取标准字段列表
            standard_fields = self.get_standard_fields(self.parsed_config)
            self.status_message(f"共获取到 {len(standard_fields)} 个标准字段")
            
            # 显示当前映射
            self.display_current_mappings(self.parsed_config)
            
            # 应用映射规则
            updated_count = self.apply_mapping_rules(self.parsed_config, mapping_rules)
            
            self.status_message(f"字段映射处理完成，共更新 {updated_count} 个映射关系")
            self.status_message("处理完成，可点击'保存修改后规则'按钮保存结果")
            
        except Exception as e:
            self.status_message(f"处理时发生错误: {str(e)}")
            import traceback
            self.status_message(f"详细错误信息: {traceback.format_exc()}")
    
    def get_standard_fields(self, config):
        """从配置中获取标准字段列表"""
        standard_fields = []
        properties = config[0].get('properties', [])
        for prop in properties:
            if prop.get('key'):
                standard_fields.append({
                    'key': prop['key'],
                    'name': prop.get('name', prop['key']),
                    'entity': prop.get('entity')
                })
        return standard_fields
    
    def display_current_mappings(self, config):
        """显示当前的字段映射"""
        self.status_message("\n当前字段映射：")
        normalize = config[0].get('normalize', [])
        for item in normalize:
            index = item.get('index')
            field = item.get('field')
            entity = item.get('entity')
            result = item.get('result', [])
            self.status_message(f"索引 {index}: 字段={field}, 实体={entity}, 结果={result}")
    
    def apply_mapping_rules(self, config, mapping_rules):
        """应用映射规则到配置中"""
        normalize = config[0].get('normalize', [])
        standard_fields = self.get_standard_fields(config)  # 获取标准字段信息
        updated_count = 0
        
        # 确保field_to_entity和prop_to_field已加载
        if not hasattr(self, 'field_to_entity') or not self.field_to_entity:
            self.status_message("警告: field_to_entity未初始化，将无法正确获取实体映射")
        if not hasattr(self, 'prop_to_field') or not self.prop_to_field:
            self.status_message("警告: prop_to_field未初始化，将无法正确获取字段映射")
        
        for rule in mapping_rules:
            original_field = rule.get('original_field')
            standard_field = rule.get('standard_field')
            
            if not original_field or not standard_field:
                continue
            
            # 实体获取优先级：
            # 1. 直接通过字段名称查找field_to_entity
            # 2. 通过系统属性名称查找field_to_entity（如果standard_field是系统属性名称）
            entity = None
            
            # 策略1：直接通过字段名称查找
            if hasattr(self, 'field_to_entity') and standard_field in self.field_to_entity:
                entity = self.field_to_entity[standard_field]
            else:
                # 策略2：如果standard_field是系统属性名称，先转换为字段名称
                if hasattr(self, 'prop_to_field') and standard_field in self.prop_to_field:
                    converted_field = self.prop_to_field[standard_field]
                    self.status_message(f"[apply_mapping_rules] 将系统属性 '{standard_field}' 转换为字段名称 '{converted_field}'")
                    # 使用转换后的字段名称重新查找entity
                    if hasattr(self, 'field_to_entity') and converted_field in self.field_to_entity:
                        entity = self.field_to_entity[converted_field]
                    # 更新standard_field为转换后的字段名称
                    standard_field = converted_field
            
            # 策略3：如果仍然没有entity，从standard_fields中获取（原始配置文件中的值）
            if not entity:
                for field in standard_fields:
                    if field['key'] == standard_field:
                        entity = field.get('entity')
                        break
            
            if not entity:
                self.status_message(f"警告：未找到标准字段 {standard_field} 的实体")
                continue
            
            # 查找对应的映射项
            matched_item = None
            original_key = str(original_field).strip()
            original_key_lower = original_key.lower()

            for item in normalize:
                index_value = str(item.get('index', '') or '').strip()
                field_value = str(item.get('field', '') or '').strip()
                result = item.get('result', [])
                if isinstance(result, list):
                    result_values = [str(v).strip() for v in result if v is not None]
                else:
                    result_values = [str(result).strip()]
                result_values_lower = [v.lower() for v in result_values]
                index_value_lower = index_value.lower()
                field_value_lower = field_value.lower()

                # 先按 normalize.index 匹配原始字段名，再按 field，再按 result 兜底
                if (
                    original_key_lower == index_value_lower
                    or original_key_lower in index_value_lower
                    or original_key_lower == field_value_lower
                    or original_key_lower in field_value_lower
                    or original_key_lower in result_values_lower
                ):
                    matched_item = item
                    break

            if matched_item:
                matched_item['field'] = standard_field
                matched_item['entity'] = entity
                # 保持原来的 result 数据值，不要改成字段名
                matched_item['core'] = False
                matched_item['sim'] = True

                # 检查entity是否在simEntities中，不在则添加
                sim_entities = config[0].get('simEntities', [])
                if entity and entity not in sim_entities:
                    sim_entities.append(entity)
                    config[0]['simEntities'] = sim_entities

                updated_count += 1
            else:
                self.status_message(f"未找到匹配normalize项，创建新项: {original_key} -> {standard_field}")
                new_item = {
                    'core': False,
                    'entity': entity,
                    'field': standard_field,
                    'index': original_key,
                    'info': [],
                    'required': False,
                    'result': [],  # 设置为空数组，不要用字段名
                    'sim': True,
                    'value': None
                }
                normalize.append(new_item)
                sim_entities = config[0].get('simEntities', [])
                if entity and entity not in sim_entities:
                    sim_entities.append(entity)
                    config[0]['simEntities'] = sim_entities
                updated_count += 1

        self.status_message(f"字段映射完成: 共更新 {updated_count} 个映射规则")
        return updated_count
    
    def _load_standard_properties(self):
        """从固定的对象.xlsx文件读取系统属性和字段名称映射"""
        import sys
        if getattr(sys, 'frozen', False) and getattr(sys, '_MEIPASS', None):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fixed_file = os.path.join(base_path, "config", "对象.xlsx")
        prop_to_field = {}  # 系统属性名称 -> 字段名称
        field_to_entity = {}  # 字段名称 -> 实体（对象）名称
        
        try:
            if not os.path.exists(fixed_file):
                self.status_message(f"错误: 固定标准字段文件不存在: {fixed_file}")
                return None, None, None
                
            self.status_message(f"正在加载固定标准字段文件: {os.path.basename(fixed_file)}")
            wb = load_workbook(fixed_file, read_only=True, data_only=True)
            
            try:
                # 优先读取【对应关系】sheet页
                if '对应关系' in wb.sheetnames:
                    ws = wb['对应关系']
                    self.status_message("正在读取【对应关系】sheet页构建属性映射关系...")
                    
                    headers = []
                    if ws.max_row >= 1:
                        for col in range(1, ws.max_column + 1):
                            cell_value = ws.cell(row=1, column=col).value
                            headers.append(str(cell_value) if cell_value is not None else '')
                    
                    # 查找系统属性名称、字段名称、对象的列索引
                    prop_col_index = None
                    field_col_index = None
                    entity_col_index = None
                    for i, header in enumerate(headers):
                        if '系统属性' in header or '属性名称' in header:
                            prop_col_index = i + 1
                        if '字段名称' in header or '字段' in header:
                            field_col_index = i + 1
                        if '对象' in header:
                            entity_col_index = i + 1
                    
                    if prop_col_index and field_col_index and entity_col_index:
                        for row in ws.iter_rows(min_row=2, max_row=ws.max_row, values_only=True):
                            if len(row) >= max(prop_col_index, field_col_index, entity_col_index):
                                prop_name = row[prop_col_index - 1]
                                field_name = row[field_col_index - 1]
                                entity_name = row[entity_col_index - 1]
                                
                                if prop_name and field_name and entity_name:
                                    prop_name = str(prop_name).strip()
                                    field_name = str(field_name).strip()
                                    
                                    # 处理多个对象的情况，取第一个
                                    entity_name = str(entity_name).strip()
                                    if ',' in entity_name:
                                        entity_name = entity_name.split(',')[0].strip()
                                    
                                    # 构建映射关系
                                    prop_to_field[prop_name] = field_name
                                    field_to_entity[field_name] = entity_name
                        
                        self.status_message(f"从【对应关系】sheet页读取 {len(prop_to_field)} 个系统属性映射，{len(field_to_entity)} 个字段实体映射")
                    else:
                        self.status_message(f"警告: 【对应关系】sheet页中未找到完整的列")
                else:
                    self.status_message(f"警告: 未找到【对应关系】sheet页")
                    
            finally:
                wb.close()
                
            return prop_to_field, field_to_entity, {}
            
        except Exception as e:
            self.status_message(f"读取固定标准字段文件时出错: {str(e)}")
            import traceback
            self.status_message(f"详细错误: {traceback.format_exc()}")
            return None, None, None
    
    def read_mappings_from_excel(self, user_template_file):
        """使用openpyxl读取Excel映射数据"""
        try:
            # 检查用户上传文件是否存在
            if not os.path.exists(user_template_file):
                self.status_message("错误: 用户上传的映射文件不存在")
                return None

            mapping_rules = []  # 用于存储用户模板中的映射规则
            row_count = 0
            valid_count = 0
            
            # 第一步：从固定的对象.xlsx读取系统属性和字段名称映射
            prop_to_field, field_to_entity, prop_to_entity = self._load_standard_properties()
            if prop_to_field is None or field_to_entity is None:
                return None
            
            # 第二步：从用户上传的模板文件读取映射规则
            self.status_message(f"正在加载用户上传的映射文件: {os.path.basename(user_template_file)}")
            wb = load_workbook(user_template_file, read_only=True, data_only=True)
            try:
                # 检查用户模板的工作表结构
                found_mapping_sheet = False
                
                # 优先查找Sheet1
                if 'Sheet1' in wb.sheetnames:
                    ws = wb['Sheet1']
                    self.status_message("正在处理Sheet1中的映射关系...")
                    found_mapping_sheet = True
                else:
                    # 如果没有Sheet1，查找第一个包含"映射"或"规则"的工作表
                    for sheet_name in wb.sheetnames:
                        if '映射' in sheet_name or '规则' in sheet_name:
                            ws = wb[sheet_name]
                            self.status_message(f"正在处理工作表 '{sheet_name}' 中的映射关系...")
                            found_mapping_sheet = True
                            break
                    
                    # 如果还是没有找到，使用第一个工作表
                    if not found_mapping_sheet:
                        first_sheet = wb.sheetnames[0]
                        ws = wb[first_sheet]
                        self.status_message(f"未找到指定映射工作表，使用第一个工作表 '{first_sheet}'")
                        found_mapping_sheet = True
                
                if found_mapping_sheet:
                    # 处理映射规则
                    for row in ws.iter_rows(min_row=2, max_col=2, values_only=True):
                        row_count += 1
                        # 过滤空行和匹配值为空的行
                        if len(row) < 2 or row[0] is None or row[1] is None:
                            continue
                        
                        original_field = str(row[0]).strip()
                        standard_field = str(row[1]).strip()
                        
                        if original_field and standard_field:
                            # 检查标准字段名是否是系统属性名称，如果是则转换为字段名称
                            if standard_field in prop_to_field:
                                converted_field = prop_to_field[standard_field]
                                self.status_message(f"将系统属性 '{standard_field}' 转换为字段名称 '{converted_field}'")
                                mapping_rules.append({
                                    "original_field": original_field,
                                    "standard_field": converted_field
                                })
                            else:
                                # 如果不是系统属性名称，直接使用
                                mapping_rules.append({
                                    "original_field": original_field,
                                    "standard_field": standard_field
                                })
                            valid_count += 1
                    
                    self.status_message(f"从用户模板读取 {valid_count} 个有效映射关系 (共扫描 {row_count} 行)")
                    
                else:
                    self.status_message("错误: 无法找到包含映射关系的工作表")
                    return None
                    
            finally:
                wb.close()
                
            if not mapping_rules:
                self.status_message(f"错误: 用户上传的模板文件中没有有效映射数据")
                return None
            
            # 创建反向映射：字段名称 -> 系统属性名称
            field_to_prop = {field: prop for prop, field in prop_to_field.items()}
            
            # 保存映射关系供后续使用
            self.prop_to_field = prop_to_field
            self.field_to_entity = field_to_entity
            self.field_to_prop = field_to_prop
            
            self.status_message(f"成功从模板读取 {len(mapping_rules)} 个映射关系")
            
            # 添加调试信息：显示field_to_entity的关键映射
            self.status_message(f"调试: field_to_entity共 {len(field_to_entity)} 个映射")
            if field_to_entity:
                # 显示几个关键的映射示例
                sample_count = 0
                for field, entity in field_to_entity.items():
                    if sample_count >= 5:
                        break
                    if any(keyword in str(field).lower() for keyword in ['threat', 'event', 'content', 'original']):
                        self.status_message(f"  - field_to_entity['{field}'] = '{entity}'")
                        sample_count += 1
            
            return mapping_rules
        except Exception as e:
            self.status_message(f"读取Excel映射数据时出错: {str(e)}")
            import traceback
            self.status_message(f"详细错误信息: {traceback.format_exc()}")
            return None
            
    def get_entity_by_field(self, field_name):
        """根据字段名称获取实体名称
        
        Args:
            field_name: 字段名称（如event_content）
            
        Returns:
            实体名称（如"事件"）或None
        """
        try:
            if not hasattr(self, 'field_to_entity'):
                self.status_message("错误: 未初始化字段到实体的映射关系")
                return None
            
            # 直接通过字段名称查找实体
            if field_name in self.field_to_entity:
                return self.field_to_entity[field_name]
            
            # 如果找不到，尝试通过系统属性名称查找
            if hasattr(self, 'field_to_prop') and field_name in self.field_to_prop:
                prop_name = self.field_to_prop[field_name]
                self.status_message(f"通过字段 {field_name} 找到系统属性 {prop_name}")
                
                # 遍历所有工作表重新查找（如果需要）
                self.status_message("注意: 未直接找到字段到实体的映射，可能需要重新加载Excel文件")
                
            return None
            
        except Exception as e:
            self.status_message(f"获取实体时出错: {str(e)}")
            return None

    def download_template(self):
        """下载标准字段映射表模板"""
        try:
            # 使用filedialog让用户选择保存位置和文件名
            save_path = filedialog.asksaveasfilename(
                title="保存标准字段映射表模板",
                defaultextension=".xlsx",
                filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")],
                initialfile="标准字段映射表模板.xlsx"
            )
            
            if not save_path:
                return  # 用户取消了保存操作
            
            self.status_message(f"正在生成模板文件: {os.path.basename(save_path)}")
            
            # 使用openpyxl创建Excel文件
            from openpyxl import Workbook
            wb = Workbook()
            ws = wb.active
            
            # 检查工作表是否成功创建
            if not ws:
                self.status_message("错误: 无法创建Excel工作表")
                messagebox.showerror("错误", "无法创建Excel工作表")
                return
            
            ws.title = "标准字段映射表"
            
            # 添加表头
            if hasattr(ws, '__setitem__'):
                ws['A1'] = "原始字段名"
                ws['B1'] = "标准字段名"
            else:
                self.status_message("警告: 无法添加表头，模板文件可能不完整")
            
            # 设置表头样式
            from openpyxl.styles import Font, Border, Side
            header_font = Font(bold=True)
            
            # 检查ws是否支持__getitem__方法（用于ws[1]访问）
            if hasattr(ws, '__getitem__'):
                for cell in ws[1]:
                    cell.font = header_font
            else:
                self.status_message("警告: 无法设置表头样式，可能会影响表格显示效果")
            
            # 添加示例数据
            examples = [
                ["raw_field_1", "standard_field_1"],
                ["raw_field_2", "standard_field_2"],
                ["raw_field_3", "standard_field_3"]
            ]
            
            # 检查ws是否具有cell方法
            if hasattr(ws, 'cell'):
                for i, example in enumerate(examples, start=2):
                    ws.cell(row=i, column=1, value=example[0])
                    ws.cell(row=i, column=2, value=example[1])
            else:
                self.status_message("警告: 无法添加示例数据，可能会影响表格使用体验")
            
            # 调整列宽
            if hasattr(ws, 'column_dimensions'):
                ws.column_dimensions['A'].width = 20
                ws.column_dimensions['B'].width = 20
            else:
                self.status_message("警告: 无法调整列宽，可能会影响表格显示效果")
            
            # 保存文件
            wb.save(save_path)
            
            self.status_message(f"模板文件已成功保存到: {os.path.basename(save_path)}")
            messagebox.showinfo("成功", f"标准字段映射表模板已成功保存！\n文件路径: {save_path}")
            
        except Exception as e:
            self.status_message(f"生成模板文件时出错: {str(e)}")
            import traceback
            self.status_message(f"详细错误信息: {traceback.format_exc()}")
            messagebox.showerror("错误", f"生成模板文件时出错: {str(e)}")
    
    def save_modified_rules(self):
        """保存修改后的规则，重新编码为base64格式"""
        if not self.parsed_config:
            self.status_message("错误: 没有可保存的修改后规则")
            messagebox.showerror("错误", "没有可保存的修改后规则")
            return
        
        # 获取默认文件名
        original_filename = os.path.basename(self.original_rules_path.get()) if self.original_rules_path and self.original_rules_path.get() else "rules.txt"
        default_filename = f"modified_{original_filename}"
        
        # 保存文件对话框
        file_path = filedialog.asksaveasfilename(
            title="保存修改后的解析规则",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=default_filename
        )
        
        if file_path:
            try:
                self.status_message(f"准备保存修改后的规则到: {os.path.basename(file_path)}")
                
                # 将配置转换为JSON字符串，使用紧凑格式
                self.status_message("正在将配置转换为JSON字符串...")
                json_str = json.dumps(self.parsed_config, ensure_ascii=False, separators=(',', ':'))
                self.status_message(f"JSON字符串生成成功，长度: {len(json_str)} 字符")
                
                # 重新编码为base64
                self.status_message("正在将JSON字符串编码为Base64格式...")
                base64_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
                self.status_message(f"Base64编码成功，长度: {len(base64_data)} 字符")
                
                # 保存到文件
                self.status_message(f"正在写入文件: {file_path}")
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(base64_data)
                
                self.status_message(f"修改后的规则已保存到: {os.path.basename(file_path)}")
                self.status_message(f"文件大小: {os.path.getsize(file_path)} 字节")
                messagebox.showinfo("成功", f"修改后的解析规则已成功保存！\n文件路径: {file_path}")
                
            except json.JSONDecodeError as e:
                error_msg = f"JSON序列化失败: {str(e)}"
                self.status_message(error_msg)
                messagebox.showerror("错误", error_msg)
            except Exception as e:
                error_msg = f"保存文件时出错: {str(e)}"
                self.status_message(error_msg)
                import traceback
                self.status_message(f"详细错误信息: {traceback.format_exc()}")
                messagebox.showerror("错误", error_msg)
    
    def show_usage_help(self):
        """显示标准字段映射功能的使用说明和表格格式示例"""
        # 创建帮助窗口
        help_window = tk.Toplevel(self.main_gui.root)
        help_window.title("标准字段映射 - 使用说明")
        help_window.geometry("800x600")
        help_window.resizable(True, True)
        help_window.transient(self.main_gui.root)  # 使帮助窗口始终在主窗口上方
        
        # 创建框架
        main_frame = ttk.Frame(help_window)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 标题
        ttk.Label(
            main_frame,
            text="标准字段映射功能使用说明",
            font=('SimHei', 14, 'bold')
        ).pack(pady=10)
        
        # 创建滚动条和文本框
        text_frame = ttk.Frame(main_frame)
        text_frame.pack(fill=tk.BOTH, expand=True)
        
        # 帮助内容文本框
        help_text = tk.Text(
            text_frame,
            wrap=tk.WORD,
            bg="white",
            font=('SimHei', 10)
        )
        
        scrollbar = ttk.Scrollbar(
            text_frame,
            orient=tk.VERTICAL,
            command=help_text.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        help_text.pack(fill=tk.BOTH, expand=True)
        help_text.config(yscrollcommand=scrollbar.set)
        
        # 设置文本框为只读模式
        help_text.config(state=tk.NORMAL)
        
        # 添加帮助内容
        help_content = self._get_usage_help_content()
        help_text.insert(tk.END, help_content)
        
        # 设置为只读模式
        help_text.config(state=tk.DISABLED)
    
    def _get_usage_help_content(self):
        """获取使用帮助内容"""
        return """
功能介绍：
标准字段映射功能用于将原始解析规则中的字段映射到标准字段，支持自动解码Base64格式的原始规则，并将结果重新编码为Base64格式。

使用步骤：
1. 上传原始解析规则文件（Base64编码格式）
2. （可选）点击"下载模板"按钮获取标准字段映射表模板
3. 按照模板格式填写标准字段映射关系并保存为Excel文件
4. 上传标准字段映射表文件（仅支持Excel格式）
5. 点击"处理映射"按钮开始处理
6. 查看调试信息了解处理结果
7. 点击"保存修改后规则"保存处理后的结果

原始解析规则格式：
- 必须是Base64编码的JSON格式文件
- 文件扩展名通常为.txt
- 示例内容（解码前）：eyJjb25maWd1cmF0aW9uIjpbeyJwcm9wZXJ0aWVzIjpbeyJrZXkiOiJzdGFuZGFsb25lX2ZpZWxkIiwibmFtZSI6IlN0YW5kYWxvbmUgRmlldGhkIn1dfX0=

标准字段映射表格式：

Excel格式（.xlsx）：
- 第一列为原始字段名
- 第二列为标准字段名
- 第一行为表头（将被忽略）
- 示例表格：

原始字段名      标准字段名
raw_field_1     standard_field_1
raw_field_2     standard_field_2
raw_field_3     standard_field_3

注意事项：
- 原始解析规则文件必须是有效的Base64编码
- 映射表中的原始字段名必须与原始解析规则中的字段名完全匹配
- 标准字段名必须与系统中定义的标准字段一致
- 处理结果将保留原始配置的结构，仅更新字段映射部分

输出结果：
- 处理后的规则将重新编码为Base64格式
- 输出文件包含更新后的字段映射关系
- 调试信息中会显示处理的详细过程和结果统计
        """
    
    def clear_fields(self):
        """清空所有字段"""
        if self.original_rules_path:
            self.original_rules_path.set("")
        if self.mapping_file_path:
            self.mapping_file_path.set("")
        self.parsed_config = None
        if self.status_text:
            self.status_text.delete(1.0, tk.END)
            self.status_message("已清空所有字段")
    
    def status_message(self, message):
        """线程安全的状态消息输出"""
        def update_status():
            if self.status_text:
                # 在插入文本前先设置为可写模式
                self.status_text.config(state=tk.NORMAL)
                self.status_text.insert(tk.END, message + "\n")
                self.status_text.see(tk.END)
                # 插入后设置回只读模式
                self.status_text.config(state=tk.DISABLED)
        if self.main_gui.root:
            self.main_gui.root.after(0, update_status)
        else:
            # 如果没有GUI环境，直接打印消息
            print(f"[DEBUG] {message}")
