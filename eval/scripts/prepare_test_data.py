"""
批量处理脚本 - 准备标准字段测试数据

从archive目录中的base64编码测试数据文件批量提取测试数据
"""
import sys
import os
import argparse
from pathlib import Path

# 添加项目根目录到Python路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, project_root)

from eval.tools.test_data_extractor import batch_extract_test_data


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='标准字段测试数据提取工具')
    parser.add_argument('--source', type=str, help='源目录路径（包含base64文件）')
    parser.add_argument('--output', type=str, help='输出目录路径')
    parser.add_argument('--default', action='store_true', help='使用默认路径')
    
    args = parser.parse_args()
    
    print("="*60)
    print("标准字段测试数据提取工具")
    print("="*60)
    
    # 默认配置
    default_source_dir = os.path.join(project_root, "archive", "测试数据", "标准字段测试数据", "data")
    default_output_dir = os.path.join(project_root, "eval", "test_data")
    
    # 确定路径
    if args.default or (args.source is None and args.output is None):
        # 使用默认路径
        source_dir = default_source_dir
        output_dir = default_output_dir
        print(f"使用默认路径配置")
    else:
        # 使用命令行参数
        source_dir = args.source if args.source else default_source_dir
        output_dir = args.output if args.output else default_output_dir
    
    # 转换为绝对路径
    source_dir = os.path.abspath(source_dir)
    output_dir = os.path.abspath(output_dir)
    
    print(f"\n源目录: {source_dir}")
    print(f"输出目录: {output_dir}")
    print(f"\n开始提取测试数据...\n")
    
    try:
        # 批量提取测试数据
        summary = batch_extract_test_data(source_dir, output_dir)
        
        print(f"\n{'='*60}")
        print("提取完成！")
        print(f"{'='*60}")
        print(f"详细处理结果请查看: {summary['summary_file']}")
        
    except FileNotFoundError as e:
        print(f"\n错误: {str(e)}")
        print(f"请确认源目录路径正确: {source_dir}")
        sys.exit(1)
    except Exception as e:
        print(f"\n错误: 提取过程中出现异常")
        print(f"详细信息: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()