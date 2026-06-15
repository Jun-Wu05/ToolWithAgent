"""
测试数据提取工具

从base64编码的JSON数据中提取标准字段测试数据
"""
import base64
import json
import os
from typing import Dict, List, Any, Optional
from pathlib import Path


class TestExtractor:
    """测试数据提取器"""
    
    def __init__(self, base64_file_path: str):
        """
        初始化提取器
        
        Args:
            base64_file_path: base64编码的测试数据文件路径
        """
        self.base64_file_path = base64_file_path
        self.file_name = os.path.basename(base64_file_path)
        self.device_type = self._extract_device_type(self.file_name)
        
    def _extract_device_type(self, file_name: str) -> str:
        """
        从文件名提取设备类型
        
        Args:
            file_name: 文件名
            
        Returns:
            设备类型（如"防火墙"、"WAF"等）
        """
        # 移除文件扩展名和"待提取数据"等后缀
        name = file_name.replace(".txt", "").replace(".json", "")
        name = name.replace("待提取数据", "").replace("测试数据", "").strip()
        return name if name else "未知设备"
    
    def _decode_base64_to_json(self) -> Dict:
        """
        将base64文件解码为JSON
        
        Returns:
            解码后的JSON数据
            
        Raises:
            FileNotFoundError: 文件不存在
            ValueError: base64解码失败或JSON解析失败
        """
        if not os.path.exists(self.base64_file_path):
            raise FileNotFoundError(f"文件不存在: {self.base64_file_path}")
        
        try:
            with open(self.base64_file_path, 'r', encoding='utf-8') as f:
                # 读取所有行并拼接（base64可能分行存储）
                base64_content = f.read().strip().replace('\n', '').replace('\r', '')
            
            # base64解码
            decoded_bytes = base64.b64decode(base64_content)
            decoded_str = decoded_bytes.decode('utf-8')
            
            # 解析JSON
            json_data = json.loads(decoded_str)
            return json_data
            
        except Exception as e:
            raise ValueError(f"base64解码或JSON解析失败: {str(e)}")
    
    def _filter_fields(self, normalize_list: List[Dict], seen_indexes: set) -> List[Dict]:
        """
        过滤和去重字段
        
        规则（按优先级排序）：
        1. 删除index包含"field"的字段（如field0, field1等）
        2. 过滤掉field为null或空的记录
        3. 保护field="key_keeper"或field="original_log"的字段
        4. 对index进行去重，保留第一个出现的记录（全局去重）
        
        Args:
            normalize_list: normalize数组
            seen_indexes: 已见过的index集合（用于全局去重）
            
        Returns:
            过滤后的字段列表
        """
        if not isinstance(normalize_list, list):
            return []
        
        filtered_fields = []
        
        for item in normalize_list:
            if not isinstance(item, dict):
                continue
            
            field_value = item.get('field')
            index_value = item.get('index', '')
            
            # 规则1：删除index包含"field"的字段
            if "field" in str(index_value):
                continue
            
            # 规则2：过滤掉field为null或空的记录
            if field_value is None or str(field_value).strip() == '':
                continue
            
            # 规则3：保护特殊字段
            if field_value == "key_keeper" or field_value == "original_log":
                filtered_fields.append(item)
                continue
            
            # 规则4：index去重，保留第一个（全局去重）
            if index_value in seen_indexes:
                continue
            
            seen_indexes.add(index_value)
            filtered_fields.append(item)
        
        return filtered_fields
    
    def _extract_single_sample(self, parser_config: Dict, sample_id: int, seen_indexes: set) -> Optional[Dict]:
        """
        提取单个样本
        
        Args:
            parser_config: 解析器配置
            sample_id: 样本ID
            seen_indexes: 已见过的index集合（用于全局去重）
            
        Returns:
            样本数据字典，如果提取失败返回None
        """
        try:
            # 提取sample字段
            sample = parser_config.get('sample', '')
            if not sample:
                return None
            
            # 提取normalize数组
            normalize_list = parser_config.get('normalize', [])
            filtered_fields = self._filter_fields(normalize_list, seen_indexes)
            
            if not filtered_fields:
                return None
            
            return {
                'sample_id': sample_id,
                'original_log': sample,
                'fields': filtered_fields
            }
            
        except Exception:
            return None
    
    def extract(self) -> Dict:
        """
        提取测试数据
        
        Returns:
            标准化的测试数据字典
            
        Raises:
            Exception: 提取过程中出现错误
        """
        try:
            # 解码base64文件
            json_data = self._decode_base64_to_json()
            
            # 检查是否为列表格式（多个解析器配置）
            if isinstance(json_data, list):
                parser_configs = json_data
            elif isinstance(json_data, dict) and 'data' in json_data:
                parser_configs = json_data['data']
            else:
                parser_configs = [json_data]
            
            # 全局去重集合：在所有样本之间共享
            seen_indexes = set()
            
            # 提取每个样本
            samples = []
            total_fields = 0
            unique_fields = set()
            
            for idx, config in enumerate(parser_configs, 1):
                # 传递全局的seen_indexes集合
                sample_data = self._extract_single_sample(config, idx, seen_indexes)
                if sample_data:
                    samples.append(sample_data)
                    total_fields += len(sample_data['fields'])
                    
                    # 统计唯一的index
                    for field in sample_data['fields']:
                        unique_fields.add(field.get('index', ''))
            
            # 构建结果
            result = {
                'test_set_name': self.file_name.replace('.txt', '').replace('.json', ''),
                'device_type': self.device_type,
                'source_file': self.base64_file_path,
                'samples': samples,
                'statistics': {
                    'total_samples': len(samples),
                    'total_fields': total_fields,
                    'unique_fields': len(unique_fields)
                }
            }
            
            return result
            
        except Exception as e:
            raise Exception(f"测试数据提取失败: {str(e)}")
    
    def save_to_json(self, output_path: Optional[str] = None) -> str:
        """
        提取并保存为JSON文件
        
        Args:
            output_path: 输出文件路径，如果为None则自动生成
            
        Returns:
            保存的文件路径
        """
        # 提取数据
        data = self.extract()
        
        # 确定输出路径
        if output_path is None:
            # 使用设备类型作为文件名
            safe_device_name = self.device_type.replace('/', '-').replace('\\', '-')
            output_path = f"eval/test_data/{safe_device_name}_test_data.json"
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_path)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)
        
        # 保存JSON文件
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 测试数据已保存到: {output_path}")
        print(f"  - 设备类型: {data['device_type']}")
        print(f"  - 样本数量: {data['statistics']['total_samples']}")
        print(f"  - 字段总数: {data['statistics']['total_fields']}")
        print(f"  - 唯一字段数: {data['statistics']['unique_fields']}")
        
        return output_path


