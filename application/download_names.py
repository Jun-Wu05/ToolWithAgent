"""Compatible artifact download names shared by UI entry points."""

def download_filename(kind: str, timestamp: str) -> str:
    """按产物语义生成用户可见下载名。"""
    names = {
        "log_classification": f"logclassification_{timestamp}.json",
        "enum_values": f"enumvalues_{timestamp}.json",
        "threat_mapping": f"threatmapping_{timestamp}.xlsx",
        "mapped_config": f"fieldmapped_config_{timestamp}.txt",
        "mapped_sub_rules": f"fieldmapped_subrules_{timestamp}.txt",
        "enummapping_config": f"enummapping_config_{timestamp}.txt",
        "threatmapping_config": f"threatmapping_config_{timestamp}.txt",
        "cancelmapping_config": f"cancelmapping_config_{timestamp}.txt",
        "current_config": f"current_config_{timestamp}.txt",
        "mappedconfig_subrules": f"mappedconfig_subrules_{timestamp}.txt",
        "mappedconfig_mainrules": f"mappedconfig_mainrules_{timestamp}.txt",
        "unmappedconfig_subrules": f"unmappedconfig_subrules_{timestamp}.txt",
        "field_adjusted_config": f"fieldadjusted_config_{timestamp}.txt",
    }
    if kind in names:
        return names[kind]
    raise ValueError(f"不支持的下载产物类型: {kind}")
