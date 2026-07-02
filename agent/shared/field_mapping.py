"""
字段映射处理模块

从 config/对象.xlsx 读取系统属性名称 → 英文字段名 → 实体 的映射关系
提供填充功能
"""
import os
import json
import base64
from openpyxl import load_workbook


class FieldMappingHandler:
    """字段映射处理器"""
    
    def __init__(self):
        self.prop_to_field = {}  # 系统属性名称 → 字段名称（英文）
        self.field_to_entity = {}  # 字段名称 → 实体（对象）名称
        self.load_config()
    
    def load_config(self):
        """从 config/对象.xlsx 加载映射关系"""
        # __file__ = agent/shared/field_mapping.py
        # dirname*3 → 项目根目录 toolswithagent/
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "对象.xlsx"
        )
        
        if not os.path.exists(config_path):
            print(f"[WARN] 配置文件不存在: {config_path}")
            return
        
        try:
            wb = load_workbook(config_path, read_only=True, data_only=True)
            
            if '对应关系' in wb.sheetnames:
                ws = wb['对应关系']
                
                headers = []
                if ws.max_row >= 1:
                    for col in range(1, ws.max_column + 1):
                        cell_value = ws.cell(row=1, column=col).value
                        headers.append(str(cell_value) if cell_value is not None else '')
                
                # 查找列索引
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
                                entity_name = str(entity_name).strip()
                                
                                # 处理多个对象的情况，取第一个
                                if ',' in entity_name:
                                    entity_name = entity_name.split(',')[0].strip()
                                
                                self.prop_to_field[prop_name] = field_name
                                self.field_to_entity[field_name] = entity_name
                    
                    print(f"[INFO] 加载映射配置: {len(self.prop_to_field)} 个系统属性, {len(self.field_to_entity)} 个字段实体")
            
            wb.close()
            
        except Exception as e:
            print(f"[ERROR] 加载配置文件失败: {str(e)}")
    
    def get_field_from_prop(self, prop_name: str) -> str:
        """根据系统属性名称获取英文字段名"""
        return self.prop_to_field.get(prop_name)
    
    def get_entity_from_field(self, field_name: str) -> str:
        """根据英文字段名获取实体名称"""
        return self.field_to_entity.get(field_name)
    
    def apply_field_mapping(self, config: list, mapping_table: list) -> tuple:
        """
        应用字段映射到配置
        
        Args:
            config: 原始配置（JSON对象列表）
            mapping_table: 映射表
                [
                    {"原始字段名": "xxx", "系统属性名称": "yyy", "匹配状态": "zzz"},
                    ...
                ]
        
        Returns:
            tuple: (更新后的配置, 更新数量)
        """
        if not config or not mapping_table:
            return config, 0
        
        # 获取 normalize 数组
        normalize = config[0].get('normalize', [])
        updated_count = 0
        
        for rule in mapping_table:
            original_field = rule.get('原始字段名', '')
            system_prop = rule.get('系统属性名称', '')
            match_status = rule.get('匹配状态', '')
            
            # 只处理匹配成功的
            if '匹配成功' not in match_status:
                continue
            
            if not original_field or not system_prop:
                continue
            
            # 获取英文字段名和实体
            standard_field = self.get_field_from_prop(system_prop)
            if not standard_field:
                print(f"[WARN] 未找到系统属性 '{system_prop}' 对应的英文字段名")
                continue
            
            entity = self.get_entity_from_field(standard_field)
            if not entity:
                print(f"[WARN] 未找到字段 '{standard_field}' 对应的实体")
                continue
            
            # 查找匹配的 normalize 项
            original_key = str(original_field).strip()
            original_key_lower = original_key.lower()
            
            matched_item = None
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
                
                # 匹配逻辑
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
                # 更新字段
                matched_item['field'] = standard_field
                matched_item['entity'] = entity
                matched_item['core'] = False
                matched_item['sim'] = True
                
                # 更新 simEntities
                sim_entities = config[0].get('simEntities', [])
                if entity and entity not in sim_entities:
                    sim_entities.append(entity)
                    config[0]['simEntities'] = sim_entities
                
                updated_count += 1
            else:
                print(f"[INFO] 未找到匹配项，创建新项: {original_key} -> {standard_field}")
                new_item = {
                    'core': False,
                    'entity': entity,
                    'field': standard_field,
                    'index': original_key,
                    'info': [],
                    'required': False,
                    'result': [],
                    'sim': True,
                    'value': None
                }
                normalize.append(new_item)
                
                sim_entities = config[0].get('simEntities', [])
                if entity and entity not in sim_entities:
                    sim_entities.append(entity)
                    config[0]['simEntities'] = sim_entities
                
                updated_count += 1
        
        print(f"[INFO] 字段映射完成: 共更新 {updated_count} 个映射规则")
        return config, updated_count
    
    def export_to_base64(self, config: list) -> str:
        """将配置导出为 Base64 编码"""
        json_str = json.dumps(config, ensure_ascii=False, separators=(',', ':'))
        base64_data = base64.b64encode(json_str.encode('utf-8')).decode('utf-8')
        return base64_data


# 全局实例
_handler = None

def get_field_mapping_handler() -> FieldMappingHandler:
    """获取全局字段映射处理器"""
    global _handler
    if _handler is None:
        _handler = FieldMappingHandler()
    return _handler