def extract_test_data_from_file(
    base64_file_path: str,
    output_path: Optional[str] = None
) -> Dict:
    """
    从base64文件提取测试数据的便捷函数
    
    Args:
        base64_file_path: base64编码的测试数据文件路径
        output_path: 输出文件路径，如果为None则自动生成
        
    Returns:
        提取的测试数据字典
        
    Raises:
        Exception: 提取过程中出现错误
    """
    extractor = TestExtractor(base64_file_path)
    if output_path:
        extractor.save_to_json(output_path)
    else:
        extractor.save_to_json()
    return extractor.extract()


# CHANGED: 添加批量处理函数
def batch_extract_test_data(
    source_dir: str,
    output_dir: str = "eval/test_data"
) -> Dict:
    """
    批量提取测试数据
    
    Args:
        source_dir: 源目录路径（包含base64文件）
        output_dir: 输出目录路径
        
    Returns:
        批量处理结果的汇总信息
    """
    summary = {
        'processed_files': [],
        'statistics': {
            'total_files': 0,
            'successful': 0,
            'failed': 0,
            'total_samples': 0,
            'total_fields': 0
        },
        'summary_file': ''
    }
    
    if not os.path.exists(source_dir):
        raise FileNotFoundError(f"源目录不存在: {source_dir}")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    # 遍历目录中的文件
    for file_name in os.listdir(source_dir):
        file_path = os.path.join(source_dir, file_name)
        
        # 跳过目录和非文本文件
        if not os.path.isfile(file_path):
            continue
        if not (file_name.endswith('.txt') or file_name.endswith('.json')):
            continue
        
        summary['statistics']['total_files'] += 1
        
        try:
            # 提取数据
            extractor = TestExtractor(file_path)
            data = extractor.extract()
            
            # 生成输出文件名
            safe_device_name = data['device_type'].replace('/', '-').replace('\\', '-')
            output_path = os.path.join(output_dir, f"{safe_device_name}_test_data.json")
            
            # 保存文件
            extractor.save_to_json(output_path)
            
            # 更新统计信息
            summary['statistics']['successful'] += 1
            summary['statistics']['total_samples'] += data['statistics']['total_samples']
            summary['statistics']['total_fields'] += data['statistics']['total_fields']
            
            summary['processed_files'].append({
                'source_file': file_name,
                'output_file': os.path.basename(output_path),
                'status': 'success',
                'device_type': data['device_type'],
                'samples': data['statistics']['total_samples'],
                'fields': data['statistics']['total_fields']
            })
            
        except Exception as e:
            summary['statistics']['failed'] += 1
            summary['processed_files'].append({
                'source_file': file_name,
                'status': 'failed',
                'error': str(e)
            })
            print(f"✗ 处理失败: {file_name}, 错误: {str(e)}")
    
    # 保存汇总信息
    summary_path = os.path.join(output_dir, 'test_data_summary.json')
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    summary['summary_file'] = summary_path
    
    print(f"\n{'='*60}")
    print(f"批量处理完成！")
    print(f"  - 总文件数: {summary['statistics']['total_files']}")
    print(f"  - 成功: {summary['statistics']['successful']}")
    print(f"  - 失败: {summary['statistics']['failed']}")
    print(f"  - 总样本数: {summary['statistics']['total_samples']}")
    print(f"  - 总字段数: {summary['statistics']['total_fields']}")
    print(f"  - 汇总文件: {summary_path}")
    print(f"{'='*60}")
    
    return summary


if __name__ == "__main__":
    # 测试代码
    print("测试数据提取工具 - 独立运行模式")
    print("使用示例:")
    print("  python eval/tools/test_data_extractor.py <base64_file_path>")