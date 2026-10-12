# Issue #266 V2 字段映射主路径 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 V2 中复用 Application 生成字段映射，持久发布完整结果，提供对话摘要、原位放大和兼容下载。

**Architecture:** 从 master 创建隔离分支后 fast-forward 到已验证但未合并的 #275 HEAD d1bcfe24fc8843144c7d5887af80ca85bb2f778c。所有业务继续经 Application 确定性计划和默认 Adapter；V2 仅冻结输入、排队、发布、权限及安全展示。PR 基于 #300 分支保持 draft，#60 与现有人工门禁未解除。用户于2026-10-10明确暂缓测试并要求继续开发，允许在未合并依赖上继续开发，不代表允许合并或宣称验收完成。

**Tech Stack:** Python/FastAPI/SQLite、既有 Application/FieldMappingAdapter、React/TypeScript、pytest/Vitest。

## 边界与领取复核

- #262/#263/#264/#265 已落地；#275 自动验证和Review完成，人工未完成，不改变ready-for-human依赖状态。
- 对齐 #266、产品规格 §3/4/6/7、技术规格 §5.2/7/11、DESIGN §5/6、ADR0009/0010/0013。保留App Shell、Composer和单实例抽屉。
- 本轮只交付自动生成结果和只读放大；生成的成功完整结果是正式Artifact。编辑Draft、替换确认、跨规则联动、apply/undo及草稿阻断属#267/#268，不设置无实现的编辑/应用按钮。#276自然语言跨轮及独立导出业务后置；#266的映射下载复用已有产物内容和命名。
- 日志输入可直接映射（内部先复用日志解析），或选取当前成功分类结果继续映射。必须显式产品/厂商，数据源留空按RuleSourceFields现有逻辑补全。无效文件、过期分类及跨会话输入拒绝。
- Run冻结file/classification/source-fields，取消和新有效主数据/新分类后不得迟到发布，失败保留旧Artifact；正常未匹配允许成功。业务原值仅进入受保护Blob与本人主动打开的结果视图，不进入摘要、SSE和普通诊断。

## 任务1 基线与环境

独立worktree复制.env与三份标准字段缓存（不输出内容）。显式Python全量pytest通过后才实施；树内TEMP、basetemp、cache_dir。V2复用已有隔离依赖，不升级共享环境；前端按lockfile安装。

## 任务2 后端（Builder）

Files: v2/backend/toolwithagent_v2/runtime/business_application.py、runtime/worker.py、infrastructure/store.py、api/app.py；可新增单一mapping_projection.py和测试test_field_mapping_slice.py。公开样例读取接缝复用Application/standard_enum_mapping，保持原画像扫描与10值上限；样例line_number为原始日志条目序号，配置降级样例没有行号。

1. 写入队/成功发布/失败保留/取消与过期/归属/幂等测试，确认旧入口红。
2. 加明确字段映射命令。冻结显式输入，复用现有_Run/fence/Blob事务，不创建第二队列。
3. BusinessApplication经现有FieldMappingStep与生产组合运行；创建现有专业Agent registry，禁止复制批处理、事件标注或威胁续跑。测试在可控专业Agent/Adapter接缝覆盖实际公共桥接，避免只测fake应用。
4. 将完整配置/映射结果/下载内容存Blob；metadata只放计数、rule标签与来源身份。按当前有效数据与分类校验发布事务。
5. 本人结果读取支持子规则、每页50行、整个选定子规则搜索（不限当前页）/状态筛选、原字段/样例/标准字段/匹配证据/状态。下载由现有内容和命名逻辑产生；必要时将web现有纯命名函数原样移到Application公共函数，Web也使用同一函数，禁止跨包私有导入。
6. 定向V2测试绿，给Lead报告API契约后进入前端。

## 任务3 前端（Builder）

Files: v2/frontend/src/App.tsx、api.ts、styles.css；新增MappingWorkspace.tsx和相应组件测试。

在现有布局和CSS tokens上：文件/当前分类结果有“标准字段映射”入口；就地表单收集产品/厂商/可选数据源；提交后显示运行状态；对话摘要卡显示计数、“查看结果”和下载。点击查看只替换中间消息区，左栏/Composer/右抽屉保留；子规则Tabs、只读表格、搜索、分组、分页、空态/错误/Loading。返回按钮恢复原结果卡位置。切换会话/身份与迟到请求不得串数据。Developer/Admin不得出现写入口。

## 任务4 Tester → Reviewer

先定向与全量根仓pytest；V2后端全量、前端test/lint/build；生产Python修改重新生成scripts/generate_source_code_analysis.py（若快照扫描V2无变化也核对）。检查导出字节/命名兼容和无新领域复制。Tester独立验证后Reviewer查规格/架构/隐私/取消/过期/跨会话/过度设计，Major返工闭环。

## 任务5 交付

只提交该Issue逻辑文件，push新分支；创建以codex/issue-275-log-parse-v2为base的依赖草稿PR（Closes #266），注明#300合并后才可rebase/master合并。继续保留人工门禁，不关闭#60、#275、#266、不启动服务或浏览器。最终给简洁开发成果与暂缓验收说明，不要求用户立即测试。
