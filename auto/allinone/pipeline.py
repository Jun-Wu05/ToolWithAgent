# 主流水线框架

# 导入必要的模块
from phase1_processor import process_phase1
from phase2_llm_calller import process_phase2
from phase3_extractor import process_phase3
from utils import load_config


def run_pipeline(config_path: str = "config.yaml"):
    """
    执行完整三阶段流水线
    流程：
    1. 加载配置
    2. 执行 Phase1（自动）
    3. 执行 Phase2（手动或自动）
    4. 执行 Phase3（自动）
    5. 生成执行报告
    """
    config = load_config(config_path)
    
    # Phase1
    print("=== Phase1: 索引提取 ===")
    phase1_result = process_phase1(
        input_dir=config["phase1"]["input_dir"],
        output_dir=config["phase1"]["output_dir"]
    )
    print(f"✓ Phase1 完成：{phase1_result['stats']}")
    
    # Phase2
    print("\n=== Phase2: LLM 字段映射 ===")
    phase2_result = process_phase2(
        normalize_indexes_file=phase1_result["normalize_indexes_file"],
        output_dir=config["phase2"]["output_dir"],
        phase2_config=config["phase2"],
        auto_call=config["phase2"].get("auto_call", False)
    )
    
    if not config["phase2"].get("auto_call", False):
        input("Phase2 提示词已生成，请手动完成 LLM 调用后按回车继续...")
    
    # Phase3
    print("\n=== Phase3: 字段值提取 ===")
    phase3_result = process_phase3(
        field_mapping_file=phase2_result["field_mapping_file"],
        log_dir=config["phase3"]["log_dir"],
        output_dir=config["phase3"]["output_dir"]
    )
    print(f"✓ Phase3 完成：{phase3_result['stats']}")
    
    # 生成报告
    generate_report(phase1_result, phase2_result, phase3_result)
