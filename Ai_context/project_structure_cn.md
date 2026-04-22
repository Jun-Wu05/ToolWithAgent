# 项目结构


ai_app/ 
│ 
├ app/ 
│   ├ agent/ 
│   │   └ agent.py 
│   │ 
│   ├ rag/ 
│   │   ├ index_builder.py 
│   │   ├ retriever.py 
│   │   └ query_engine.py 
│   │ 
│   ├ tools/ 
│   │   ├ rag_tool.py 
│   │   ├ sql_tool.py 
│   │   └ web_tool.py 
│   │ 
│   ├ config/ 
│   │   └ settings.py 
│   │ 
│   └ main.py 
│ 
├ data/ 
│   ├ documents/ 
│   └ database/ 
│ 
├ storage/ 
│ 
└ ai_context/ 

原则
Agent 不应直接访问数据。 
所有数据访问必须通过工具进行。 
RAG 逻辑应与 Agent 逻辑分离。 
工具作为能力接口。 

---
