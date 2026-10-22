# Issue 实施 SOP：git worktree 隔离工作流

每个 issue 从 master 开短命分支实施、PR 合并后即删分支；**较大改动用独立 git worktree 隔离，小改动在主 worktree 直通**（判据见下）。允许多棵临时 worktree 并行，前提是：并行 issue 的改动面零相交、每棵 worktree 独立补第 2 步环境文件并显式使用树内 `--basetemp`、任一 PR 合并后立即清理对应 worktree。该流程已在 #178（worktree 五组删除）、#179（worktree bug 修复）、#176（主 worktree 直通小修复）上完整验证。跨 agent（多会话）并行时，另见下文「双 Agent 并行协作」。

## 是否需要建 worktree：自动判据

不是按"感觉大小"判断，按可客观检查的信号。**任一命中 → 建 worktree**：

| 信号 | 检查方式 |
|---|---|
| 预计改动 ≥3 个文件，或跨 ≥2 个模块目录（agent / application / web / contracts / skills） | 读 issue 的修复方案/影响清单 |
| issue 要求分组提交（含实现顺序、多阶段、"每组提交便于单独 revert"字样） | 读 issue 正文 |
| 主 worktree 有未提交 WIP，且改动文件可能与之相交 | `git status` + 文件清单比对 |
| 需要长时间在隔离目录跑基线/验收（如重复全量测试对比） | 实施计划 |

**全部不命中 → 直通**（小改动：单/双文件、单 commit 可完成、主 worktree 干净或零交集、issue 已给完整修复方案）：

```bat
git checkout -b codex/issue-<NNN>-<slug> master   & :: 主 worktree 内，未跟踪文件不受影响
:: …实现 → 全量 pytest 绿 →（动了生产 .py 则先重生成快照）…
git push github <分支> → PR（Closes #NNN）→ squash merge
git checkout master && git fetch github master:master
git branch -D <分支> && git push github --delete <分支>
```

两条路径共享不变式：**从 master 开分支、全量 pytest 绿、PR 带 `Closes #NNN`、做完删分支**；worktree 路径另需第 2 步补环境文件。

## 前提

- 远程：`github` = Jun-Wu05/ToolWithAgent（issue 与 PR 所在）；`origin` = gitcode 镜像，不用管。
- 主 worktree 默认驻留 master：更新用 `git pull --ff-only github master`；若主 worktree 临时切到特性分支（master 不被任何 worktree 占用），才可用 `git fetch github master:master` 直接更新引用。
- Python 用全局环境（无仓库内 venv）；测试全离线，但依赖两个 gitignore 的本地文件组（见第 2 步）。

## Tracker 发布前确认

Agent 往 tracker 发布任何产物（新建 issue、PR、spec）前，先在会话中给用户过目：

1. 未与用户讨论过的话题，先问清（grill / 澄清提问），不得擅自定稿发布；已讨论过的话题，只综合既有讨论，不新增未讨论的设计决策。
2. 成文（issue 正文、PR 正文、spec）先展示全文，用户确认后再发布。

已确认 issue 的机械执行（贴标签、按用户指示评论或关闭）不受此限。目的：防止 agent 替用户做设计决策或替双方立约。

## 流程

### 1. 领取与开分支

```bat
git fetch github master:master
git worktree add D:\Agent\agent_design\twa-<NNN> -b codex/issue-<NNN>-<slug> master
```

- worktree 目录名 `twa-<NNN>`，分支名沿用 `codex/issue-<NNN>-<slug>` 惯例。
- 文档类小改动（非 issue）分支用 `docs/<slug>`，其余同此 SOP。

### 2. 补环境（新 worktree 是干净 checkout，缺以下本地文件）

```bat
copy D:\Agent\agent_design\toolswithagent\config\标准字段_embeddings.npy  <worktree>\config\
copy D:\Agent\agent_design\toolswithagent\config\标准字段_records.json     <worktree>\config\
copy D:\Agent\agent_design\toolswithagent\config\标准字段_cache_meta.json  <worktree>\config\
copy D:\Agent\agent_design\toolswithagent\.env                             <worktree>\.env
```

- 3 个 embedding 缓存：`tests/test_standard_field_catalog_characterization.py` 需要。
- `.env`：3 个密钥相关测试（test_explicit_feature_field / test_log_coverage_info / test_provider_registry）依赖其中的 API key 链。

### 3. 基线必须全绿

