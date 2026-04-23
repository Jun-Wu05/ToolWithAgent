"""
数据映射智能助手 - Chainlit聊天界面

核心特点：
1. 对话式交互，Agent通过聊天与用户沟通
2. 支持在聊天中拖拽上传文件
3. 与Agno Team无缝集成（纯UI层）
4. 使用 cl.Dataframe 展示映射结果，支持排序/筛选/导出

使用JSON格式接收Agent的映射结果：
[{"原始字段名": "xxx", "系统属性名称": "yyy", "匹配状态": "匹配成功"}]

使用方法：
1. 设置环境变量 SILICONFLOW_API_KEY 或在.env文件
2. 运行: chainlit run web/chainlit_app.py
"""

# === CRITICAL: 这必须在所有其他导入之前 ===
import sys
import os

# 获取项目根目录（web的父目录）
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)

# 确保项目根目录在sys.path的最前面
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 验证路径
print(f"[DEBUG] 项目根目录: {_project_root}")
print(f"[DEBUG] agent目录存在: {os.path.exists(os.path.join(_project_root, 'agent'))}")
# =========================================

# 加载.env文件
from dotenv import load_dotenv
load_dotenv()

import chainlit as cl
import json
import re
import io
from datetime import datetime

# 初始化日志
from src.logger import get_logger
logger = get_logger("chainlit_app")
logger.info("=" * 60)
logger.info("Chainlit聊天式Web应用启动")
logger.info("=" * 60)


# ============= 工具函数 =============

def parse_json_mapping_result(content: str) -> list:
    """
    解析Agent返回的JSON映射结果
    只提取正确的3列格式：原始字段名、系统属性名称、匹配状态
    
    Args:
        content: Agent返回的内容（可能是纯JSON或包含在其他文本中）
    
    Returns:
        list: 映射结果列表，解析失败返回空列表
    """
    # 定义正确的列名
    VALID_COLUMNS = {"原始字段名", "系统属性名称", "匹配状态"}
    
    def validate_item(item: dict) -> bool:
        """验证单条记录是否符合格式要求"""
        if not isinstance(item, dict):
            return False
        # 检查是否只有3个键
        keys = set(item.keys())
        if keys != VALID_COLUMNS:
            # 过滤多余列，只保留需要的
            filtered = {k: v for k, v in item.items() if k in VALID_COLUMNS}
            if len(filtered) == 3:
                item.clear()
                item.update(filtered)
                return True
            return False
        return True
    
    # 方法1：去除前后空白后直接尝试解析
    content = content.strip()
    try:
        result = json.loads(content)
        if isinstance(result, list):
            valid_result = [item for item in result if validate_item(item)]
            if valid_result:
                logger.info(f"[PARSER] 方法1解析成功，获得 {len(valid_result)} 条有效记录")
                return valid_result
    except json.JSONDecodeError:
        pass
    
    # 方法2：查找第一个 [ 到最后一个 ] 之间的内容
    first_bracket = content.find('[')
    last_bracket = content.rfind(']')
    
    if first_bracket != -1 and last_bracket > first_bracket:
        json_candidate = content[first_bracket:last_bracket + 1]
        try:
            result = json.loads(json_candidate)
            if isinstance(result, list) and len(result) > 0:
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[PARSER] 方法2解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError:
            pass
    
    # 方法3：尝试提取代码块中的JSON
    code_block_pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    matches = re.findall(code_block_pattern, content)
    for match in matches:
        try:
            result = json.loads(match.strip())
            if isinstance(result, list):
                valid_result = [item for item in result if validate_item(item)]
                if valid_result:
                    logger.info(f"[PARSER] 方法3解析成功，获得 {len(valid_result)} 条有效记录")
                    return valid_result
        except json.JSONDecodeError:
            continue
    
    logger.warning(f"[PARSER] 解析失败，无法提取有效的映射结果")
    return []


def create_dataframe_elements(mapping_data: list) -> list:
    """
    根据映射数据创建 Chainlit Dataframe 元素
    
    Args:
        mapping_data: 映射结果列表
    
    Returns:
        list: Chainlit 元素列表
    """
    import pandas as pd
    
    if not mapping_data:
        return []
    
    # 将列表转换为 pandas.DataFrame
    df = pd.DataFrame(mapping_data)
    
    # 使用 cl.Dataframe 展示数据
    # pagination=0 禁用分页，一次性展示所有行
    elements = [
        cl.Dataframe(
            data=df,
            display="inline",
            title="📊 字段映射结果",
            pagination=0,  # 设为0禁用分页
        )
    ]
    
    return elements


