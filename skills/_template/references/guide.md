# 模板参考文档

## 目录说明

本目录存放技能的补充参考资料，Agent 在需要时通过 `get_skill_reference()` 按需加载。

## 何时使用参考资料
- SKILL.md 正文中引用了具体的数据结构或格式规范
- Agent 需要查阅示例 JSON 来确保输出格式正确
- 有额外的背景知识或边界情况说明

## 文件组织建议

```
references/
  data_structure.md    - 数据结构和字段说明
  examples.md          - 完整的输入输出示例
  api_reference.md     - 外部 API 或依赖说明
```
