---
name: _template
description: 技能模板 - 复制此目录并重命名为你的技能名称，然后修改本文件
license: MIT
metadata:
  version: "1.0.0"
  author: your-name
  tags: ["template"]
---

# 技能名称

## 何时使用
描述触发此技能的具体场景和关键词。RouterAgent 根据此描述决定何时调用。
例如：
- 用户说"XX"、"YY"时
- 用户需要做某类特定操作时

## 前置条件
执行此技能前必须满足的条件：
- 条件 1（如：用户已上传 Base64 配置文件）
- 条件 2（如：session 中存在 decoded_data）

## 操作步骤

### Step 1: 获取数据
说明如何获取输入数据（从 session、用户输入等）

### Step 2: 执行操作
说明具体的处理逻辑，引用 `scripts/` 中的函数

### Step 3: 输出结果
说明输出格式和后续处理

## 输出格式
```json
{
  "field1": "说明",
  "field2": "说明"
}
```

## 约束与边界
- 错误情况 1：如何处理
- 错误情况 2：如何处理
- 限制说明

## 完整示例

### 输入
```
用户输入示例
```

### 中间处理
```
调用 scripts/example.py 的处理过程
```

### 输出
```json
{
  "result": "最终输出示例"
}
```
