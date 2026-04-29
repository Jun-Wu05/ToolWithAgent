import os
import base64
import binascii
import json
import threading
import re
from openpyxl import load_workbook
import tkinter as tk
from tkinter import messagebox, filedialog
from tkinter import ttk
from collections import defaultdict
from src.threat_type_manager import ThreatTypeManager
import pandas as pd
import chardet
from datetime import datetime
import time

class DataProcessor:
    def __init__(self, app):
        self.app = app
        # 初始化ThreatTypeManager实例
        self.threat_manager = ThreatTypeManager()
        # 性能优化：Excel文件缓存
        self._excel_cache = {}
        
    def read_mappings_from_excel(self, excel_file, use_cache=True):
        """使用openpyxl高效读取Excel映射数据
        读取每个工作表的前三列数据:
        - 第一列: mappingType (EQUAL或REGULAR)
        - 第二列: orgValue (匹配值)
        - 第三列: mappingValue (映射值)
        返回格式: {sheet_name: mappings_list}
        
        Args:
            excel_file: Excel文件路径
            use_cache: 是否使用缓存（默认True）
        """
        try:
            # 检查文件是否存在
            if not os.path.exists(excel_file):
                self.app.log_message("错误: Excel文件不存在")
                return None

            # 性能优化：检查缓存
            if use_cache and excel_file in self._excel_cache:
                filename = os.path.basename(excel_file)
                self.app.log_message(f"从缓存读取Excel文件: {filename}")
                return self._excel_cache[excel_file]

            invalid_type_count = 0
            valid_mapping_types = {"EQUAL", "REGULAR"}
            all_mappings = defaultdict(list)  # 使用defaultdict简化代码
            
            # 加载工作簿 (不使用with语句以避免类型检查错误)
            wb = load_workbook(excel_file, read_only=True, data_only=True)
            try:
                # 遍历所有工作表
                for sheet_name in wb.sheetnames:
                    ws = wb[sheet_name]
                    sheet_mappings = []
                    
                    for row in ws.iter_rows(min_row=2, max_col=3,
                                            values_only=True):
                        # 过滤空行和匹配值为空的行
                        if row[1] is None:
                            continue
                        
                        # 读取映射类型，如果为空或无效则默认为EQUAL
                        if row[0] is not None:
                            mapping_type = str(row[0]).upper()
                        else:
                            mapping_type = "EQUAL"
                        if mapping_type not in valid_mapping_types:
                            mapping_type = "EQUAL"
                            invalid_type_count += 1
                        
                        raw_org_value = str(row[1])
                        org_value = raw_org_value
                        # 对于REGULAR类型，在orgValue前后添加.*通配符（避免重复添加）
                        if mapping_type == "REGULAR":
                            # 检查是否已经有通配符
                            if not org_value.startswith(".*"):
                                org_value = ".*" + org_value
                            if not org_value.endswith(".*"):
                                org_value = org_value + ".*"
                        
                        # 如果mappingValue为空或None，则使用orgValue作为输入来查找匹配的威胁类型
                        if row[2] is not None:
                            raw_map_value = str(row[2])
                        else:
                            raw_map_value = ""
                        
                        # 只有当工作表名称与威胁类型相关时，才应用威胁类型标准化
                        # 否则保持1:1的映射关系
                        threat_type_sheets = ['threat_type', 'threatType', '威胁类型']
                        is_threat_type_sheet = any(
                            keyword in sheet_name.lower() 
                            for keyword in threat_type_sheets
                        )
                        
                        if is_threat_type_sheet:
                            # 使用ThreatTypeManager将mappingValue标准化为配置文件中的标准威胁类型名称
                            # 如果raw_map_value为空，则使用orgValue作为输入进行匹配
                            if raw_map_value.strip():
                                input_for_matching = raw_map_value
                            else:
                                input_for_matching = raw_org_value
                            standard_map_value = self.threat_manager.find_matching_threat_type(input_for_matching, mapping_type)
                        else:
                            # 非威胁类型字段保持1:1映射
                            if raw_map_value.strip():
                                standard_map_value = raw_map_value
                            else:
                                standard_map_value = raw_org_value
                        
                        # 如果mappingValue为空，记录一下使用了orgValue来补充
                        if not raw_map_value.strip():
                            message = f"提示: 为 '{raw_org_value}' 自动补充映射值为 '{standard_map_value}'"
                            self.app.log_message(message)
                        
                        sheet_mappings.append({
                            "mappingType": mapping_type,
                            "orgValue": org_value,
                            "mappingValue": standard_map_value
                        })
                    
                    if sheet_mappings:
                        all_mappings[sheet_name] = sheet_mappings
                        count = len(sheet_mappings)
                        message = f"从工作表 '{sheet_name}' 读取 {count} 个映射关系"
                        self.app.log_message(message)
            finally:
                wb.close()
                
            # 性能优化：将结果存入缓存
            if use_cache and all_mappings:
                self._excel_cache[excel_file] = dict(all_mappings)
                

            
            if invalid_type_count > 0:
                message = f"警告: {invalid_type_count} 条记录的映射类型无效，已默认设为EQUAL"
                self.app.log_message(message)
            
            if not all_mappings:
                self.app.log_message("错误: Excel文件中没有有效数据（可能只有表头）")
                return None
            
            # 显示前10条处理结果
            self.app.log_message("\n=== 前10条威胁类型映射处理结果 ===")
            display_count = 0
            max_display = 10
            
            for sheet_name, mappings in all_mappings.items():
                for mapping in mappings:
                        if display_count < max_display:
                            # 格式化显示原始值和标准化后的值
                            # 提取原始值（去掉.*通配符）
                            display_org_value = mapping['orgValue'].replace(
                                ".*", ""
                            )
                            if display_org_value != mapping['mappingValue']:
                                message = f"{sheet_name} - {display_org_value} → {mapping['mappingValue']}"
                                self.app.log_message(message)
                            else:
                                message = f"{sheet_name} - {display_org_value}"
                                self.app.log_message(message)
                            display_count += 1
                        else:
                            break
                if display_count >= max_display:
                    break
            
            if display_count < max_display:
                self.app.log_message(f"\n共处理 {display_count} 条记录")
            else:
                total_records = sum(len(mappings) for mappings in all_mappings.values())
                message = f"\n共处理 {total_records} 条记录，仅显示前{max_display}条"
                self.app.log_message(message)
            
            self.app.log_message(f"\n成功从Excel读取 {len(all_mappings)} 个工作表的映射数据")
            return all_mappings
            
        except Exception as e:
            self.app.log_message(f"读取Excel文件时出错: {str(e)}")
            return None
    
    def process_data(self):
        """处理数据的主要函数（在后台线程运行）"""
        try:
            base64_file = self.app.base64_file_path.get().strip()
            excel_file = self.app.excel_file_path.get().strip()
            index_values = self.app.index_value.get().strip()
            output_json = self.app.output_json.get()
            
            # 验证输入
            if not base64_file or not os.path.exists(base64_file):
                self.app.log_message("错误: 请选择有效的Base64编码文件")
                return
            
            if not excel_file or not os.path.exists(excel_file):
                self.app.log_message("错误: 请选择有效的Excel映射文件")
                return
            
            if not index_values:
                self.app.log_message("错误: 请输入normalize index值")
                return
            
            # 解析多个index值（逗号分隔）
            index_list = [
                idx.strip() for idx in index_values.split(',') 
                if idx.strip()
            ]
            if not index_list:
                self.app.log_message("错误: 请输入有效的normalize index值")
                return
            
            self.app.log_message("开始处理数据...")
            
            # 读取Excel文件中的映射（按sheet名称组织）
            sheet_mappings = self.read_mappings_from_excel(excel_file)
            if not sheet_mappings:
                return
            
            # 读取并解码Base64 (使用缓冲区读取大文件)
            try:
                # 性能优化：检查文件大小
                file_size = os.path.getsize(base64_file)
                file_size_mb = file_size / (1024 * 1024)
                self.app.log_message(f"Base64文件大小: {file_size_mb:.2f} MB")
                
                # 大文件警告
                if file_size_mb > 50:
                    self.app.log_message("警告: 文件较大（>50MB），处理可能需要较长时间")
                
                # 对于大文件，使用二进制模式和缓冲区读取
                with open(base64_file, 'rb') as f:
                    base64_data = f.read()  # 一次性读取，对于大文件可能需要分块
                
                # 检查文件是否为空
                if not base64_data:
                    self.app.log_message("Base64文件为空")
                    return
                
                # 初步检查base64格式
                try:
                    # 尝试不带验证的解码
                    decoded_data = base64.b64decode(base64_data, validate=False)
                    self.app.log_message("不带验证的Base64解码成功")
                    
                    # 尝试带验证的解码
                    try:
                        decoded_data_validated = base64.b64decode(
                            base64_data, validate=True
                        )
                        self.app.log_message("带验证的Base64解码成功")
                    except binascii.Error as ve:
                        message = f"带验证的Base64解码失败: {str(ve)}，但使用非验证模式继续"
                        self.app.log_message(message)
                    
                    json_str = decoded_data.decode('utf-8')
                    
                    # 优化JSON解析
                    data = json.loads(json_str)
                    self.app.log_message("成功解码Base64并读取JSON数据")
                except Exception as e:
                    self.app.log_message(f"Base64解码或JSON解析失败: {str(e)}")
                    return
            except Exception as e:
                self.app.log_message(f"处理数据时发生未预期错误: {str(e)}")
                return