```bat
cd /d <worktree> && python -X utf8 -m pytest -q --basetemp=.pytest-tmp-<NNN>-baseline
```

基线不绿不许开工——先查环境（第 2 步漏复制是最常见原因）。

在 Codex 的 `workspace-write` 沙箱中，独立 worktree 通常位于主 workspace 可写根之外。第一次运行 pytest 就必须申请该 worktree 的写权限，并显式传入位于 worktree 内的 `--basetemp`；不要先用受限权限试跑。若 `.pytest_cache`、`agent/logs` 或系统临时目录出现 `PermissionError`，应立即判定为环境失败并修正权限，不要把 Windows 临时目录探测造成的高 CPU/长时间等待误认为测试仍在正常执行。测试结束后只删除已核对绝对路径的本次 `.pytest-tmp-<NNN>-*` 目录。

### 4. 领取协议复核

issue 正文自带「领取协议」：逐项 `git grep` 复核其删除/修改清单的 file:line 证据。**代码漂移与证据矛盾 → 停止实施，在 issue 评论矛盾点并加 `needs-info` 标签**，不即兴改设计。

### 5. 实施

- bug 修复类测试先行：先写红测试，再修到绿。
- 改动面大的按逻辑组分组提交（便于单独 revert），每组提交前全量 pytest 绿。
- 只要动了生产 Python 文件（application/contracts/web/agent/skills），先 `python -X utf8 scripts/generate_source_code_analysis.py` 重新生成快照再跑测试，否则 `test_documentation_architecture` 门禁必红。
- 完成 issue 的「文档同步」节（架构文档 / README / CHANGELOG / five-evidence 等，以 issue 列的为准）。

### 6. PR 与合并

```bat
git push github codex/issue-<NNN>-<slug>
gh pr create --repo Jun-Wu05/ToolWithAgent --base master --title "..." --body "Closes #<NNN> ..."
```

- PR 正文必须含 `Closes #<NNN>`（合并自动关 issue）与领取协议复核结论。
- 单一目的改动 squash 合并；分组提交需要保留的用 merge commit 合并（如 #178）。

### 7. 人工 / 浏览器验收交接

只要验收运行在 worktree（包括多个 PR 汇总后的联合验收分支），交给人工测试前必须明确给出并核对：

- worktree 的绝对路径、分支名和完整 `HEAD`；联合验收时还要列出纳入的 PR / commit。
- 从该 worktree 启动服务的精确命令，以及预期日志目录 `<worktree>\agent\logs`。
- 当前端口是否仍被旧进程占用；如已占用，先让用户停止旧服务，再从正确目录启动。
- 浏览器使用全新聊天 / Session，避免旧会话状态污染结果。

交接清单至少包含以下可复制命令（路径替换为本次实际值）：

```powershell
Set-Location -LiteralPath '<worktree>'
git branch --show-current
git rev-parse HEAD
git status --short
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
chainlit run web/chainlit_app.py --port 8000
```

启动后必须从新产生的日志确认源码路径或运行目录属于该 worktree；如果日志仍落在主目录，立即停止测试并修正启动目录。浏览器验收默认只交付详细人工步骤和预期结果；只有用户明确要求“自动化测试”“你来操作浏览器”或“你来跑 Web 测试”时，Agent 才能启动服务或操作浏览器。

### 8. 清理（做完即删）

```bat
git fetch github master:master
git worktree remove --force D:\Agent\agent_design\twa-<NNN>
git branch -d <分支>            （未合并时 -D）
git push github --delete <分支>
```

`--force` 是因为 worktree 里有复制的未跟踪文件（缓存/.env）；它们只是主目录的副本，无独有内容。

## 双 Agent 并行协作

多个 agent（会话）同时在本仓库工作时（如 master 维护线 + V2 开发线），在单 agent SOP 之上追加以下协议。**GitHub Issues 是唯一任务表**，不另建文件形式的任务表——避免出现第二份真相。跨 agent 协调只经 GitHub（issue 评论、远端分支状态）进行，不依赖会话记忆；凡未落 tracker 的约定对其他 agent 不存在。**用户的显式指派优先于先声明者优先**；协议只在没有明确指派时裁决 agent 间的自动领取。

### 领取与改动面申报

