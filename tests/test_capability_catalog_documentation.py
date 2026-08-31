"""领域能力目录的导航、schema 与审计语义门禁（Issue #154）。"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs" / "architecture" / "领域能力目录.md"


def _catalog_text() -> str:
    return CATALOG.read_text(encoding="utf-8")


def test_领域能力目录具有稳定schema和核心能力() -> None:
    text = _catalog_text()

    metadata = ("文档版本", "对应分支", "架构决策")
    for item in metadata:
        assert item in text

    schema_fields = (
        "能力名称",
        "职责",
        "领域术语",
        "公共入口",
        "上游",
        "下游",
        "测试接缝",
        "生命周期状态",
        "负责人类别",
    )
    for field in schema_fields:
        assert field in text

    core_capabilities = (
        "StandardFieldCatalog",
        "日志分类策略",
        "FieldSkillAdapter",
        "五证据删除审计",
    )
    for capability in core_capabilities:
        assert capability in text


def test_领域能力目录区分模块角色并记录静态分析盲区() -> None:
    text = _catalog_text()

    module_roles = (
        "public entrypoint",
        "domain transformation",
        "policy",
        "integration adapter",
        "legacy/audit candidate",
    )
    for role in module_roles:
        assert role in text

    blind_spots = ("延迟导入", "包级重导出", "动态加载", "仓库外依赖")
    for blind_spot in blind_spots:
        assert blind_spot in text

    assert "log_pattern_store" in text
    assert "在用能力" in text
    assert "运行时服务定位器" in text
    assert "全局注册中心" in text


def test_领域能力目录把行数保留为软性评审信号() -> None:
    text = _catalog_text()

    assert "400–500" in text
    assert "不作为 CI 硬门禁" in text
    assert "不作为质量评分" in text
    assert "职责深度" in text
    assert "测试接缝" in text


def test_领域能力目录可从稳定文档入口发现() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    architecture = (ROOT / "docs" / "architecture" / "架构概览.md").read_text(
        encoding="utf-8"
    )

    assert "[领域能力目录](docs/architecture/领域能力目录.md)" in readme
    assert "[领域能力目录](./领域能力目录.md)" in architecture