# 此异常已被上层捕获处理，移除多余的 except 子句
                self.app.log_message(f"数据解析错误: {str(e)}")
                return
            
            # 处理每个index
            all_success = True
            for i, index_val in enumerate(index_list):
                # 如果只有一个sheet且没有指定index与sheet的对应关系，则使用第一个sheet的映射
                if len(sheet_mappings) == 1 and len(index_list) > 1:
                    sheet_name = next(iter(sheet_mappings.keys()))
                    new_mappings = sheet_mappings[sheet_name]
                # 如果index数量与sheet数量相同，则按顺序对应
                elif len(index_list) == len(sheet_mappings):
                    sheet_name = list(sheet_mappings.keys())[i]
                    new_mappings = sheet_mappings[sheet_name]
                    message = f"将工作表 '{sheet_name}' 的映射应用到 index '{index_val}'"
                    self.app.log_message(message)
                # 否则，假设index值就是sheet名称
                else:
                    if index_val in sheet_mappings:
                        new_mappings = sheet_mappings[index_val]
                        self.app.log_message(f"使用工作表 '{index_val}' 的映射")
                    else:
                        message = f"警告: 未找到与index '{index_val}' 对应的工作表，跳过该index"
                        self.app.log_message(message)
                        all_success = False
                        continue
                
                # 添加映射到指定index
                if not self.add_mappings_to_index(data, new_mappings, index_val):
                    all_success = False
            
            if all_success:
                # 优化JSON序列化
                json_str = json.dumps(
                    data, ensure_ascii=False, separators=(',', ':')
                )  # 紧凑格式
                
                # 保存文件的函数
                def save_files():
                    # 获取默认保存路径
                    default_dir = os.path.dirname(base64_file)
                    default_name = f"processed_{os.path.basename(base64_file)}"
                    
                    base64_save_path = filedialog.asksaveasfilename(
                        title="保存Base64文件",
                        defaultextension=".txt",
                        filetypes=[("文本文件", "*.txt"), ("所有文件", "*.*")],
                        initialdir=default_dir,
                        initialfile=default_name
                    )
                    
                    if base64_save_path:
                        try:
                            # 编码并保存Base64文件
                            base64_data = base64.b64encode(
                                json_str.encode('utf-8')
                            ).decode('utf-8')
                            with open(base64_save_path, 'w', encoding='utf-8') as f:
                                f.write(base64_data)
                            filename = os.path.basename(base64_save_path)
                            self.app.log_message(f"Base64文件已保存到: {filename}")
                            
                            # 保存JSON文件（如果需要）
                            if output_json:
                                base_name = os.path.splitext(
                                    base64_save_path
                                )[0]
                                if base_name.endswith("_base64"):
                                    base_name = base_name[:-7]
                                json_save_path = f"{base_name}.json"
                                
                                with open(json_save_path, 'w', encoding='utf-8') as f:
                                    f.write(json_str)
                                filename = os.path.basename(json_save_path)
                                self.app.log_message(f"JSON文件已保存到: {filename}")
                                
                                message = (
                                    f"数据已成功处理并保存到:\n"
                                    f"Base64文件: {base64_save_path}\n"
                                    f"JSON文件: {json_save_path}"
                                )
                                messagebox.showinfo("成功", message)
                            else:
                                message = f"数据已成功处理并保存到:\n{base64_save_path}"
                                messagebox.showinfo("成功", message)
                            
                        except Exception as e:
                            message = f"保存文件时出错: {str(e)}"
                            self.app.log_message(message)
                            messagebox.showerror("错误", message)
                
                # 在主线程中执行文件保存
                self.app.root.after(0, save_files)
            else:
                error_msg = "处理数据时出错，请查看日志获取详细信息"
                self.app.root.after(0, lambda: messagebox.showerror("错误", error_msg))
            
        except Exception as e:
            self.app.log_message(f"处理数据时出错: {str(e)}")
            error_msg = f"处理数据时出错: {str(e)}"
            self.app.root.after(0, lambda: messagebox.showerror("错误", error_msg))
        finally:
            # 确保处理完成后恢复UI状态
            self.app.root.after(0, self.app.finish_processing)
    
    def add_mappings_to_index(self, data, new_mappings, index_val):
        """高效添加映射到指定索引位置"""
        # 构建新映射的字典，key为orgValue，value为完整映射对象
        new_mappings_dict = {mapping['orgValue']: mapping for mapping in new_mappings}
        
        # 预编译正则表达式（如果有）
        regex_mappings = {}
        for org_val, mapping in new_mappings_dict.items():
            if mapping['mappingType'] == 'REGULAR':
                try:
                    regex_mappings[org_val] = re.compile(org_val)
                except re.error:
                    self.app.log_message(f"警告: 正则表达式 '{org_val}' 无效，已跳过")
                    del new_mappings_dict[org_val]
        
        # 遍历规则查找指定index
        for rule in data:
            normalize_items = rule.get('normalize', [])
            for norm_item in normalize_items:
                if norm_item.get('index') == index_val:
                    # 确保mappings字段存在
                    mappings = norm_item.setdefault('mappings', [])
                    
                    # 构建现有值的集合用于快速查找
                    existing_org_values = {m['orgValue'] for m in mappings}
                    # 构建现有映射的字典以便更新
                    existing_map_by_org = {}
                    for idx, m in enumerate(mappings):
                        existing_map_by_org[m['orgValue']] = idx
                    
                    # 计算需要添加或更新的映射
                    mappings_to_add = []
                    updated_count = 0
                    for org_val, m in new_mappings_dict.items():
                        if org_val not in existing_org_values:
                            mappings_to_add.append(m)
                        else:
                            # 如果已存在同orgValue，但mappingValue不同，则更新为标准化值
                            existing_idx = existing_map_by_org.get(org_val)
                            if existing_idx is not None:
                                existing_mv = mappings[existing_idx].get('mappingValue', '')
                                new_mv = m.get('mappingValue', '')
                                if new_mv and existing_mv != new_mv:
                                    mappings[existing_idx]['mappingValue'] = new_mv
                                    updated_count += 1
                    
                    if mappings_to_add:
                        mappings.extend(mappings_to_add)
                        self.app.log_message(f"成功添加 {len(mappings_to_add)} 个新映射到 {index_val}")
                    if updated_count > 0:
                        self.app.log_message(f"已更新 {updated_count} 个已有映射的映射值为标准化结果")
                    if not mappings_to_add and updated_count == 0:
                        self.app.log_message(f"没有新的或需要更新的映射添加到 {index_val}")
                        
                    return True
        
        self.app.log_message(f"错误: 未找到index为 '{index_val}' 的字段")
        return False
    
    def clear_cache(self):
        """清除Excel文件缓存"""
        self._excel_cache.clear()
        self.app.log_message("Excel文件缓存已清除")
    
    def process_csv_batch(self, input_path, output_folder, progress_callback=None):
        """批量处理CSV文件转换，自动判断输入是文件还是文件夹
        
        Args:
            input_path: 输入文件或文件夹路径
            output_folder: 输出文件夹路径
            progress_callback: 进度回调函数，接收(current, total, success, fail, message)参数
            
        Returns:
            处理结果字典
        """
        try:
            # 创建输出文件夹
            os.makedirs(output_folder, exist_ok=True)
            
            # 判断输入是文件还是文件夹
            if os.path.isfile(input_path):
                # 单文件处理
                if not input_path.lower().endswith(('.csv', '.xlsx', '.xls')):
                    if progress_callback:
                        progress_callback(0, 0, 0, 0, "不支持的文件格式")
                    return {"success": False, "message": "不支持的文件格式"}
                
                csv_files = [(input_path, os.path.basename(input_path))]
            elif os.path.isdir(input_path):
                # 文件夹批量处理
                csv_files = self._collect_csv_files(input_path)
            else:
                if progress_callback:
                    progress_callback(0, 0, 0, 0, "输入路径不存在")
                return {"success": False, "message": "输入路径不存在"}
            
            if not csv_files:
                if progress_callback:
                    progress_callback(0, 0, 0, 0, "未找到任何CSV或Excel文件")
                return {"success": False, "message": "未找到任何CSV或Excel文件"}
            
            total_files = len(csv_files)
            if progress_callback:
                message = f"找到 {total_files} 个文件，开始处理..."
                progress_callback(0, total_files, 0, 0, message)
            
            # 初始化处理状态
            success_count = 0
            fail_count = 0
            failed_files = []
            start_time = time.time()
            
            # 处理每个文件
            for i, (file_path, rel_path) in enumerate(csv_files):
                try:
                    # 生成输出文件路径
                    base_rel_path, ext = os.path.splitext(rel_path)
                    output_rel_path = base_rel_path + ".txt"
                    output_path = os.path.join(output_folder, output_rel_path)
                    
                    # 确保输出子文件夹存在
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    
                    # 处理文件
                    record_count = self._convert_single_file(file_path, output_path, ext)
                    
                    success_count += 1
                    if progress_callback:
                        message = f"✓ 转换成功: {output_rel_path} ({record_count} 条记录)"
                        progress_callback(i + 1, total_files, success_count, 
                                        fail_count, message)
                    
                except Exception as e:
                    fail_count += 1
                    failed_files.append((rel_path, str(e)))
                    if progress_callback:
                        message = f"✗ 转换失败: {rel_path} - {str(e)}"
                        progress_callback(i + 1, total_files, success_count, 
                                        fail_count, message)
            
            # 生成汇总报告
            report_data = self._generate_batch_report(
                input_path, output_folder, total_files,
                success_count, fail_count, failed_files, start_time
            )
            
            return {
                "success": True,
                "total_files": total_files,
                "success_count": success_count,
                "fail_count": fail_count,
                "failed_files": failed_files,
                "report_data": report_data
            }
            
        except Exception as e:
            if progress_callback:
                message = f"批量处理过程中发生错误: {str(e)}"
                progress_callback(0, 0, 0, 0, message)
            return {"success": False, "message": str(e)}
    
    def _collect_csv_files(self, folder_path):
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
            self.app.log_message(f"收集文件时出错: {str(e)}")
        
        return csv_files
    
    def _detect_file_encoding(self, file_path):
        """检测文件编码"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(20000)  # 读取更多字节提高检测准确性
                result = chardet.detect(raw_data)
                detected_encoding = result['encoding']
                confidence = result['confidence']
                
                # 对于中文编码，如果置信度较低，优先尝试中文编码
                if confidence > 0.7:
                    return detected_encoding
                elif 'gb' in detected_encoding.lower() or 'gbk' in detected_encoding.lower():
                    # 如果是GB系列编码但置信度不高，优先尝试GB18030（最全的中文编码）
                    return 'gb18030'
        except Exception:
            pass
        
        # 回退到基础检测，优先尝试中文编码
        encodings = ['gb18030', 'gbk', 'gb2312', 'utf-8', 'latin1', 'cp1252']
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1024)
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        return 'utf-8'
    
    def _convert_single_file(self, input_path, output_path, ext):
        """转换单个文件"""
        # 根据文件类型选择读取方式
        if ext.lower() in ('.xlsx', '.xls'):
            # Excel文件处理
            df = pd.read_excel(input_path)
        else:
            # CSV文件处理
            encoding = self._detect_file_encoding(input_path)
            df = pd.read_csv(input_path, encoding=encoding)
        
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
        
        # 写入文件，使用utf-8-sig编码确保Excel打开不乱码
        with open(output_path, 'w', encoding='utf-8-sig') as f:
            for json_line in json_lines:
                f.write(json_line + '\n')
        
        return len(json_lines)
    
    def _generate_batch_report(self, input_folder, output_folder, total_files,
                              success_count, fail_count, failed_files, start_time):
        """生成批量处理报告"""
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
            with open(report_json_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            
            # 保存CSV格式报告
            report_csv_path = os.path.join(output_folder, "conversion_report.csv")
            with open(report_csv_path, 'w', encoding='utf-8') as f:
                f.write("项目,值\n")
                for key, value in report["summary"].items():
                    f.write(f"{key},{value}\n")
                f.write("\n失败文件列表:\n")
                f.write("文件路径,错误信息\n")
                for file_path, error in failed_files:
                    f.write(f"{file_path},{error}\n")
            
            self.app.log_message(f"汇总报告已保存:")
            self.app.log_message(f"  JSON格式: {os.path.basename(report_json_path)}")
            self.app.log_message(f"  CSV格式: {os.path.basename(report_csv_path)}")
            
            return report
            
        except Exception as e:
            self.app.log_message(f"生成汇总报告时出错: {str(e)}")
            return None

    def _decode_base64_file_chunked(self, base64_file, chunk_size=1024*1024):
        """分块读取并解码Base64文件（用于大文件处理）
        
        Args:
            base64_file: Base64文件路径
            chunk_size: 分块大小（默认1MB）
            
        Returns:
            解码后的数据，失败返回None
        """
        try:
            file_size = os.path.getsize(base64_file)
            file_size_mb = file_size / (1024 * 1024)
            self.app.log_message(f"Base64文件大小: {file_size_mb:.2f} MB")
            
            # 大文件警告
            if file_size_mb > 50:
                self.app.log_message("警告: 文件较大（>50MB），处理可能需要较长时间")
            
            # 分块读取
            chunks = []
            processed_size = 0
            
            with open(base64_file, 'rb') as f:
                while True:
                    chunk = f.read(chunk_size)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    processed_size += len(chunk)
                    
                    # 进度反馈（每10%报告一次）
                    if file_size > 0:
                        progress = (processed_size / file_size) * 100
                        if int(progress) % 10 == 0 and processed_size == len(chunks[-1]):
                            self.app.log_message(f"读取进度: {progress:.1f}%")
            
            # 合并所有分块
            base64_data = b''.join(chunks)
            
            # 检查文件是否为空
            if not base64_data:
                self.app.log_message("Base64文件为空")
                return None
            
            # 解码Base64
            try:
                decoded_data = base64.b64decode(base64_data, validate=False)
                self.app.log_message("不带验证的Base64解码成功")
                
                # 尝试带验证的解码
                try:
                    decoded_data_validated = base64.b64decode(base64_data, validate=True)
                    self.app.log_message("带验证的Base64解码成功")
                except binascii.Error as ve:
                    self.app.log_message(f"带验证的Base64解码失败: {str(ve)}，但使用非验证模式继续")
                
                json_str = decoded_data.decode('utf-8')
                data = json.loads(json_str)
                self.app.log_message("成功解码Base64并读取JSON数据")
                return data
            except Exception as e:
                self.app.log_message(f"Base64解码或JSON解析失败: {str(e)}")
                return None
                
        except Exception as e:
            self.app.log_message(f"处理Base64文件时出错: {str(e)}")
            return None
