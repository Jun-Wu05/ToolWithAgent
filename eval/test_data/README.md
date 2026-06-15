# 标准字段测试数据

本目录包含从base64编码的测试数据文件中提取的标准字段测试数据，用于准确率测试。

## 📁 文件说明

- `test_data_summary.json` - 批量提取的汇总统计信息
- `*_test_data.json` - 各设备类型的测试数据文件

## 📊 测试数据统计

### 提取结果汇总

| 设备类型 | 样本数量 | 字段总数 | 唯一字段数 | 源文件 |
|---------|---------|---------|-----------|--------|
| 防火墙 | 56 | 900 | 270 | 防火墙待提取数据.txt |
| NDR待 | 100 | 2,979 | 977 | NDR待测试数据.txt |
| NDR待2 | 29 | 718 | 288 | NDR待测试数据2.txt |
| IPS | 43 | 855 | 251 | IPS待提取数据.txt |
| waf | 43 | 801 | 373 | waf待提取数据.txt |
| EDR待 | 27 | 567 | 115 | EDR待测试数据.txt |
| 抗ddos | 12 | 162 | 72 | 抗ddos待提取数据.txt |
| **总计** | **310** | **6,982** | **2,346** | - |

## 🔄 数据提取

### 自动提取

使用批量处理脚本自动提取测试数据：

```bash
python eval/scripts/prepare_test_data.py --default
```

### 手动提取

指定源目录和输出目录：

```bash
python eval/scripts/prepare_test_data.py --source <源目录> --output <输出目录>
```

## 📝 数据格式

### 测试数据文件结构

```json
{
  "test_set_name": "防火墙待提取数据",
  "device_type": "防火墙",
  "source_file": "源文件路径",
  "samples": [
    {
      "sample_id": 1,
      "original_log": "原始日志内容...",
      "fields": [
        {
          "index": "字段索引",
          "field": "映射字段名",
          "entity": "实体类型",
          "result": ["字段值1", "字段值2"],
          "core": true,
          "sim": true
        }
      ]
    }
  ],
  "statistics": {
    "total_samples": 56,
    "total_fields": 900,
    "unique_fields": 270
  }
}
```

### 字段过滤规则

1. **空字段过滤**：移除 `field` 为 `null` 或空字符串的记录
2. **索引去重**：当 `index` 相同时，保留第一个出现的记录

## 🛠️ 工具说明

### TestExtractor

测试数据提取器类，负责从base64编码的文件中提取测试数据。

**主要功能**：
- base64解码
- JSON解析
- 字段过滤和去重
- 统计信息生成

**使用示例**：

```python
from eval.tools.test_data_extractor import TestExtractor

# 创建提取器
extractor = TestExtractor("path/to/base64_file.txt")

# 提取数据
data = extractor.extract()

# 保存为JSON
extractor.save_to_json("output_path.json")
```

### 批量提取

批量处理函数，用于一次性提取多个测试数据文件。

**使用示例**：

```python
from eval.tools.test_data_extractor import batch_extract_test_data

# 批量提取
summary = batch_extract_test_data(
    source_dir="archive/测试数据/标准字段测试数据/data",
    output_dir="eval/test_data"
)

# 查看汇总信息
print(f"总样本数: {summary['statistics']['total_samples']}")
print(f"总字段数: {summary['statistics']['total_fields']}")
```

## 📈 准确率测试

使用提取的测试数据进行标准字段映射准确率测试。

### 测试流程

1. 加载测试数据
2. 对每个样本执行标准字段映射
3. 比对映射结果与预期结果
4. 计算准确率指标

### 关键指标

- **映射准确率**：正确映射的字段数 / 总字段数
- **字段召回率**：成功提取的字段数 / 预期字段数
- **整体准确率**：所有样本的准确率平均值

## 🔍 数据验证

在准确率测试前，建议验证测试数据质量：

1. 检查字段去重是否正确
2. 验证空字段过滤是否生效
3. 确认样本数量和字段数量统计准确

## 📞 相关文档

- [标准字段定义](../../config/标准字段.txt)
- [字段映射工具](../../agent/tools/standard_mapper.py)
- [准确率测试脚本](../test_llm_accuracy.py)

## 📅 更新记录

- **2026-06-15**: 初始版本，从7个设备类型的测试数据中提取310个样本