- 发领取声明前先 fetch 最新 master（及所在开发线基线），声明与零相交检查基于最新远端状态。
- 领取 issue 前先在其上发**领取声明**评论：声明者、工作分支/worktree、预计改动面（文件/模块清单）。先声明者优先；后声明者若改动面相交，让位重排队。
- **改动面零相交是并行前提**：领取声明清单与任一在途分支的改动面相交，即不得并行开工。
- 实施中发现需要改清单外文件时，先回 issue 评论**补报**更新声明；补报后与他人相交的，停止实施回到排队。
- 任务完成（PR 合并）或放弃时，领取人回 issue 更新声明状态（已完成/释放）；释放后排队者可按序接手。

### 依赖与排队

- 依赖关系用 issue 间的 blocked-by 表达；被依赖 issue 合并前，依赖方不领取。
- **契约先行**：两线共同需要的接口/数据结构，先落契约层（`contracts/` 或模块公共接口）+ 测试合入 master，双方都基于契约实施，不各自造私有接口。
- **堆叠分支护栏**：仅契约先行场景允许把开发分支堆在被依赖分支之上；被依赖分支合并后必须 rebase 回 master 并重跑全量测试。其余情况一律等依赖合并后从 master 重开。
- **THROWAWAY 原型例外**：探索/原型工作（不进 master 的 THROWAWAY 分支）可不立 issue，但须在分支 README 或首条提交注明 THROWAWAY 及目的，且同样不得与在途任务改动面相交。

### 集成方向

- 集成单向流动：开发线（如 V2）单向吸收 master；master 不从开发线摘 cherry-pick。开发线成果合回 master 由开发线发起，并保证全量 pytest 绿。

### 冲突处理（三层）

1. **任务冲突**：两 agent 声明了相交改动面或领取了同一 issue——后声明者让位，重排队或改选任务。
2. **文本冲突**：合并时的同文件 git 冲突。零相交前提下不应发生；发生即领取声明失真，按任务冲突处理（让位方调整）并回补申报清单。
3. **语义冲突**：文件不相交但行为相互破坏（如双方改了同一行为的两端）。以全量 pytest 兜底：回归红的一方在自己分支修到绿；双方都绿但行为仍异常的，提交用户裁决。

### 本地资源隔离

- 本地验收服务端口按线隔离（master 线 8000，V2 线 8112/5175）；启动前核对端口占用，不共用。
- 各 agent 的 worktree 与分支互不触碰；同一分支不得被两个 worktree 同时检出（git 自带拒绝，不要绕过）。

本协议对 ≥2 个 agent 通用；当前实例：master 维护线 + `codex/v2-development` V2 线。

## 速查：常见坑

| 症状 | 原因 |
|------|------|
| 新 worktree 3 个测试红（Bearer 空密钥 / coverage KeyError / 密钥解析） | 没复制 `.env` |
| characterization 测试红（FileNotFoundError *.npy） | 没复制 3 个 embedding 缓存 |
| test_documentation_architecture 红（行数不一致） | 改了生产文件没重新生成 source-code-analysis 快照 |
| 独立 worktree 中 pytest 报 `.pytest_cache` / `agent/logs` / tempfile `PermissionError`，或高 CPU 久不结束 | 首次调用未取得 worktree 写权限；用获批权限并显式指定 worktree 内的 `--basetemp` 重跑，结束后清理该精确目录 |
| `gh pr create` 报 No commits between master and ... | push 没成功，检查 `git ls-remote github` 后重推 |
| CMD 下 `head`/`tail`/管道转义报错 | Windows CMD 无这些命令；grep 正则含引号/竖线时拆成单条 `git grep -n -E ...` 跑 |
| 多行 `python -c` 无输出、看似没执行也不报错 | CMD 引号解析静默吞掉多行脚本；文件改写一律用 Read/Write/Edit 工具，确需脚本就写临时 .py 再执行或压成单行 |
| 命令链里 `;`、`2>nul;` 后半段被跳过 | CMD 不认 `;` 作分隔符（用 `&`/`&&`），`2>nul;` 会截断整条命令；删除/清理类命令单独执行 |
| 链式 `& echo EXIT=%ERRORLEVEL%` 显示 0 但命令实际失败 | `%ERRORLEVEL%` 在整行解析时展开（早于命令执行）；判成败直接看输出里的 F/E 标记，或把回显单独跑 |
| CMD `for` 循环体内用 `&` 串联命令，一次执行产生多个提交并推上远端（#395、#402 两次，均靠 soft reset + force push 修复） | `&` 绑定的整串命令随每次迭代逐条执行；循环体只放单条命令，多步操作写 .bat 脚本或分步执行，提交/推送绝不放进带 `&` 的循环体 |