# ============= Chainlit 事件处理 =============

@cl.on_chat_start
async def start():
    """聊天开始时初始化"""
    # 创建用户会话状态
    user_session = {
        "team": None,
        "decoded_data": None,
        "decoded_fields": None,
        "original_log": None,
        "last_mapping_data": None,  # 保存最后一次映射结果
    }
    cl.user_session.set("user_session", user_session)
    
    # 发送欢迎消息
    await cl.Message(
        content="""👋 **数据映射智能助手已就绪！**

📋 **功能说明：**
- **上传文件**：支持拖拽或点击上传 Base64/TXT/JSON/Excel 文件
- **字段映射**：发送"映射"生成字段映射表
- **威胁类型**：发送"威胁"进行威胁类型标准化
- **枚举处理**：发送"枚举"处理枚举字段

✨ **表格特性：**
- 支持排序（点击列标题）
- 支持筛选
- 支持一键复制
- 支持Excel导出

请上传数据文件或直接发送消息开始对话。""",
    ).send()


@cl.on_message
async def main(message: cl.Message):
    """
    处理用户消息 - 纯UI层
    
    Args:
        message: 用户消息，包含文本和可能上传的文件
    """
    # 重新设置sys.path（Chainlit可能在不同线程中运行）
    import sys, os
    _root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    
    user_session = cl.user_session.get("user_session")
    
    # 初始化Team
    if user_session["team"] is None:
        try:
            from agent.core.team import create_data_mapping_team
            user_session["team"] = create_data_mapping_team()
            logger.info("✅ Team初始化成功")
        except ValueError as e:
            await cl.Message(content=f"❌ Team初始化失败: {str(e)}").send()
            return
        except Exception as e:
            logger.error(f"❌ Team初始化失败: {str(e)}")
            await cl.Message(content=f"❌ Team初始化失败: {str(e)}").send()
            return
    
    team = user_session["team"]
    
    # 处理上传的文件
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'type') and element.type == "file":
                await handle_file_upload(user_session, element)
    
    # 处理文本消息 - 纯UI，直接传递给Team
    user_text = message.content.strip()
    if user_text:
        await handle_user_message(user_session, team, user_text)


# ============= 文件处理 =============

async def handle_file_upload(user_session: dict, element):
    """处理文件上传"""
    try:
        # 获取文件路径并读取内容
        if hasattr(element, 'path') and element.path:
            with open(element.path, 'r', encoding='utf-8', errors='ignore') as f:
                file_content = f.read()
        elif hasattr(element, 'content'):
            file_content = element.content
            if isinstance(file_content, bytes):
                file_content = file_content.decode('utf-8', errors='ignore')
        else:
            file_content = str(element)
        
        # 解码Base64内容
        from agent.core.agent import simple_decode
        result = simple_decode(file_content)
        
        if result["status"] == "success":
            user_session["decoded_data"] = result["decoded_json"]
            user_session["decoded_fields"] = result["fields"]
            user_session["original_log"] = result["original_log"]
            
            # 构建简化 JSON（只包含必要的索引和日志示例）
            indexes = result.get("fields", [])
            original_log = result.get("original_log", [])
            original_log_sample = original_log[0] if original_log else ""
            
            simplified_data = {
                "fields": indexes,  # 全量 index 列表
                "original_log_sample": original_log_sample
            }
            user_session["simplified_data"] = simplified_data
            
            # 记录简化 JSON
            import json as json_module
            simplified_json_str = json_module.dumps(simplified_data, ensure_ascii=False)
            logger.info(f"[DECODE] 简化JSON（发送给LLM）: {simplified_json_str[:500]}...")
            
            field_count = result["field_count"]
            await cl.Message(
                content=f"""✅ **文件解码成功！**

📊 **字段数量**：{field_count} 个

现在可以直接发送消息进行字段映射、威胁类型处理等操作。"""
            ).send()
        else:
            await cl.Message(content=f"❌ 解码失败：{result.get('error_message', '未知错误')}").send()
            
    except Exception as e:
        logger.error(f"文件处理异常: {str(e)}")
        await cl.Message(content=f"❌ 文件处理失败：{str(e)}").send()


