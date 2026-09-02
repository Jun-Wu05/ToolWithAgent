"""从最终生产源码生成可验证的交互式架构地图。"""

from __future__ import annotations

import ast
import json
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "source-code-analysis.html"
PRODUCTION_PATTERNS = (
    "application/**/*.py",
    "contracts/**/*.py",
    "web/**/*.py",
    "agent/**/*.py",
    "skills/**/scripts/**/*.py",
)

LAYER_INFO = {
    "Chainlit 适配层": {
        "description": "只拥有 Chainlit 输入、生命周期、设置、进度、每会话锁和结果渲染。",
        "upstream": "用户、Chainlit Element 与 Action",
        "downstream": "Application 公共运行时",
        "reading": ["web/chainlit_app.py", "web/message_router.py", "web/user_message_handlers.py"],
    },
    "Application 运行时": {
        "description": "统一请求、执行账本、会话生命周期、安全事实投影以及模型、字段和文件入口。",
        "upstream": "Web 或其他界面适配器",
        "downstream": "Contracts 与 Application Adapters",
        "reading": [
            "application/request_runtime.py",
            "application/execution.py",
            "application/session_state.py",
        ],
    },
    "Application 适配与策略": {
        "description": "把类型化步骤桥接到专业 Agent、Pipeline、领域函数和 Skills，并原子写回 Session。",
        "upstream": "PlanExecutor / StepSpec",
        "downstream": "Agent、领域能力与 Skills",
        "reading": [
            "application/adapters/composition.py",
            "application/adapters/field_mapping.py",
            "application/field_mapping_batch.py",
            "application/field_mapping_conflicts.py",
        ],
    },
    "类型化契约": {
        "description": "定义计划、步骤、执行报告、SessionFacts、可引用产物和进度事件，不读取运行时状态。",
        "upstream": "所有语义层",
        "downstream": "无运行时依赖",
        "reading": ["contracts/planner_models.py", "contracts/session_facts.py", "contracts/progress.py"],
    },
    "规划、模型与可观测性": {
        "description": "构造 Planner/专业 Agent、模型提供商、字段检索、追踪和结构化日志。",
        "upstream": "Application 请求与适配器",
        "downstream": "Agno 与模型服务",
        "reading": ["agent/core/planner.py", "agent/core/team.py", "agent/core/model_config.py"],
    },
    "Prompt 资产": {
        "description": "集中全部 Prompt 文件的公开加载器和资源定位。",
        "upstream": "Planner、专业 Agent 与 Pipeline",
        "downstream": "包内 Markdown Prompt",
        "reading": ["agent/prompts/__init__.py"],
    },
    "日志解析 Pipeline": {
        "description": "识别日志格式，定位并分类特征，回填样本，为解析规则生成提供结构化结果。",
        "upstream": "LogParseAdapter",
        "downstream": "规则生成与 Session 产物",
        "reading": [
            "agent/tools/pipeline/classification_policy.py",
            "agent/tools/pipeline/log_format_identifier.py",
            "agent/tools/pipeline/log_classifier.py",
        ],
    },
    "解析规则生成": {
        "description": "生成入口规则、子规则、filter 和 normalize，并承接字段映射回写。",
        "upstream": "日志分类与字段映射",
        "downstream": "解析配置",
        "reading": [
            "agent/tools/rule_generator/core.py",
            "agent/tools/rule_generator/filters.py",
            "agent/tools/rule_generator/normalize.py",
        ],
    },
    "领域能力": {
        "description": "标准字段目录与检索、字段/值映射、事件名称标注、枚举与威胁领域操作。",
        "upstream": "Application Adapters",
        "downstream": "配置与类型化产物",
        "reading": [
            "agent/core/standard_field_catalog.py",
            "agent/core/field_retriever.py",
            "agent/shared/mapping_utils.py",
        ],
    },
    "字段调整 Skills": {
        "description": "添加、删除、合并、Base64 解码和正则提取的确定性脚本单一事实源。",
        "upstream": "FieldSkillAdapter",
        "downstream": "原配置来源",
        "reading": [
            "skills/add-fields/scripts/add_fields.py",
            "skills/delete-fields/scripts/delete_fields.py",
            "skills/merge-fields/scripts/merge_fields.py",
        ],
    },
}

