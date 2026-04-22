# 数据映射解析工具

基于Python tkinter开发的图形化数据映射解析工具，用于安全设备配置规则的字段映射和编码转换。

## 功能特性

### 功能1：字段枚举批量处理
- 上传Base64编码的原始规则文件
- 上传Excel格式的字段映射模板
- 解析JSON配置并提取simEntities数组
- 根据索引路径定位并修改字段值
- 输出修改后的配置（支持JSON格式）
- 下载映射模板文件

### 功能2：Base64错误检测
- 批量检测指定目录下所有JSON文件中的Base64编码错误
- 扫描文件内容中的潜在Base64格式问题
- 输出处理结果到指定文件
- 支持多线程快速扫描

### 功能3：CSV格式转换
- CSV文件上传和预览
- CSV数据分析和统计
- CSV数据导出功能

### 功能4：标准字段映射
- 上传原始解析规则文件（Base64编码的JSON配置）
- 上传标准字段映射表Excel文件
- 自动读取"对应关系"表建立字段与对象的映射
- 智能处理多对象情况（默认取第一个）
- 自动将新实体添加到simEntities数组
- 保存修改后的解析规则

### 功能5：字段映射集合
融合功能1（带枚举的字段映射）和功能4（标准字段映射）的综合功能：
1. 上传原始Base64编码的解析规则
2. 上传包含多个Sheet的字段映射模板（Sheet名称=原始字段名）
3. 可选：配置字段映射（原始字段名→标准字段名）
   - 提供常用字段名快捷按钮（源地址、目标地址、威胁名称、威胁类型、用户名）
   - 支持重复字段名检测和警告
4. 遍历每个Sheet进行映射处理：
   - 若Sheet名称是系统属性名，先获取实体（功能4），再添加枚举映射（功能1）
   - 若Sheet名称非系统属性名，仅添加枚举映射（功能1）
   - REGULAR类型映射自动在原始值前后添加.*前缀和后缀
   - threat_type字段自动使用threat_type_config.json中的标准威胁名称
5. 自动管理simEntities数组中的实体
6. 保存修改后的规则

输入格式：
- 原始规则：Base64编码的JSON文件
- 映射模板：Excel文件，含多个Sheet
  - Sheet名称 = 原始字段名（来自JSON索引数组）
  - 列结构：mappingType, orgValue, mappingValue

输出：
- 修改后的Base64编码JSON文件
- 自动向simEntities数组中添加实体（如果不存在）

## 项目结构

```
tools/
├── main.py                              # 主程序入口，GUI主窗口
├── gui_handler.py                       # GUI界面处理模块，协调各功能模块
├── field_mapping_handler.py             # 功能1：字段枚举批量处理模块
├── base64_error_handler.py              # 功能2：Base64错误检测模块
├── feature3_handler.py                  # 功能3：CSV格式转换模块
├── standard_field_mapping_handler.py    # 功能4：标准字段映射处理模块
├── feature5_mappingall.py               # 功能5：字段映射集合模块
├── threat_type_manager.py               # 威胁类型管理工具
├── threat_type_config.json              # 威胁类型配置文件
├── 对象.xlsx                            # 系统属性映射模板
└── readme.md                            # 项目说明文档
```

## 快速开始

### 环境要求
- Python 3.6+
- Windows操作系统

### 安装依赖
```bash
pip install openpyxl pandas
```

### 运行程序
```bash
python main.py
```

## 使用说明

### 功能1
1. 选择Base64编码文件
2. 选择Excel映射模板文件
3. 输入与Excel sheet名称对应的字段名
4. 点击"处理数据"按钮

### 功能2
1. 选择需要扫描的目录
2. 选择输出结果文件路径
3. 点击"开始检测"按钮

### 功能4
1. 上传原始解析规则文件（Base64编码的JSON配置）
2. 上传标准字段映射表Excel文件
3. 系统自动从"对应关系"Sheet读取映射关系
4. 点击"应用映射规则"执行字段映射
5. 点击"保存解析规则"导出处理结果

### 功能5
1. 上传原始解析规则文件（Base64编码的JSON配置）
2. 上传映射模板Excel文件（多个Sheet，Sheet名为原始字段名）
3. 可选：配置字段映射（原始字段名→标准字段名）
   - 手动输入原始字段名和标准字段名
   - 或点击右侧常用字段名快捷按钮快速填充
   - 系统会自动检测重复字段名并警告
4. 点击"处理映射"按钮执行处理
   - REGULAR类型映射自动添加.*前缀和后缀
   - threat_type字段自动标准化为威胁类型配置中的标准名称
5. 点击"保存结果"按钮导出结果

## 映射规则格式

### 功能1Excel映射模板
- Sheet名称：对应原始字段名
- 列结构：原始值 → 目标值

### 功能4标准字段映射表
- Sheet名称："对应关系"
- 列结构：系统属性名称 | 字段名称 | 对象
- 支持多对象映射（逗号分隔），默认取第一个对象

### 功能5映射模板
- Sheet名称 = 原始字段名
- 列结构：mappingType | orgValue | mappingValue
- mappingType类型说明：
  - replace：精确匹配替换
  - add：精确匹配添加
  - REGULAR：正则表达式匹配（自动添加.*前缀和后缀）

### 威胁类型标准化
功能5在处理threat_type字段时，会自动将映射后的值与threat_type_config.json中的模式进行匹配，使用对应的标准威胁名称进行标准化。

## 依赖库

- tkinter：GUI界面（Python标准库）
- openpyxl：Excel文件读写
- pandas：CSV数据处理
- Python标准库：os, threading, base64, binascii, json, re

## 注意事项

1. Base64编码文件应为纯文本格式的JSON配置
2. Excel映射文件应包含正确的Sheet结构
3. 标准字段映射表的"对应关系"Sheet需按格式要求创建
4. 建议定期备份原始配置文件
5. 功能5的常用字段名快捷按钮可快速填充标准字段名
6. threat_type_config.json用于威胁类型的标准化配置