# ============= Action 回调处理 =============

@cl.action_callback("confirm_fill")
async def on_confirm_fill(action: cl.Action):
    """处理确认填充按钮点击"""
    logger.info("[confirm_fill] 收到确认填充回调")
    user_session = cl.user_session.get("user_session")
    
    # 获取映射结果和原始数据
    mapping_data = user_session.get("last_mapping_data")
    decoded_data = user_session.get("decoded_data")
    
    logger.info(f"[confirm_fill] mapping_data: {type(mapping_data)}, 长度: {len(mapping_data) if mapping_data else 0}")
    logger.info(f"[confirm_fill] decoded_data: {type(decoded_data)}, 是否有数据: {bool(decoded_data)}")
    
    if not mapping_data:
        logger.warning("[confirm_fill] 没有映射结果")
        await cl.Message(content="❌ 没有可用的映射结果，请先执行字段映射").send()
        return
    
    if not decoded_data:
        logger.warning("[confirm_fill] 没有原始数据")
        await cl.Message(content="❌ 没有可用的原始数据，请先上传文件").send()
        return
    
    await cl.Message(content="⏳ **正在执行填充操作...**").send()
    
    try:
        # 导入字段映射处理器
        from src.field_mapping_handler import get_field_mapping_handler
        
        handler = get_field_mapping_handler()
        
        # 应用字段映射
        logger.info("[confirm_fill] 开始应用字段映射")
        updated_config, updated_count = handler.apply_field_mapping(decoded_data, mapping_data)
        logger.info(f"[confirm_fill] 字段映射完成，更新数量: {updated_count}")
        
        if updated_count == 0:
            await cl.Message(content="⚠️ 没有找到需要更新的字段").send()
            return
        
        # 导出为 Base64
        logger.info("[confirm_fill] 开始导出Base64")
        base64_result = handler.export_to_base64(updated_config)
        logger.info(f"[confirm_fill] Base64导出完成，长度: {len(base64_result)}")
        
        # 保存更新后的配置
        user_session["updated_config"] = updated_config
        
        # 发送成功消息
        success_msg = f"""✅ **填充完成！**

📊 **更新统计：**
- 更新字段数：{updated_count} 个

💾 **输出选项：**
- 点击下方按钮下载 Base64 编码结果"""
        logger.info(f"[confirm_fill] 发送成功消息: {success_msg[:50]}...")
        await cl.Message(content=success_msg).send()
        
        # 发送可下载的 Base64 文件
        file_content = base64_result.encode('utf-8')
        logger.info(f"[confirm_fill] 创建File元素, 大小: {len(file_content)} bytes")
        
        base64_file = cl.File(
            name="filled_config.txt",
            content=file_content,
        )
        
        logger.info("[confirm_fill] 发送文件消息")
        await cl.Message(
            content="**📥 点击下载填充后的配置：**",
            elements=[base64_file]
        ).send()
        
        logger.info("[confirm_fill] 完成")
        
    except Exception as e:
        logger.error(f"填充操作异常: {str(e)}")
        import traceback
        logger.error(f"详细错误: {traceback.format_exc()}")
        await cl.Message(content=f"❌ 填充失败：{str(e)}").send()


# ============= 用户消息处理 =============

