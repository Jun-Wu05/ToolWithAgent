# Project Guidelines

## 项目概览
- 这是一个以 Windows 为主的 Python Tkinter 桌面工具项目，主入口是 `main.py`。
- GUI 组装在 `main.py` 与 `src/gui_handler.py`，核心处理逻辑集中在 `src/data_processor.py`、`src/threat_type_manager.py` 与 `src/handlers/`。
- `auto/` 目录是独立的分阶段自动化处理流水线，和主 GUI 工具是两套相邻但用途不同的代码路径。

## 代码风格
- 所有代码注释、文档字符串、说明性文字统一使用中文。
- 优先保持现有模块职责，不要把 GUI 逻辑直接塞进数据处理模块，也不要把数据处理细节回填到界面层。
- 修改代码时，优先沿用 `src/handlers/` 中按功能拆分处理器的模式。

## 架构约定
- `main.py` 负责应用启动与 Tkinter 根窗口初始化，不承载复杂业务逻辑。
- `src/gui_handler.py` 负责界面状态、用户交互和日志展示。
- `src/data_processor.py` 与 `src/handlers/*.py` 负责具体业务处理。
- 威胁类型相关配置与规则处理依赖 `config/threat_type_config.json` 以及相关文本配置；涉及威胁类型标准化时，不要绕过现有配置直接硬编码。
- `auto/phase1`、`auto/phase2`、`auto/phase3` 是串行阶段性数据处理目录；新增自动化能力时，先判断应放入 GUI 主流程还是 `auto/` 流程。

## 运行与构建
- 安装依赖：`pip install -r requirements.txt`
- 本地运行：`python main.py`
- Windows 打包：运行 `scripts/fix_packaging.bat`
- 当前仓库未见标准测试目录或测试命令；如需验证，优先做最小范围运行验证，不要虚构测试入口。

## 项目特有约定
- 默认运行环境是 Windows；路径、批处理脚本和 PyInstaller 参数都按 Windows 习惯编写。
- 仓库中存在中文文件名和路径；修改文件引用、打包参数或资源路径时，注意保持兼容。
- 需要从项目根目录执行命令，避免因为相对路径导致 `main.py`、配置文件或资源文件加载失败。
- `scripts/fix_packaging.bat` 中的 `--add-data` 使用 Windows 分隔格式 `源;目标`，不要误改成非 Windows 风格。

## 文档与参考
- 功能总览、项目结构、基础使用说明见 `docs/readme.md`。
- `auto/` 分阶段流程说明见 `auto/README.md`。
- 领域说明与处理规则见 `docs/威胁类型映射与字段处理完整指南.md`。
- 代码整理与优化记录见 `docs/代码优化.md`。
- 若用户要求扩展代理/技能相关说明，可参考 `docs/skill.md`。

## 修改建议
- 做改动前先判断影响范围：GUI、核心处理器、还是 `auto/` 阶段脚本。
- 没有充分依据时，不要重命名现有中文字段、配置键名或输出文件名。
- 如果要补充新文档，优先链接现有文档而不是重复搬运内容。