RESPONSIBILITIES = {
    "application/request_runtime.py": "自然语言与确定性请求的统一应用入口。",
    "application/execution.py": "类型化计划执行、依赖账本、失败关闭与执行报告。",
    "application/execution_policy.py": "执行前后领域校验与 PlanExecutor 生产组合。",
    "application/session_state.py": "主数据、附件、派生配置和可引用会话产物生命周期。",
    "application/session_projection.py": "把 SessionState 投影为不含敏感值的 SessionFacts。",
    "application/history.py": "受限对话历史的保存、类型化和 Prompt 格式化。",
    "application/model_runtime.py": "模型设置、密钥解析、Team 懒初始化与重置。",
    "application/field_runtime.py": "字段缓存初始化与候选检索公共入口。",
    "application/file_input.py": "Base64/JSON/TXT 确定性解码与主数据原子提交。",
    "application/field_mapping_batch.py": "字段映射分批、并发、超时、重试和漏字段补查。",
    "application/field_mapping_conflicts.py": "字段映射目标一对一占用冲突的确定性裁决。",
    "application/adapters/composition.py": "全部 StepAdapter 的唯一生产组合入口。",
    "application/adapters/field_skill_policy.py": "Field Skill 删除前的纯悬空引用扫描策略。",
    "web/user_message_handlers.py": "自然语言 Web 适配、进度衔接与结果渲染。",
    "web/message_router.py": "每会话锁、Team 获取以及文件/文本消息分发。",
    "web/file_handlers.py": "Chainlit 文件读取、Excel 分流和上传反馈。",
    "web/action_callbacks.py": "十个用户可见业务 Action 与两个弹窗内部 Action 的 Chainlit 接线。",
    "contracts/planner_models.py": "PlanDecision、StepSpec、Artifact 与 ExecutionReport 契约。",
    "contracts/session_facts.py": "Planner 可见的安全会话事实契约。",
    "agent/core/planner.py": "无业务工具的独立 PlannerAgent。",
    "agent/core/team.py": "专业 Agent 注册表与模型固定构造。",
    "agent/core/model_config.py": "ProviderSpec 注册表、密钥解析与模型构造。",
    "agent/core/standard_field_catalog.py": "只读标准字段 schema、资源解析与确定性名称/别名 lookup。",
    "agent/core/field_retriever.py": "标准字段 embedding、缓存、候选排除与排序策略。",
    "agent/prompts/__init__.py": "全部 Prompt 的公开加载器与包相对资源定位。",
    "agent/tools/pipeline/classification_policy.py": "日志体特征键覆盖率的纯路由策略。",
}


def production_files() -> list[Path]:
    """返回稳定排序且去重的生产 Python 文件。"""

    paths = {path for pattern in PRODUCTION_PATTERNS for path in ROOT.glob(pattern)}
    return sorted(paths)


def module_path(path: Path) -> str:
    """把仓库相对 Python 路径转换为可导入模块名。"""

    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def layer_for(relative: str) -> str:
    """按稳定物理边界分配语义层。"""

    if relative.startswith("web/"):
        return "Chainlit 适配层"
    if relative.startswith("contracts/"):
        return "类型化契约"
    if relative.startswith("application/adapters/") or relative in {
        "application/execution_policy.py",
        "application/field_mapping_batch.py",
        "application/field_mapping_conflicts.py",
        "application/field_mapping_input.py",
        "application/field_source.py",
        "application/parsing.py",
        "application/artifact_targets.py",
        "application/enum_mapping_attachments.py",
    }:
        return "Application 适配与策略"
    if relative.startswith("application/"):
        return "Application 运行时"
    if relative.startswith("skills/"):
        return "字段调整 Skills"
    if relative.startswith("agent/prompts/"):
        return "Prompt 资产"
    if relative.startswith("agent/tools/pipeline/"):
        return "日志解析 Pipeline"
    if relative.startswith("agent/tools/rule_generator/"):
        return "解析规则生成"
    if relative in {
        "agent/core/standard_field_catalog.py",
        "agent/core/field_retriever.py",
    }:
        return "领域能力"
    if relative.startswith("agent/core/") or relative == "agent/__init__.py":
        return "规划、模型与可观测性"
    return "领域能力"


def subsystem_for(relative: str) -> str:
    """返回紧凑且可筛选的物理子系统名。"""

    parts = relative.split("/")
    if parts[0] == "skills":
        return parts[1]
    if len(parts) >= 3 and parts[0] in {"agent", "application"}:
        return "/".join(parts[:2])
    return parts[0]


def resolve_import(name: str, module_index: dict[str, str]) -> str | None:
    """把本仓库模块导入解析为真实 Python 文件。"""

    candidate = name
    while candidate:
        if candidate in module_index:
            return module_index[candidate]
        candidate = candidate.rpartition(".")[0]
    return None