async def handle_user_message(user_session: dict, team, user_text: str):
    """处理用户消息 - 纯UI层，传递给Team处理"""
    user_lower = user_text.lower()
    
    # 检查是否有解码数据
    has_data = user_session.get("decoded_data") or user_session.get("decoded_fields")
    
    # 构建用户输入
    if has_data:
        # 使用简化 JSON 而不是完整 JSON
        simplified_data = user_session.get("simplified_data", {})
        simplified_json_str = json.dumps(simplified_data, ensure_ascii=False)
        
        full_input = f"""用户请求：{user_text}

字段列表（简化JSON）：
{simplified_json_str}

请根据用户请求处理。"""
        
        # 记录发送给 LLM 的数据
        logger.info(f"[LLM_INPUT] 发送给LLM的数据: {simplified_json_str[:500]}...")
    else:
        # 无数据时，直接传递用户输入
        full_input = user_text
    
    # 调用Team处理（创建loading提示消息）
    loading_msg = cl.Message(content="⏳ **AI正在处理中，请稍候...**\n\n💭 正在分析您的请求...")
    await loading_msg.send()
    
    try:
        # 使用Team处理（记录API响应时间）
        import asyncio
        import time
        api_start_time = time.time()
        logger.info(f"[API] 开始调用 Team.run，输入长度: {len(full_input)}")
        
        result = await asyncio.to_thread(team.run, full_input)
        
        api_end_time = time.time()
        api_duration = api_end_time - api_start_time
        logger.info(f"[API] Team.run 完成，耗时: {api_duration:.2f}秒")
        
        # 删除loading消息
        await loading_msg.remove()
        
        # 创建流式消息显示结果
        msg = cl.Message(content="")
        await msg.send()
        
        # 提取内容
        result_content = result.content if hasattr(result, 'content') else str(result)
        
        # 检查是否是字段映射请求
        is_mapping_request = any(keyword in user_lower for keyword in ["映射", "字段", "map"])
        
        if is_mapping_request:
            # 尝试解析JSON映射结果
            mapping_data = parse_json_mapping_result(result_content)
            
            if mapping_data:
                # 保存映射结果
                user_session["last_mapping_data"] = mapping_data
                
                # 统计信息
                matched_count = sum(1 for item in mapping_data if item.get("匹配状态") == "匹配成功")
                unmatched_count = len(mapping_data) - matched_count
                
                # 准备摘要
                summary = f"""✅ **字段映射完成！**

📊 **映射统计：**
- 总字段数：{len(mapping_data)}
- 匹配成功：{matched_count} 个
- 未匹配：{unmatched_count} 个

✨ **表格功能：**
- 📌 点击列标题排序
- 🔍 使用搜索框筛选
- ✏️ 点击单元格编辑系统属性名称
- 📥 导出CSV文件"""

                # 流式输出摘要
                for i in range(0, len(summary), 50):
                    chunk = summary[i:i+50]
                    await msg.stream_token(chunk)
                
                await msg.update()
                
                # 创建Dataframe表格元素
                elements = create_dataframe_elements(mapping_data)
                
                # 发送Dataframe表格
                if elements:
                    table_msg = cl.Message(
                        content="**📋 字段映射表：**\n\n请确认映射结果，点击下方按钮填充到原始数据中。",
                        elements=elements,
                        actions=[
                            cl.Action(name="confirm_fill", label="✅ 确认填充", description="确认后将映射结果填充到原始数据", payload={})
                        ]
                    )
                    await table_msg.send()
                
                return
        
        # 非映射请求，直接流式输出
        for i in range(0, len(result_content), 50):
            chunk = result_content[i:i+50]
            await msg.stream_token(chunk)
        
        await msg.update()
        
    except Exception as e:
        logger.error(f"Team调用异常: {str(e)}")
        # 删除loading消息
        try:
            await loading_msg.remove()
        except:
            pass
        await cl.Message(content=f"❌ 处理异常：{str(e)}").send()


async def send_action_buttons(msg, mapping_data: list):
    """发送操作按钮消息"""
    import pandas as pd
    
    # 创建Excel文件
    df = pd.DataFrame(mapping_data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='字段映射表', index=False)
    excel_data = output.getvalue()
    
    # 创建CSV文件
    csv_content = df.to_csv(index=False, encoding='utf-8-sig')
    csv_bytes = csv_content.encode('utf-8-sig')
    
    # 保存到会话中供下载
    user_session = cl.user_session.get("user_session")
    user_session["excel_data"] = excel_data
    user_session["excel_filename"] = f"字段映射表_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    # 发送Excel下载按钮
    excel_file = cl.File(
        name=user_session["excel_filename"],
        content=excel_data,
    )
    
    # 发送JSON复制内容
    json_str = json.dumps(mapping_data, ensure_ascii=False, indent=2)
    json_file = cl.File(
        name="映射结果.json",
        content=json_str.encode('utf-8'),
    )
    
    # 发送操作提示和下载元素
    action_msg = cl.Message(
        content="""
---

**📋 操作选项：**

- 📥 **下载 Excel** - 导出映射表为Excel文件
- 📋 **下载 JSON** - 复制映射结果为JSON格式
- 🔢 **复制内容** - 直接复制下方JSON字符串
""",
        elements=[excel_file, json_file]
    )
    await action_msg.send()
    
    # 发送可复制的JSON内容
    json_msg = cl.Message(
        content=f"```json\n{json_str}\n```"
    )
    await json_msg.send()
