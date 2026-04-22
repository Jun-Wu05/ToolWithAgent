# AI 应用架构

## 核心流水线

文档 → 索引 → 检索器 → 查询引擎 → 工具 → Agent → 用户

---

## 系统架构


                     用户 
                       │ 
                       ▼ 
                    Agent 
                       │ 
              ┌────────┼────────┐ 
              ▼        ▼        ▼ 
            RAG      SQL      API 
              │        │        │ 
              ▼        ▼        ▼ 
        VectorIndex   DB      外部服务 
              │ 
              ▼ 
          文档 

组件
文档
原始数据源： 
PDF 
TXT 
Markdown 
CSV 
网页 
索引
负责将文档转换为可搜索的结构。 
示例： 
VectorStoreIndex 
SQLIndex 
检索器
负责检索最相关的节点。 
流程： 
查询 → 向量化 → 相似度搜索 → Top K 结果 
查询引擎
组合： 
检索器 + LLM 
以生成最终响应。 
工具
工具是一个封装，允许 Agent 访问各种能力。 
示例： 
rag_tool 
sql_tool 
web_tool 
Agent
Agent 负责： 
推理 
选择工具 
执行任务 

---