def file_record(path: Path, module_index: dict[str, str]) -> dict:
    """提取单文件的度量、公开符号和本地导入。"""

    relative = path.relative_to(ROOT).as_posix()
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=relative)
    doc = (ast.get_docstring(tree) or "").strip().splitlines()
    symbols = []
    import_names = []
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_"):
                symbols.append(node.name)
        elif isinstance(node, ast.Import):
            import_names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            import_names.append(node.module)
    imports = sorted(
        {
            resolved
            for name in import_names
            if (resolved := resolve_import(name, module_index)) and resolved != relative
        }
    )
    responsibility = RESPONSIBILITIES.get(relative)
    if not responsibility:
        responsibility = doc[0] if doc else f"{path.stem.replace('_', ' ')} 模块。"
    return {
        "path": relative,
        "lines": len(source.splitlines()),
        "layer": layer_for(relative),
        "subsystem": subsystem_for(relative),
        "responsibility": responsibility,
        "symbols": symbols[:14],
        "imports": imports,
        "callers": [],
    }


def git_commit() -> str:
    """读取快照基线提交；失败时使用 working-tree。"""

    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "working-tree"


def build_payload() -> dict:
    """构建浏览器展示和 pytest 共用的可验证数据快照。"""

    paths = production_files()
    module_index = {module_path(path): path.relative_to(ROOT).as_posix() for path in paths}
    records = [file_record(path, module_index) for path in paths]
    callers: dict[str, set[str]] = defaultdict(set)
    for record in records:
        for imported in record["imports"]:
            callers[imported].add(record["path"])
    for record in records:
        record["callers"] = sorted(callers[record["path"]])
    return {
        "meta": {
            "generated": datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M CST"),
            "commit": git_commit(),
            "scope": list(PRODUCTION_PATTERNS),
        },
        "totals": {
            "files": len(records),
            "lines": sum(record["lines"] for record in records),
        },
        "layers": LAYER_INFO,
        "reading_order": [
            ["web/chainlit_app.py", "找到 Chainlit 生命周期和消息入口"],
            ["application/request_runtime.py", "沿自然语言或确定性请求进入 Application"],
            ["contracts/planner_models.py", "理解 PlanDecision、StepSpec 和 ExecutionReport"],
            ["application/execution.py", "理解校验、依赖账本和失败关闭"],
            ["application/adapters/composition.py", "查看 12 类步骤的唯一生产组合"],
            ["application/session_state.py", "理解主数据与可引用会话产物生命周期"],
            ["agent/core/planner.py", "查看独立 Planner 的模型边界"],
        ],
        "flows": {
            "自然语言": ["Chainlit Message", "run_user_request", "SessionFacts", "PlannerAgent", "PlanExecutor", "StepAdapter", "ExecutionReport", "Renderer"],
            "确定性 Action": ["Action callback", "StepSpec", "run_deterministic_plan", "PlanExecutor", "StepAdapter", "ExecutionReport", "Renderer"],
            "文件输入": ["Chainlit Element", "Web 类型识别", "Application file_input", "主数据原子提交", "SessionFacts"],
            "字段映射": ["字段来源", "候选检索", "FieldMappingBatchRunner", "一对一冲突裁决", "事件名称标注", "Session 原子写回", "Artifact"],
        },
        "files": records,
    }


