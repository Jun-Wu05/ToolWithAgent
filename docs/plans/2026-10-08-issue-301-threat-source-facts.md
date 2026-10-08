# Issue #301 威胁来源事实校验 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 模型错误声称已有 desc 不存在时，不把模型猜测呈现为字段事实；强化显式换源计划，保持失败关闭和旧配置。

**Architecture:** 复用 PlannerService 单次调用与 SessionFacts，校验结构化 requested_field，遇到共同来源字段矛盾返回稳定规划错误。由 Planner 理解授权与构建四步计划，不从用户原文另做执行路由。

**Tech Stack:** Python、Pydantic、pytest、既有 Planner Prompt。

## 1. 领取证据和基线

复核 agent/core/planner.py:336-343、application/session_projection.py 的 threat_source_fields 交集、agent/prompts/planner.md 换源契约；本树完整 pytest 必须先通过。

## 2. Tester 红测试

修改 tests/test_planner_agent.py，fake runner 返回 clarification/threat_source_not_found/desc，facts含desc共同来源。断言结果不再是不存在声明、无执行步骤、调用数1、错误文案不带原日志或整字段池。
边界覆盖真的不存在仍拒绝、只有部分覆盖不提升授权、proposal/cancel不被改成execute。命令：明确 Chainlit Python -m pytest tests/test_planner_agent.py -q --basetemp=tmp/pytest-301-red。

## 3. Builder 最小修复

修改 agent/core/planner.py 的现有文案规范化函数：requested_field in facts.threat_source_fields 时返回稳定 planner_source_fact_conflict + 明确本次未执行；日志只含稳定原因/布尔事实，不记录用户原文、日志样例或字段池。
修改 agent/prompts/planner.md：显式改用 X 的参数来自当前输入，而非旧威胁映射产物；X在共同来源时生成完整替换链，不报来源缺失/不存在，存在不等于已绑定。缺/部分覆盖保留既有追问，提案/取消继续遵守授权边界。
不增加Planner重试，不正则合成业务计划。

## 4. 自动验证与独立 Review

运行定向与完整 pytest；生产 Python 修改后先 python -X utf8 scripts/generate_source_code_analysis.py。静态检查与 git diff --check；Reviewer核对事实冲突不会执行、不存在及部分覆盖保持、隐私/单次调用/旧配置不变。

## 5. 提交与人工交接

全量绿后单逻辑提交、push新短命分支、draft PR带Closes #301。保留独立worktree，给用户直接启动命令，用同一JSON样本验证 event_str→desc→event_str。真实Provider/UI未验证前不声称换源已完整修复，不合并、不关闭#60或#301。
