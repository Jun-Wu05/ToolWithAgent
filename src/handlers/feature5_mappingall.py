"""
功能5：字段映射集合（融合字段映射和枚举添加功能）

本功能整合了功能1（带枚举的字段映射）和功能4（标准字段映射），提供统一的工作流程：
1. 上传原始Base64编码的解析规则
2. 上传包含多个Sheet的字段映射模板（Sheet名称=原始字段名）
3. 遍历每个Sheet：
   - 如果Sheet名称是对象.xlsx中的系统属性名，则先获取实体（功能4），再添加枚举映射（功能1）
   - 如果Sheet名称不是系统属性名，则仅添加枚举映射（功能1）
4. 保存修改后的规则并自动管理实体

输入格式：
- 包含解析规则的Base64编码JSON文件
- Excel映射模板包含多个Sheet：
  - 每个Sheet名称 = 原始字段名（来自JSON中的索引数组）
  - 列：mappingType, orgValue, mappingValue

输出：
- 修改后的Base64编码JSON文件
- 自动向simEntities数组中添加实体（如果不存在）
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import os
import json
import base64
import binascii
import re
from openpyxl import load_workbook
from collections import defaultdict
from src.threat_type_manager import ThreatTypeManager


class Feature5MappingAll:
    def __init__(self, gui_handler):
        self.gui = gui_handler
        self.feature5_frame = None
        self.original_rules_path = tk.StringVar()
        self.mapping_file_path = tk.StringVar()
        self.parsed_config = None
        self.status_text = None
        self.log_messages = []
        self.field_mapping_entries = []
        self.field_mapping_confirmed = False
        self.threat_manager = ThreatTypeManager()

    def log(self, message):
        """Log message to feature5's own log area only"""
        print(message)
        self.log_messages.append(message)
        if self.status_text:
            self.status_text.config(state=tk.NORMAL)
            self.status_text.insert(tk.END, message + "\n")
            self.status_text.see(tk.END)
            self.status_text.config(state=tk.DISABLED)

    def show_feature5_panel(self):
        """Display Feature 5 panel"""
        content_frame = self.gui.content_frame

        for widget in content_frame.winfo_children():
            widget.pack_forget()

        if not self.feature5_frame:
            self.create_feature5_panel(content_frame)
            self.log("功能5面板已启动")
            self.log("请上传原始解析规则和映射模板文件")
        else:
            self.feature5_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    def create_feature5_panel(self, parent_frame):
        """Create Feature 5 UI"""
        self.feature5_frame = ttk.Frame(parent_frame)
        self.feature5_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        input_frame = ttk.LabelFrame(self.feature5_frame, text="文件输入", padding=10)
        input_frame.pack(fill=tk.X, padx=10, pady=5)

        ttk.Label(input_frame, text="原始解析规则 (Base64):").grid(row=0, column=0, sticky="w", pady=5)
        ttk.Entry(input_frame, textvariable=self.original_rules_path, width=50).grid(
            row=0, column=1, padx=5, pady=5
        )
        ttk.Button(input_frame, text="浏览", command=self.browse_original_rules, width=10).grid(
            row=0, column=2, pady=5
        )

        ttk.Label(input_frame, text="映射模板 (Excel):").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(input_frame, textvariable=self.mapping_file_path, width=50).grid(
            row=1, column=1, padx=5, pady=5
        )
        ttk.Button(input_frame, text="浏览", command=self.browse_mapping_file, width=10).grid(
            row=1, column=2, pady=5
        )

        field_mapping_frame = ttk.LabelFrame(self.feature5_frame, text="字段映射配置 (可选)", padding=10)
        field_mapping_frame.pack(anchor="w", padx=10, pady=5)

        header_frame = ttk.Frame(field_mapping_frame)
        header_frame.pack(anchor="w", pady=(0, 5))
        ttk.Label(header_frame, text="原始字段名", width=18, anchor="center", font=('SimHei', 9, 'bold')).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(header_frame, text="标准字段名", width=18, anchor="center", font=('SimHei', 9, 'bold')).pack(side=tk.LEFT)

        self.field_mapping_entries = []
        
        field_mapping_content_frame = ttk.Frame(field_mapping_frame)
        field_mapping_content_frame.pack(anchor="w")
        
        left_frame = ttk.Frame(field_mapping_content_frame)
        left_frame.pack(side=tk.LEFT)
        
        for i in range(5):
            row_frame = ttk.Frame(left_frame)
            row_frame.pack(anchor="w", pady=2)
            
            original_entry = ttk.Entry(row_frame, width=20)
            original_entry.pack(side=tk.LEFT, padx=(0, 5))
            
            standard_entry = ttk.Entry(row_frame, width=20)
            standard_entry.pack(side=tk.LEFT)
            
            self.field_mapping_entries.append({
                'original': original_entry,
                'standard': standard_entry
            })
            
            if i == 4:
                ttk.Button(row_frame, text="确认", command=self.confirm_field_mapping, width=8).pack(side=tk.LEFT, padx=(10, 0))

        quick_field_frame = ttk.LabelFrame(field_mapping_content_frame, text="常用字段名", padding=5)
        quick_field_frame.pack(side=tk.LEFT, padx=(20, 0))

        common_fields = ["日志类型", "事件类型", "威胁名称", "威胁类型", "威胁信息"]

        def fill_standard_field(field_name):
            """填充标准字段名到第一个空的标准字段输入框"""
            for entry_pair in self.field_mapping_entries:
                current_value = entry_pair['standard'].get().strip()
                if current_value == field_name:
                    messagebox.showwarning("重复警告", f"标准字段名【{field_name}】已存在，请选择其他字段名")
                    return
                    
            for entry_pair in self.field_mapping_entries:
                current_value = entry_pair['standard'].get().strip()
                if not current_value:
                    entry_pair['standard'].insert(0, field_name)
                    break

        for field_name in common_fields:
            ttk.Button(
                quick_field_frame,
                text=field_name,
                command=lambda f=field_name: fill_standard_field(f),
                width=10
            ).pack(pady=2)

        ttk.Label(quick_field_frame, text="(点击填充)", font=('SimHei', 8), foreground="gray").pack(pady=(5, 0))

        ttk.Label(field_mapping_frame, text="提示: 如果映射模板的Sheet名是原始字段名(如srcip)，需要在此配置对应的标准字段名(如源地址)，\n"
                                          "系统会先根据此配置转换为标准字段名，再进行实体映射和枚举添加。",
                  font=('SimHei', 8), foreground="gray").pack(anchor="w", pady=(5, 0))

        button_frame = ttk.Frame(self.feature5_frame)
        button_frame.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(
            button_frame,
            text="处理映射",
            command=self.process_feature5,
            width=15
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            button_frame,
            text="下载模板",
            command=self.download_template,
            width=12
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            button_frame,
            text="保存结果",
            command=self.save_result,
            width=12
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            button_frame,
            text="清空",
            command=self.clear_fields,
            width=10
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            button_frame,
            text="使用说明",
            command=self.show_help,
            width=10
        ).pack(side=tk.LEFT, padx=(0, 10))

        status_frame = ttk.LabelFrame(self.feature5_frame, text="处理日志", padding=10)
        status_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        status_header_frame = ttk.Frame(status_frame)
        status_header_frame.pack(fill=tk.X, pady=(0, 5))
        ttk.Button(status_header_frame, text="查看完整日志", command=self.show_full_log, width=12).pack(side=tk.RIGHT)

        self.status_text = tk.Text(
            status_frame,
            height=10,
            wrap=tk.WORD,
            bg="#f0f0f0",
            font=('Courier New', 9)
        )
        scrollbar = ttk.Scrollbar(
            status_frame,
            orient=tk.VERTICAL,
            command=self.status_text.yview
        )
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.status_text.pack(fill=tk.BOTH, expand=True)
        self.status_text.config(yscrollcommand=scrollbar.set)
        self.status_text.config(state=tk.DISABLED)

    def browse_original_rules(self):
        """Browse and select original rules file"""
        file_path = filedialog.askopenfilename(
            title="选择原始解析规则文件",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")]
        )
        if file_path:
            self.original_rules_path.set(file_path)
            self.log(f"已选择原始规则文件: {os.path.basename(file_path)}")

    def browse_mapping_file(self):
        """Browse and select mapping template file"""
        file_path = filedialog.askopenfilename(
            title="选择映射模板文件",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        if file_path:
            self.mapping_file_path.set(file_path)
            self.log(f"已选择映射模板文件: {os.path.basename(file_path)}")

    def load_standard_properties(self):
        """Load system property to field/entity mappings from 对象.xlsx

        Returns:
            prop_to_field: dict mapping system property name -> field name
            field_to_entity: dict mapping field name -> entity name
            prop_to_entity: dict mapping system property name -> entity name
        """
        import sys
        if getattr(sys, 'frozen', False) and getattr(sys, '_MEIPASS', None):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        fixed_file = os.path.join(base_path, "config", "对象.xlsx")
        prop_to_field = {}
        field_to_entity = {}
        prop_to_entity = {}

        if not os.path.exists(fixed_file):
            self.log(f"错误: 固定文件不存在: {fixed_file}")
            return None, None, None

        self.log(f"加载标准属性文件: {os.path.basename(fixed_file)}")

        try:
            wb = load_workbook(fixed_file, read_only=True, data_only=True)

            if '对应关系' in wb.sheetnames:
                ws = wb['对应关系']

                headers = []
                for col in range(1, ws.max_column + 1):
                    cell_value = ws.cell(row=1, column=col).value
                    headers.append(str(cell_value) if cell_value is not None else '')

                prop_col_idx = None
                field_col_idx = None
                entity_col_idx = None

                for i, header in enumerate(headers):
                    if '系统属性' in header or '属性' in header:
                        prop_col_idx = i + 1
                    if '字段名称' in header or '字段' in header:
                        field_col_idx = i + 1
                    if '对象' in header or '实体' in header:
                        entity_col_idx = i + 1

                if prop_col_idx and field_col_idx:
                    row_count = 0
                    mapping_count = 0
                    for row in ws.iter_rows(min_row=2, values_only=True):
                        row_count += 1
                        if len(row) >= max(prop_col_idx, field_col_idx, entity_col_idx or 0):
                            prop_name = row[prop_col_idx - 1]
                            field_name = row[field_col_idx - 1]
                            entity_name = row[entity_col_idx - 1] if entity_col_idx else None

                            if prop_name and field_name:
                                prop_str = str(prop_name).strip()
                                field_str = str(field_name).strip()
                                prop_to_field[prop_str] = field_str
                                field_to_entity[field_str] = field_str
                                mapping_count += 1

                            if prop_name and entity_name:
                                prop_str = str(prop_name).strip()
                                entity_str = str(entity_name).strip().split(',')[0].strip()
                                prop_to_entity[prop_str] = entity_str

                    self.log(f"  从对应关系表加载 {mapping_count} 个属性映射")
                    self.log(f"  系统属性数量: {len(prop_to_field)}, 字段数量: {len(field_to_entity)}")
                else:
                    self.log("错误: 未找到系统属性名称或字段名称列")
            else:
                self.log("错误: 对象.xlsx中未找到'对应关系'工作表")

            wb.close()
            return prop_to_field, field_to_entity, prop_to_entity

        except Exception as e:
            self.log(f"加载标准属性文件时出错: {str(e)}")
            import traceback
            self.log(f"详细错误: {traceback.format_exc()}")
            return None, None, None

    def process_feature5(self):
        """Main processing function for Feature 5"""
        self.log("=" * 50)
        self.log("开始处理功能5：融合字段映射和枚举添加")
        self.log("=" * 50)

        original_path = self.original_rules_path.get().strip()
        mapping_file = self.mapping_file_path.get().strip()

        if not original_path or not os.path.exists(original_path):
            self.log("错误: 请选择有效的原始解析规则文件")
            return

        if not mapping_file or not os.path.exists(mapping_file):
            self.log("错误: 请选择有效的映射模板文件")
            return

        try:
            self.log("\n[步骤1] 读取原始解析规则文件")
            with open(original_path, 'rb') as f:
                base64_data = f.read()

            if not base64_data:
                self.log("错误: 原始规则文件为空")
                return

            try:
                decoded_data = base64.b64decode(base64_data, validate=False)
                json_str = decoded_data.decode('utf-8')
                self.parsed_config = json.loads(json_str)
                self.log("成功解码Base64并读取JSON配置")
            except (binascii.Error, json.JSONDecodeError) as e:
                self.log(f"解码失败: {str(e)}")
                return

            self.log("\n[步骤2] 加载对象.xlsx标准属性映射")
            prop_to_field, field_to_entity, prop_to_entity = self.load_standard_properties()
            if prop_to_field is None:
                return

            self.log("\n[步骤2.5] 解析字段映射配置")
            custom_field_mapping = {}
            if self.field_mapping_confirmed and hasattr(self, 'field_mapping_dict'):
                for original_field, standard_field in self.field_mapping_dict.items():
                    custom_field_mapping[original_field] = standard_field
                    self.log(f"  自定义字段映射: {original_field} -> {standard_field}")
                self.log(f"  共加载 {len(custom_field_mapping)} 个自定义字段映射")
            elif self.field_mapping_entries:
                for entry_pair in self.field_mapping_entries:
                    original = entry_pair['original'].get().strip()
                    standard = entry_pair['standard'].get().strip()
                    if original and standard:
                        custom_field_mapping[original] = standard
                if custom_field_mapping:
                    for original_field, standard_field in custom_field_mapping.items():
                        self.log(f"  自定义字段映射: {original_field} -> {standard_field}")
                    self.log(f"  共加载 {len(custom_field_mapping)} 个自定义字段映射")
                else:
                    self.log("  未配置自定义字段映射")
            else:
                self.log("  字段映射配置控件不存在")

            self.log("\n[步骤3] 读取映射模板中的所有Sheet")
            wb = load_workbook(mapping_file, read_only=True, data_only=True)

            sheet_names = wb.sheetnames
            self.log(f"映射模板包含 {len(sheet_names)} 个工作表: {sheet_names}")

            if not sheet_names:
                self.log("错误: 映射模板中没有工作表")
                wb.close()
                return

            self.log("\n[步骤4] 处理每个Sheet的映射规则")

            normalize = self.parsed_config[0].get('normalize', [])
            sim_entities = self.parsed_config[0].get('simEntities', [])
            total_mappings_added = 0
            total_entities_added = 0

            for sheet_name in sheet_names:
                self.log(f"\n处理工作表: {sheet_name}")
                ws = wb[sheet_name]

                current_field = sheet_name
                converted_from = None

                if custom_field_mapping and sheet_name in custom_field_mapping:
                    current_field = custom_field_mapping[sheet_name]
                    converted_from = sheet_name
                    self.log(f"  字段名转换: {sheet_name} -> {current_field}")

                sheet_mappings = []
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if len(row) >= 3 and row[0] is not None and row[1] is not None:
                        mapping_type = str(row[0]).strip().upper()
                        raw_org_value = str(row[1]).strip()
                        raw_mapping_value = str(row[2]).strip() if row[2] is not None else ''

                        if mapping_type == "REGULAR":
                            if not raw_org_value.startswith(".*"):
                                raw_org_value = ".*" + raw_org_value
                            if not raw_org_value.endswith(".*"):
                                raw_org_value = raw_org_value + ".*"

                        if current_field in ['threat_type', 'threatType', '威胁类型']:
                            if raw_mapping_value:
                                mapping_value = self.threat_manager.find_matching_threat_type(raw_mapping_value)
                            else:
                                mapping_value = self.threat_manager.find_matching_threat_type(raw_org_value)
                        else:
                            mapping_value = raw_mapping_value if raw_mapping_value else raw_org_value

                        sheet_mappings.append({
                            'mappingType': mapping_type,
                            'orgValue': raw_org_value,
                            'mappingValue': mapping_value
                        })

                self.log(f"  读取到 {len(sheet_mappings)} 条映射规则")

                if not sheet_mappings:
                    continue

                is_system_property = prop_to_field and current_field in prop_to_field
                is_system_property_in_entity = prop_to_entity and current_field in prop_to_entity

                if is_system_property or is_system_property_in_entity:
                    self.log(f"  字段 '{current_field}' 是系统属性名称")
                    entity = None
                    standard_field = None

                    if is_system_property:
                        standard_field = prop_to_field[current_field]
                        self.log(f"  获取标准字段名: {standard_field}")

                    if is_system_property_in_entity and prop_to_entity:
                        entity = prop_to_entity[current_field]
                        self.log(f"  获取实体: {entity}")
                    elif field_to_entity and standard_field and standard_field in field_to_entity:
                        entity = field_to_entity[standard_field]
                        self.log(f"  从field_to_entity获取实体: {entity}")

                    if entity and entity not in sim_entities:
                        sim_entities.append(entity)
                        self.parsed_config[0]['simEntities'] = sim_entities
                        self.log(f"  添加新实体 '{entity}' 到 simEntities")
                        total_entities_added += 1

                    target_field = standard_field if standard_field else current_field

                    mappings_added = self.add_enumeration_mappings(
                        normalize,
                        sheet_name,
                        target_field,
                        entity,
                        sheet_mappings
                    )
                    total_mappings_added += mappings_added
                    self.log(f"  添加 {mappings_added} 条枚举映射到字段 '{target_field}'")
                else:
                    self.log(f"  字段 '{current_field}' 不是系统属性名称，仅添加枚举映射")
                    mappings_added = self.add_enumeration_mappings(
                        normalize,
                        sheet_name,
                        current_field,
                        None,
                        sheet_mappings
                    )
                    total_mappings_added += mappings_added
                    self.log(f"  添加 {mappings_added} 条枚举映射")

            wb.close()

            self.log("\n[步骤5] 处理完成")
            self.log(f"共添加 {total_mappings_added} 条枚举映射")
            self.log(f"共添加 {total_entities_added} 个新实体到 simEntities")
            self.log(f"simEntities当前包含: {sim_entities}")
            self.log("\n处理完成！可点击'保存结果'按钮保存处理后的规则")

        except Exception as e:
            self.log(f"处理过程中出错: {str(e)}")
            import traceback
            self.log(f"详细错误: {traceback.format_exc()}")

    def add_enumeration_mappings(self, normalize, original_field, target_field, entity, mappings):
        """向normalize数组添加枚举映射

        Args:
            normalize: 配置中的normalize数组
            original_field: 原始字段名（Sheet名称）
            target_field: 目标字段名（标准字段）
            entity: 实体名称（来自功能4）
            mappings: 来自Excel的{mappingType, orgValue, mappingValue}列表

        Returns:
            添加的映射数量
        """
        mappings_added = 0
        mappings_logged = 0
        max_log = 10

        matched_item = None
        match_type = None

        for item in normalize:
            index_value = item.get('index', '')
            result = item.get('result', [])

            if index_value and original_field in index_value:
                matched_item = item
                match_type = 'index'
                if mappings_logged < max_log:
                    self.log(f"    通过index匹配到normalize项: index={index_value}, field={item.get('field')}")
                break
            elif original_field in result:
                matched_item = item
                match_type = 'result'
                if mappings_logged < max_log:
                    self.log(f"    通过result匹配到normalize项: index={item.get('index')}, field={item.get('field')}")
                break

        if matched_item:
            if target_field:
                matched_item['field'] = target_field

            if entity:
                matched_item['entity'] = entity

            if 'mappings' not in matched_item:
                matched_item['mappings'] = []

            for mapping in mappings:
                exists = any(
                    m.get('orgValue') == mapping['orgValue']
                    for m in matched_item['mappings']
                )
                if not exists:
                    matched_item['mappings'].append(mapping)
                    mappings_added += 1
                    if mappings_logged < max_log:
                        self.log(f"    添加映射: {mapping['mappingType']} | {mapping['orgValue']} -> {mapping['mappingValue']}")
                        mappings_logged += 1
        else:
            self.log(f"    未找到匹配的normalize项，尝试创建新项")
            self.log(f"    original_field={original_field}, target_field={target_field}, entity={entity}")

            new_item = {
                'core': None,
                'entity': entity if entity else None,
                'field': target_field if target_field else original_field,
                'index': f'"{original_field}"' if original_field else '',
                'info': [],
                'mappings': [],
                'required': False,
                'result': [],
                'sim': True if entity else None,
                'value': None
            }

            for mapping in mappings:
                new_item['mappings'].append(mapping)
                mappings_added += 1
                if mappings_logged < max_log:
                    self.log(f"    添加映射: {mapping['mappingType']} | {mapping['orgValue']} -> {mapping['mappingValue']}")
                    mappings_logged += 1

            normalize.append(new_item)
            self.log(f"    已创建新的normalize项并添加 {mappings_added} 条枚举映射")

        if mappings_added > max_log:
            self.log(f"    ... 还有 {mappings_added - max_log} 条映射已添加（不逐一显示）")

        return mappings_added

    def download_template(self):
        """Download mapping template file"""
        file_path = filedialog.asksaveasfilename(
            title="保存映射模板",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx")],
            initialfile="mapping_template.xlsx"
        )
        if file_path:
            try:
                from openpyxl import Workbook
                wb = Workbook()
                ws = wb.active
                if ws is not None:
                    ws.title = "示例字段名"
                else:
                    ws = wb.create_sheet("示例字段名")

                ws['A1'] = 'mappingType'
                ws['B1'] = 'orgValue'
                ws['C1'] = 'mappingValue(若标准字段为威胁类型，此列可删除，后台自动匹配)'

                ws['A2'] = 'EQUAL'
                ws['B2'] = '原始值1'
                ws['C2'] = '映射值1'

                ws['A3'] = 'REGULAR'
                ws['B3'] = '^正则.*匹配$'
                ws['C3'] = '映射值2'

                wb.save(file_path)
                self.log(f"已下载映射模板: {os.path.basename(file_path)}")
                messagebox.showinfo("成功", "映射模板下载成功！")
            except Exception as e:
                self.log(f"下载模板失败: {str(e)}")
                messagebox.showerror("错误", f"下载模板失败: {str(e)}")

    def save_result(self):
        """Save processed result to file"""
        if not self.parsed_config:
            self.log("错误: 没有可保存的处理结果，请先执行处理操作")
            messagebox.showwarning("警告", "请先执行处理操作")
            return

        original_path = self.original_rules_path.get().strip()
        if original_path:
            default_name = f"modified_{os.path.basename(original_path)}"
        else:
            default_name = "modified_rules.txt"

        file_path = filedialog.asksaveasfilename(
            title="保存处理结果",
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
            initialfile=default_name
        )
        if file_path:
            try:
                json_str = json.dumps(self.parsed_config, ensure_ascii=False, indent=2)
                base64_data = base64.b64encode(json_str.encode('utf-8')).decode('ascii')

                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(base64_data)

                self.log(f"已保存处理结果: {os.path.basename(file_path)}")
                messagebox.showinfo("成功", "处理结果保存成功！")
            except Exception as e:
                self.log(f"保存结果失败: {str(e)}")
                messagebox.showerror("错误", f"保存结果失败: {str(e)}")

    def clear_fields(self):
        """清空所有输入字段"""
        self.original_rules_path.set("")
        self.mapping_file_path.set("")
        for entry_pair in self.field_mapping_entries:
            entry_pair['original'].delete(0, tk.END)
            entry_pair['standard'].delete(0, tk.END)
        self.field_mapping_confirmed = False
        self.parsed_config = None
        self.log_messages = []
        if self.status_text:
            self.status_text.config(state=tk.NORMAL)
            self.status_text.delete("1.0", tk.END)
            self.status_text.config(state=tk.DISABLED)
        self.log("已清空所有字段")

    def confirm_field_mapping(self):
        """确认字段映射配置"""
        mappings = {}
        for entry_pair in self.field_mapping_entries:
            original = entry_pair['original'].get().strip()
            standard = entry_pair['standard'].get().strip()
            if original and standard:
                mappings[original] = standard
        
        if mappings:
            self.field_mapping_dict = mappings
            self.field_mapping_confirmed = True
            self.log(f"已确认 {len(mappings)} 条字段映射: {mappings}")
            messagebox.showinfo("确认成功", f"已确认 {len(mappings)} 条字段映射\n下一步请进行【处理映射】操作")
        else:
            self.field_mapping_confirmed = False
            messagebox.showwarning("未配置映射", "未配置任何字段映射，将直接使用原始字段名")

    def show_full_log(self):
        """显示完整处理日志"""
        log_window = tk.Toplevel(self.gui.root)
        log_window.title("完整处理日志")
        log_window.geometry("700x500")
        log_window.transient(self.gui.root)
        
        text_widget = tk.Text(log_window, wrap=tk.WORD, font=('Courier New', 9))
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(text_widget, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        for message in self.log_messages:
            text_widget.insert(tk.END, message + "\n")
        text_widget.config(state=tk.DISABLED)
        
        button_frame = ttk.Frame(log_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="关闭", command=log_window.destroy, width=10).pack(side=tk.RIGHT)
        ttk.Button(button_frame, text="复制到剪贴板", command=lambda: self.copy_log_to_clipboard(text_widget), width=15).pack(side=tk.RIGHT, padx=(0, 10))

    def copy_log_to_clipboard(self, text_widget):
        """复制日志到剪贴板"""
        log_content = "".join(self.log_messages)
        self.gui.root.clipboard_clear()
        self.gui.root.clipboard_append(log_content)
        messagebox.showinfo("已复制", "日志已复制到剪贴板")

    def show_help(self):
        """显示使用说明"""
        help_text = """【功能5：字段映射集合】使用说明

本功能整合了功能1（带枚举的字段映射）和功能4（标准字段映射），提供统一的工作流程。

一、操作步骤：
1. 上传原始Base64编码的解析规则文件
2. 上传包含多个Sheet的字段映射模板（Excel文件）
3. 配置字段映射关系（可选）
4. 点击"处理映射"按钮执行处理
5. 点击"保存结果"按钮保存处理后的规则

二、映射模板格式：
- Excel文件可以包含多个Sheet
- 每个Sheet名称 = 原始字段名（来自解析规则中的索引数组）
- Sheet包含三列：mappingType, orgValue, mappingValue
  * mappingType: 映射类型（replace/add）
  * orgValue: 原始值
  * mappingValue: 映射值

三、字段映射配置（可选）：
- 如果映射模板的Sheet名是原始字段名，需要在此配置对应的标准字段名
- 格式: 原始字段名=标准字段名（每行一个）
- 示例: srcip=源地址

四、处理逻辑：
- 如果Sheet名称是对象.xlsx中的系统属性名：
  1. 先获取实体（功能4）
  2. 再添加枚举映射（功能1）
- 如果Sheet名称不是系统属性名：
  仅添加枚举映射（功能1）

五、输出：
- 修改后的Base64编码JSON文件
- 自动向simEntities数组中添加实体（如果不存在）"""
        
        help_window = tk.Toplevel(self.gui.root)
        help_window.title("功能5使用说明")
        help_window.geometry("600x500")
        help_window.transient(self.gui.root)
        help_window.grab_set()
        
        text_widget = tk.Text(help_window, wrap=tk.WORD, font=('SimHei', 10))
        text_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        scrollbar = ttk.Scrollbar(text_widget, orient=tk.VERTICAL, command=text_widget.yview)
        text_widget.config(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        text_widget.insert(tk.END, help_text)
        text_widget.config(state=tk.DISABLED)
        
        button_frame = ttk.Frame(help_window)
        button_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        
        ttk.Button(button_frame, text="关闭", command=help_window.destroy, width=10).pack(side=tk.RIGHT)