HTML_TEMPLATE = r'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ToolWithAgent 源码分析地图</title>
<style>
:root{color-scheme:light dark;--bg:#f3f6fb;--panel:#fff;--panel2:#eaf0f8;--text:#18243a;--muted:#5a6880;--line:#d5deea;--brand:#3157d5;--brand-soft:#e3eaff;--good:#087d69;--shadow:0 10px 30px rgba(25,40,75,.08)}
@media(prefers-color-scheme:dark){:root{--bg:#0f1623;--panel:#172132;--panel2:#202c40;--text:#edf3ff;--muted:#a9b6ca;--line:#334258;--brand:#91aaff;--brand-soft:#25365d;--good:#70d8c2;--shadow:none}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.55 system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}button,input,select{font:inherit}button{cursor:pointer}.shell{width:min(1180px,calc(100% - 32px));margin:auto}.hero{padding:52px 0 28px;background:linear-gradient(135deg,var(--panel),var(--brand-soft))}.eyebrow{color:var(--brand);font-weight:700;letter-spacing:.08em;text-transform:uppercase}.hero h1{font-size:clamp(30px,5vw,54px);line-height:1.08;margin:8px 0 12px}.hero p{max-width:780px;color:var(--muted);font-size:17px}.meta{display:flex;gap:10px;flex-wrap:wrap;color:var(--muted)}main{padding:24px 0 56px}.section{margin:22px 0}.section-head{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:12px}.section-head h2{margin:0}.section-head p{max-width:640px;margin:0;color:var(--muted)}.grid{display:grid;gap:14px}.stats{grid-template-columns:repeat(4,1fr)}.two{grid-template-columns:repeat(2,1fr)}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:18px;box-shadow:var(--shadow)}.stat strong{display:block;font-size:30px;color:var(--brand)}.stat span,.muted{color:var(--muted)}.reading{margin:0;padding-left:22px}.reading li{margin:9px 0}.layer-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}.layer{appearance:none;text-align:left;color:inherit;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px}.layer[aria-pressed="true"]{border-color:var(--brand);background:var(--brand-soft)}.layer b,.layer small{display:block}.layer small{color:var(--muted);margin-top:5px}.detail h3{margin-top:0}.tags{display:flex;flex-wrap:wrap;gap:7px}.tag{background:var(--panel2);border-radius:999px;padding:3px 9px;font-size:13px}.flows{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}.tab{border:1px solid var(--line);border-radius:999px;background:var(--panel);color:var(--text);padding:7px 12px}.tab[aria-pressed="true"]{background:var(--brand);color:#fff;border-color:var(--brand)}.flow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.flow span{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}.flow i{color:var(--brand);font-style:normal}.bars{display:grid;gap:10px}.bar-row{display:grid;grid-template-columns:minmax(140px,220px) 1fr 90px;gap:10px;align-items:center}.track{height:12px;background:var(--panel2);border-radius:999px;overflow:hidden}.fill{height:100%;background:var(--brand)}.controls{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px}.control{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:9px;padding:9px 11px}.search{flex:1;min-width:220px}.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:12px;background:var(--panel)}table{border-collapse:collapse;width:100%;min-width:900px}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{position:sticky;top:0;background:var(--panel2);z-index:1}th button{border:0;background:none;color:inherit;font-weight:700;padding:0}.path-button{border:0;background:none;color:var(--brand);padding:0;text-align:left}.symbols{max-width:260px;color:var(--muted)}footer{border-top:1px solid var(--line);padding:24px 0;color:var(--muted)}code{overflow-wrap:anywhere}@media(max-width:800px){.stats,.two,.layer-grid{grid-template-columns:1fr 1fr}.section-head{display:block}.section-head p{margin-top:5px}.bar-row{grid-template-columns:120px 1fr 72px}}@media(max-width:520px){.shell{width:min(100% - 20px,1180px)}.hero{padding-top:34px}.stats,.two,.layer-grid{grid-template-columns:1fr}.bar-row{grid-template-columns:1fr 65px}.track{grid-row:2;grid-column:1/3}.card{padding:14px}}
</style>
</head>
<body>
<header class="hero"><div class="shell"><div class="eyebrow">Final Application Runtime</div><h1>ToolWithAgent 源码分析地图</h1><p>从最终生产源码生成的可验证快照：物理文件与行数来自仓库，语义层、职责和阅读顺序用于解释依赖边界。</p><div class="meta"><span id="generated"></span><span>·</span><span id="commit"></span></div></div></header>
<main class="shell">
<section class="section"><div class="grid stats"><div class="card stat"><strong id="files-total">—</strong><span>生产 Python 文件</span></div><div class="card stat"><strong id="lines-total">—</strong><span>物理行数</span></div><div class="card stat"><strong id="layers-total">—</strong><span>语义架构层</span></div><div class="card stat"><strong id="largest-file">—</strong><span>最大单文件行数</span></div></div></section>
<section class="section"><div class="section-head"><div><div class="eyebrow">01 / Reading</div><h2>推荐阅读顺序</h2></div><p>先沿真实请求跨越边界，再进入领域实现；路径顺序不是目录树排序。</p></div><div class="card"><ol class="reading" id="reading"></ol></div></section>
<section class="section"><div class="section-head"><div><div class="eyebrow">02 / Architecture</div><h2>语义层与依赖</h2></div><p>选择一层查看职责、上下游、代码规模与首读文件。</p></div><div class="grid two"><div class="layer-grid" id="layers"></div><aside class="card detail" id="layer-detail" aria-live="polite"></aside></div></section>
<section class="section"><div class="section-head"><div><div class="eyebrow">03 / Flows</div><h2>运行时链路</h2></div><p>箭头表达控制或数据方向，不代表每一个底层函数调用。</p></div><div class="flows" id="flow-tabs"></div><div class="flow" id="flow" aria-live="polite"></div></section>
<section class="section"><div class="section-head"><div><div class="eyebrow">04 / Weight</div><h2>子系统代码规模</h2></div><p>行数只表示物理规模，不等同于复杂度或质量。</p></div><div class="card bars" id="bars"></div></section>
<section class="section"><div class="section-head"><div><div class="eyebrow">05 / Inventory</div><h2>生产文件清单</h2></div><p>搜索路径、职责或符号；按语义层和顶层目录筛选。</p></div><div class="controls"><input class="control search" id="search" type="search" placeholder="搜索路径、职责或符号" aria-label="搜索文件"><select class="control" id="layer-filter" aria-label="语义层"><option value="">全部语义层</option></select><select class="control" id="dir-filter" aria-label="顶层目录"><option value="">全部目录</option></select></div><div class="muted" id="table-meta"></div><div class="table-wrap"><table><thead><tr><th><button data-sort="path">文件路径 ↕</button></th><th><button data-sort="lines">行数 ↕</button></th><th>语义层</th><th>子系统</th><th>职责</th><th>主要符号</th></tr></thead><tbody id="rows"></tbody></table></div><div class="card detail" id="file-detail" aria-live="polite" style="margin-top:12px"><h3>选择一个文件</h3><p class="muted">点击文件路径查看本地导入和反向调用者。</p></div></section>
</main>
<footer><div class="shell"><b>统计口径：</b> application、contracts、web、agent 下全部 Python 文件，以及 skills 下 scripts Python 文件；物理行数包含空行和注释。排除测试、评估、输出、配置数据、文档工具和历史材料。</div></footer>
<script id="source-analysis-data" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById("source-analysis-data").textContent);const esc=v=>String(v).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));const nf=new Intl.NumberFormat("zh-CN");let sortKey="path",sortDirection=1;
document.getElementById("generated").textContent=`生成于 ${data.meta.generated}`;document.getElementById("commit").textContent=`基线 ${data.meta.commit}`;document.getElementById("files-total").textContent=nf.format(data.totals.files);document.getElementById("lines-total").textContent=nf.format(data.totals.lines);document.getElementById("layers-total").textContent=nf.format(Object.keys(data.layers).length);document.getElementById("largest-file").textContent=nf.format(Math.max(...data.files.map(f=>f.lines)));
document.getElementById("reading").innerHTML=data.reading_order.map(([path,note])=>`<li><code>${esc(path)}</code> — <span class="muted">${esc(note)}</span></li>`).join("");
const layerGroups=Object.groupBy?Object.groupBy(data.files,f=>f.layer):data.files.reduce((a,f)=>((a[f.layer]??=[]).push(f),a),{});const layerRoot=document.getElementById("layers");layerRoot.innerHTML=Object.entries(data.layers).map(([name,info],index)=>{const items=layerGroups[name]||[];return `<button class="layer" data-layer="${esc(name)}" aria-pressed="${index===0}"><b>${esc(name)}</b><small>${items.length} 文件 · ${nf.format(items.reduce((n,f)=>n+f.lines,0))} 行</small></button>`}).join("");function showLayer(name){const info=data.layers[name],items=(layerGroups[name]||[]).slice().sort((a,b)=>b.lines-a.lines);document.getElementById("layer-detail").innerHTML=`<div class="eyebrow">${esc(name)}</div><h3>${esc(info.description)}</h3><p><b>上游：</b>${esc(info.upstream)}<br><b>下游：</b>${esc(info.downstream)}</p><p><b>先读：</b></p><div class="tags">${info.reading.filter(path=>data.files.some(f=>f.path===path)).map(path=>`<span class="tag"><code>${esc(path)}</code></span>`).join("")}</div><p class="muted">规模最大的文件：${items.slice(0,3).map(f=>`${esc(f.path)} (${f.lines})`).join("、")||"—"}</p>`}layerRoot.addEventListener("click",event=>{const button=event.target.closest("button[data-layer]");if(!button)return;layerRoot.querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));showLayer(button.dataset.layer)});showLayer(Object.keys(data.layers)[0]);
const flowTabs=document.getElementById("flow-tabs"),flowView=document.getElementById("flow");flowTabs.innerHTML=Object.keys(data.flows).map((name,index)=>`<button class="tab" data-flow="${esc(name)}" aria-pressed="${index===0}">${esc(name)}</button>`).join("");function showFlow(name){flowView.innerHTML=data.flows[name].map((step,index)=>`${index?'<i aria-hidden="true">→</i>':''}<span>${esc(step)}</span>`).join("")}flowTabs.addEventListener("click",event=>{const button=event.target.closest("button[data-flow]");if(!button)return;flowTabs.querySelectorAll("button").forEach(item=>item.setAttribute("aria-pressed",String(item===button)));showFlow(button.dataset.flow)});showFlow(Object.keys(data.flows)[0]);
const subsystems=Object.entries(data.files.reduce((a,f)=>(a[f.subsystem]=(a[f.subsystem]||0)+f.lines,a),{})).sort((a,b)=>b[1]-a[1]),maxSubsystem=Math.max(...subsystems.map(([,lines])=>lines));document.getElementById("bars").innerHTML=subsystems.map(([name,lines])=>`<div class="bar-row"><span>${esc(name)}</span><div class="track"><div class="fill" style="width:${(lines/maxSubsystem*100).toFixed(2)}%"></div></div><span>${nf.format(lines)} 行</span></div>`).join("");
const layerFilter=document.getElementById("layer-filter"),dirFilter=document.getElementById("dir-filter"),search=document.getElementById("search");Object.keys(data.layers).forEach(name=>layerFilter.add(new Option(name,name)));[...new Set(data.files.map(f=>f.path.split("/")[0]))].sort().forEach(name=>dirFilter.add(new Option(name,name)));function visibleFiles(){const query=search.value.trim().toLocaleLowerCase("zh-CN"),layer=layerFilter.value,dir=dirFilter.value;return data.files.filter(f=>(!layer||f.layer===layer)&&(!dir||f.path.startsWith(`${dir}/`))&&(!query||[f.path,f.responsibility,...f.symbols].join(" ").toLocaleLowerCase("zh-CN").includes(query))).sort((a,b)=>{const av=a[sortKey],bv=b[sortKey];return (typeof av==="number"?av-bv:String(av).localeCompare(String(bv),"zh-CN"))*sortDirection})}function renderTable(){const files=visibleFiles();document.getElementById("table-meta").textContent=`显示 ${files.length} / ${data.files.length} 个文件，共 ${nf.format(files.reduce((n,f)=>n+f.lines,0))} 行`;document.getElementById("rows").innerHTML=files.map(f=>`<tr><td><button class="path-button" data-path="${esc(f.path)}"><code>${esc(f.path)}</code></button></td><td>${nf.format(f.lines)}</td><td>${esc(f.layer)}</td><td>${esc(f.subsystem)}</td><td>${esc(f.responsibility)}</td><td class="symbols">${esc(f.symbols.join("、")||"—")}</td></tr>`).join("")}function showFile(path){const f=data.files.find(item=>item.path===path);if(!f)return;document.getElementById("file-detail").innerHTML=`<div class="eyebrow">${esc(f.layer)}</div><h3><code>${esc(f.path)}</code></h3><p>${esc(f.responsibility)}</p><p><b>本地导入：</b>${f.imports.map(x=>`<code>${esc(x)}</code>`).join("、")||"无"}</p><p><b>反向调用者：</b>${f.callers.map(x=>`<code>${esc(x)}</code>`).join("、")||"无"}</p>`}document.querySelector("thead").addEventListener("click",event=>{const button=event.target.closest("button[data-sort]");if(!button)return;if(sortKey===button.dataset.sort)sortDirection*=-1;else{sortKey=button.dataset.sort;sortDirection=1}renderTable()});document.getElementById("rows").addEventListener("click",event=>{const button=event.target.closest("button[data-path]");if(button)showFile(button.dataset.path)});[search,layerFilter,dirFilter].forEach(control=>control.addEventListener("input",renderTable));renderTable();
</script>
</body>
</html>
'''


def main() -> None:
    """生成并写入最终源码分析 HTML。"""

    payload = build_payload()
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    OUTPUT.write_text(HTML_TEMPLATE.replace("__DATA__", encoded), encoding="utf-8")
    print(
        f"generated {OUTPUT.relative_to(ROOT).as_posix()}: "
        f"{payload['totals']['files']} files / {payload['totals']['lines']} lines"
    )


if __name__ == "__main__":
    main()
