"""
文件读写工具
"""
import os
from pathlib import Path
from typing import Optional


def read_file(file_path: str) -> dict:
    """
    Agno Tool: 读取文件内容
    
    Args:
        file_path: 文件路径
        
    Returns:
        dict: 包含文件内容
            - content: 文件内容
            - file_name: 文件名
            - status: "success" 或 "error"
    """
    try:
        path = Path(file_path)
        
        if not path.exists():
            return {
                "status": "error",
                "error_message": f"文件不存在: {file_path}"
            }
        
        if not path.is_file():
            return {
                "status": "error",
                "error_message": f"路径不是文件: {file_path}"
            }
        
        # 根据文件扩展名选择编码
        if path.suffix.lower() in ['.txt', '.md', '.json', '.py', '.yml', '.yaml']:
            content = path.read_text(encoding='utf-8')
        else:
            content = path.read_bytes().hex()[:1000]  # 二进制文件只读取前1000字节
        
        return {
            "status": "success",
            "content": content,
            "file_name": path.name,
            "file_size": path.stat().st_size,
            "full_path": str(path.absolute())
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"读取文件失败: {str(e)}"
        }


def write_file(file_path: str, content: str) -> dict:
    """
    Agno Tool: 写入文件内容
    
    Args:
        file_path: 文件路径
        content: 文件内容
        
    Returns:
        dict: 包含写入结果
            - status: "success" 或 "error"
    """
    try:
        path = Path(file_path)
        
        # 创建父目录
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        path.write_text(content, encoding='utf-8')
        
        return {
            "status": "success",
            "file_path": str(path.absolute()),
            "bytes_written": len(content.encode('utf-8'))
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"写入文件失败: {str(e)}"
        }


def list_files(directory: str, pattern: str = "*") -> dict:
    """
    Agno Tool: 列出目录下的文件
    
    Args:
        directory: 目录路径
        pattern: 文件匹配模式 (如 "*.txt", "*.xlsx")
        
    Returns:
        dict: 包含文件列表
            - files: 文件路径列表
            - status: "success" 或 "error"
    """
    try:
        path = Path(directory)
        
        if not path.exists():
            return {
                "status": "error",
                "error_message": f"目录不存在: {directory}"
            }
        
        if not path.is_dir():
            return {
                "status": "error",
                "error_message": f"路径不是目录: {directory}"
            }
        
        # 列出文件
        files = [str(f.relative_to(path)) for f in path.glob(pattern) if f.is_file()]
        dirs = [str(f.relative_to(path)) for f in path.glob("*") if f.is_dir()]
        
        return {
            "status": "success",
            "files": files,
            "directories": dirs,
            "total_files": len(files),
            "total_directories": len(dirs)
        }
        
    except Exception as e:
        return {
            "status": "error",
            "error_message": f"列出文件失败: {str(e)}"
        }


def get_project_root() -> str:
    """获取项目根目录"""
    return str(Path(__file__).parent.parent.parent)


def get_standard_fields_path() -> str:
    """获取标准字段表路径"""
    return os.path.join(get_project_root(), "auto", "phase2", "data", "标准字段.txt")


def get_config_path(filename: str) -> str:
    """获取配置文件路径"""
    return os.path.join(get_project_root(), "config", filename)
