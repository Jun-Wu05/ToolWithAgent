# RAG 系统设计

## 流水线


文档 
↓ 
分块 
↓ 
向量化 
↓ 
VectorStoreIndex 
↓ 
检索器 
↓ 
查询引擎 
↓ 
LLM 回答 

分块策略
推荐分块大小： 
500 tokens 
重叠：50 tokens 
检索策略
Top K： 
默认值：3 
最大值：5 
提示词模板
上下文 + 问题 → 回答 
示例： 
上下文： 
{retrieved_chunks} 
问题： 
{user_question} 
请清晰简洁地回答。 

---
