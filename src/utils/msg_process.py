
import re
import json
from pydantic import BaseModel, Field
from typing import Dict, Any, Literal, Union
from typing_extensions import TypedDict
from src.agent.llm import get_llm_by_type
import logging
from src.utils.db_manager import log_handler
from werkzeug.utils import secure_filename
from flask import send_from_directory
import uuid
import os
from urllib.parse import quote
from pathlib import Path

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

def extract_response_content(text):
    """
    提取<response></response>标签之间的内容
    
    Args:
        text (str): 包含response标签的文本
        
    Returns:
        str: response标签之间的内容，如果未找到则返回空字符串
    """
    # 使用正则表达式匹配<response>和</response>之间的内容
    pattern = r'<response>(.*?)</response>'
    match = re.search(pattern, text, re.DOTALL)
    
    if match:
        return match.group(1).strip()
    else:
        return text
    
def find_json_objects(text):
    """
    使用栈平衡方法找到完整的 JSON 对象
    """
    json_objects = []
    start = -1
    brace_count = 0
    bracket_count = 0
    in_string = False
    escape_next = False
    
    for i, char in enumerate(text):
        if not in_string:
            if char == '{':
                if brace_count == 0 and bracket_count == 0:
                    start = i
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0 and bracket_count == 0 and start != -1:
                    # 找到完整的 JSON 对象
                    json_str = text[start:i+1]
                    try:
                        json.loads(json_str)
                        print("----------josn-------------")
                        if "\"steps\":" in json_str:
                            print(parse_workflow_json(json_str))
                        else:
                            print(json_str)
                        json_objects.append(json_str)
                        
                        start = -1
                    except json.JSONDecodeError:
                        continue
            elif char == '[':
                if brace_count == 0 and bracket_count == 0:
                    start = i
                bracket_count += 1
            elif char == ']':
                bracket_count -= 1
                if brace_count == 0 and bracket_count == 0 and start != -1:
                    # 找到完整的 JSON 数组
                    json_str = text[start:i+1]
                    try:
                        json.loads(json_str)
                        json_objects.append(json_str)
                        start = -1
                    except json.JSONDecodeError:
                        continue
            elif char == '"' and not escape_next:
                in_string = True
        else:
            if char == '"' and not escape_next:
                in_string = False
            elif char == '\\' and not escape_next:
                escape_next = True
                continue
        
        escape_next = False
    
    return json_objects

class FeedbackDecision(TypedDict):
    """用户反馈决策的标准化格式"""
    action: Literal["同意", "拒绝", "修改"] = Field(
        description="用户决策：接受、拒绝或修改计划"
    )
    modification_content: Union[str, None] = Field(
        default=None,
        description="如果用户选择修改，这里是修改的具体内容。如果没有修改，则为None"
    )
    confidence: float = Field(
        default=1.0,
        description="解析的置信度，0-1之间的数值"
    )
    reasoning: Union[str, None] = Field(
        default=None,
        description="解析用户意图的推理过程"
    )
    
def extract_modification_content(user_input: str, keyword: str) -> str:
    """从用户输入中提取修改内容"""
    # 尝试多种分隔符
    separators = [':', '：', '为', '是', '要']
    
    for sep in separators:
        if sep in user_input:
            parts = user_input.split(sep, 1)
            if len(parts) > 1:
                return parts[1].strip()
    
    # 如果有关键词，尝试在关键词后截取
    keyword_index = user_input.lower().find(keyword)
    if keyword_index != -1:
        content_start = keyword_index + len(keyword)
        return user_input[content_start:].strip()
    
    return user_input

def fallback_parse(user_input: str) -> FeedbackDecision:
    """LLM解析失败时的回退方案"""
    user_input_lower = user_input.lower()
    
    # 简单的关键词匹配
    accept_keywords = ['1', '同意', '接受', '确认', '好的', '不错', '可以', '行', 'ok', 'yes', 'approve', 'accept']
    reject_keywords = ['2', '拒绝', '不同意', '不好', '不行', '不可以', 'no', 'reject']
    modify_keywords = ['3', '修改', '调整', '改变', '改一下', '改动', '修正','modify']
    
    for keyword in accept_keywords:
        if keyword in user_input_lower:
            return FeedbackDecision(
                action="同意",
                reasoning=f"检测到接受关键词: {keyword}",
                confidence=0.8
            )
    
    for keyword in reject_keywords:
        if keyword in user_input_lower:
            return FeedbackDecision(
                action="接受", 
                reasoning=f"检测到拒绝关键词: {keyword}",
                confidence=0.8
            )
    
    for keyword in modify_keywords:
        if keyword in user_input_lower:
            # 尝试提取修改内容
            content = extract_modification_content(user_input, keyword)
            return FeedbackDecision(
                action="修改",
                modification_content=content,
                reasoning=f"检测到修改关键词: {keyword}",
                confidence=0.7
            )
    
    # 默认视为修改（较长的输入通常包含具体意见）
    if len(user_input) > 10:
        return FeedbackDecision(
            action="修改",
            modification_content=user_input,
            reasoning="输入内容较长，推测为具体修改意见",
            confidence=0.6
        )
    
    # 很短且不明确的输入视为接受
    return FeedbackDecision(
        action="同意",
        reasoning="输入内容简短且不明确，默认接受",
        confidence=0.5
    )


def parse_user_feedback_with_llm(user_input: str) -> FeedbackDecision:
    """
    使用大模型解析用户的自然语言反馈，返回标准化的JSON格式
    
    Args:
        user_input: 用户输入的自然语言文本
        
    Returns:
        FeedbackDecision: 标准化的反馈决策
    """
    try:
        # 使用基础LLM来解析用户反馈
        llm = get_llm_by_type("basic")
        
        # 构建解析提示
        prompt = f"""
请分析以下用户对计划的反馈，并将其解析为标准格式。

用户反馈: "{user_input}"

请根据用户的意图，确定反馈类型：
- 如果用户同意、接受、确认计划，选择 同意
- 如果用户拒绝、否定、不同意计划，选择 拒绝  
- 如果用户提出修改、调整、完善意见，选择 修改

如果是 修改 类型，请在 modification_content 中提取用户的具体修改要求。
请提供解析的推理过程和置信度。

请以JSON格式返回结果，包含以下字段：
- action: "同意", "拒绝" 或 "修改"
- modification_content: 修改内容（如果action是修改，否则为无）
- confidence: 置信度（0-1）
- reasoning: 解析推理过程

只返回JSON格式的结果，不要有其他文本。
"""
        
        # 使用结构化输出获取解析结果
        
        response = llm.with_structured_output(FeedbackDecision).invoke(prompt)
        print(response)
        return response
        
    except Exception as e:
        logger.error(f"LLM解析用户反馈失败: {e}")
        # 失败时回退到简单的规则匹配
        return fallback_parse(user_input)

def parse_plan_json(json_str):
    """
    解析工作流程JSON字符串并规范化为指定格式的文本
    
    Args:
        json_str: JSON格式的字符串
        
    Returns:
        str: 规范化后的文本
    """
    try:
        # 解析JSON字符串
        data = json.loads(json_str)
        
        # 构建规范化文本
        result = []
        
        # 添加思考部分
        if "thought" in data:
            result.append(f"### 思考: \n{data['thought']}\n<br>")
        
        # 添加计划主题部分
        if "title" in data:
            result.append(f"### 计划主题: \n{data['title']}\n<br>")
        
        # 添加步骤部分
        if "steps" in data and isinstance(data["steps"], list):
            result.append("### 步骤: \n")
            for i, step in enumerate(data["steps"], 1):
                step_text = f"**步骤{i}**：{step.get('agent_name', '')}，{step.get('title', '')}。{step.get('description', '').replace('~/nex-agent-output', '$HOME/nex-agent-output')}"
                
                # 添加注意信息
                if step.get('note'):
                    step_text += f"  __注意__，{step['note']}"
                
                result.append(step_text)
        
        return "\n".join(result)
    
    except json.JSONDecodeError as e:
        return f"JSON解析错误: {e}"
    except Exception as e:
        return f"处理过程中发生错误: {e}"


UPLOAD_DIR = "./uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def safe_filename(filename):
    """保留中文等字符的安全文件名处理"""
    # 提取文件名和扩展名
    name, ext = os.path.splitext(filename)
    
    # 只保留安全的字符：中文、字母、数字、下划线、点、连字符
    # 移除可能危险的字符
    safe_name = re.sub(r'[^\w\u4e00-\u9fff\-\.]', '_', name)
    
    # 如果处理后名称为空，使用UUID
    if not safe_name or safe_name == '_':
        safe_name = uuid.uuid4().hex
    
    return safe_name + ext.lower()

def parse_coder_json(json_str):
    """
    解析工作流程JSON字符串并规范化为指定格式的文本
    
    Args:
        json_str: JSON格式的字符串
        
    Returns:
        str: 规范化后的文本
    """
    try:
        # 解析JSON字符串
        data = json.loads(json_str)
        
        # 构建规范化文本
        result = []
        
        # 添加思考部分
        if "conclusion" in data:
            result.append(f"### 结果:\n{data['conclusion']}\n<br>")
        
        # 添加计划主题部分
        if "process" in data:
            result.append(f"### 过程: \n{data['process']}\n<br>")
        
        # 添加步骤部分
        if "files" in data and isinstance(data["files"], list):
            result.append("### 附件: \n")
            for i, step in enumerate(data["files"], 1):
                file_path = step.get('file_path', None) 
                resolved_path = resolve_file_path(file_path)
                if resolved_path and resolved_path.exists():
                    original_filename = step.get('file_name', 'unnamed') 
                    # stored_filename = secure_filename(original_filename)
                    stored_filename = safe_filename(original_filename)

                        
                    # if not stored_filename or stored_filename.startswith('.'):
                    #     ext = os.path.splitext(original_filename)[1]
                    #     stored_filename = f"{uuid.uuid4().hex}{ext}"
                    
                    save_path = os.path.join(UPLOAD_DIR, stored_filename)
                    # 复制文件到上传目录
                    with open(resolved_path, 'rb') as src_file:
                        with open(save_path, 'wb') as dest_file:
                            dest_file.write(src_file.read())
                    
                    encoded_original = quote(original_filename)
                    href = f"/api/download/{encoded_original}"
                    # href = f"/api/download/{stored_filename}"
                    size = os.path.getsize(resolved_path)
                    content = f"📦 [**{original_filename}**]({href}) · {size / 1024:.1f} KB\n"
                    result.append(content)
        return "\n".join(result)
    
    except json.JSONDecodeError as e:
        return f"JSON解析错误: {e}"
    except Exception as e:
        return f"处理过程中发生错误: {e}"

def find_json_objects_with_indices(text):
        """
        使用栈平衡方法找到完整的JSON对象及其位置
        """
        json_objects = []
        start = -1
        brace_count = 0
        bracket_count = 0
        in_string = False
        escape_next = False
        
        for i, char in enumerate(text):
            if not in_string:
                if char == '{':
                    if brace_count == 0 and bracket_count == 0:
                        start = i
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0 and bracket_count == 0 and start != -1:
                        # 找到完整的JSON对象
                        json_str = text[start:i+1]
                        try:
                            json.loads(json_str)  # 验证JSON格式
                            json_objects.append({
                                'json_str': json_str,
                                'start': start,
                                'end': i + 1
                            })
                            start = -1
                        except json.JSONDecodeError:
                            # JSON格式错误，继续寻找
                            continue
                elif char == '[':
                    if brace_count == 0 and bracket_count == 0:
                        start = i
                    bracket_count += 1
                elif char == ']':
                    bracket_count -= 1
                    if brace_count == 0 and bracket_count == 0 and start != -1:
                        # 找到完整的JSON数组
                        json_str = text[start:i+1]
                        try:
                            json.loads(json_str)
                            json_objects.append({
                                'json_str': json_str,
                                'start': start,
                                'end': i + 1
                            })
                            start = -1
                        except json.JSONDecodeError:
                            continue
                elif char == '"' and not escape_next:
                    in_string = True
            else:
                if char == '"' and not escape_next:
                    in_string = False
                elif char == '\\' and not escape_next:
                    escape_next = True
                    continue
            
            escape_next = False
        
        return json_objects

def get_plan_json(text):
    """
    找到文本中的JSON对象，将其替换为parse_workflow_json解析后的格式
    
    Args:
        text: 包含JSON对象的文本字符串
        
    Returns:
        str: 替换后的完整文本
    """
    

    # 找到所有JSON对象及其位置
    json_objects = find_json_objects_with_indices(text)
    
    if not json_objects:
        return text
    
    # 从后往前替换，避免索引变化问题
    result = text
    for obj_info in sorted(json_objects, key=lambda x: x['start'], reverse=True):
        json_str = obj_info['json_str']
        start = obj_info['start']
        end = obj_info['end']
        
        # 检查是否包含steps字段
        if "\"steps\":" in json_str:
            try:
                # 解析并格式化JSON
                parsed_text = parse_plan_json(json_str)
                # 替换原JSON字符串
                result = result[:start] + parsed_text + result[end:]
            except Exception as e:
                # 如果解析失败，保留原JSON字符串
                print(f"解析JSON失败: {e}")
                continue
            return json_str
        else:
            # 对于不包含steps的JSON，可以选择保留原样或进行其他处理
            # 这里我们保留原JSON字符串
            pass
    
    return text


def get_first_json(text):
    json_objects = find_json_objects_with_indices(text)
    
    if not json_objects:
        return {}
    else:
        return json.loads(json_objects[0]['json_str'])
    
def parse_planner_response(text):
    """
    找到文本中的JSON对象，将其替换为parse_planner_json解析后的格式
    
    Args:
        text: 包含JSON对象的文本字符串
        
    Returns:
        str: 替换后的完整文本
    """
    

    # 找到所有JSON对象及其位置
    json_objects = find_json_objects_with_indices(text)
    
    if not json_objects:
        return text
    
    # 从后往前替换，避免索引变化问题
    result = text
    for obj_info in sorted(json_objects, key=lambda x: x['start'], reverse=True):
        json_str = obj_info['json_str']
        # start = obj_info['start']
        # end = obj_info['end']
        
        # 检查是否包含steps字段
        if "\"steps\":" in json_str:
            try:
                # 解析并格式化JSON
                parsed_text = parse_plan_json(json_str)
                # 替换原JSON字符串
                result = parsed_text
            except Exception as e:
                # 如果解析失败，保留原JSON字符串
                print(f"解析JSON失败: {e}")
                continue
        else:
            # 对于不包含steps的JSON，可以选择保留原样或进行其他处理
            # 这里我们保留原JSON字符串
            pass
    
    return result



def resolve_file_path(file_path):
    """解析文件路径，处理 ~ 和相对路径"""
    if not file_path:
        return None
    
    # 使用 Path 自动处理 ~ 展开和相对路径解析
    path_obj = Path(file_path).expanduser().resolve()
    return path_obj

def extract_file_path(text):
    """
    改进版：更精确地匹配Unix风格文件路径
    
    参数:
        text: 包含文件路径的字符串
        
    返回:
        文件路径字符串，如果未找到则返回None
    """
    # Unix路径正则表达式：
    # 1. 可以以/开头（绝对路径）
    # 2. 可以包含字母、数字、下划线、连字符、点
    # 3. 必须包含文件扩展名（.后面跟着字母数字）
    # 4. 路径中可以包含多个目录层级（用/分隔）
    pattern = r'路径为：\s*((?:[^。/]+/)*[^。/]+\.\w+)'
    
    match = re.search(pattern, text)
    if match:
        return match.group(1)
    
    return None
    
def parse_filler_response(text):
    """
    找到文本中的路径，并添加相关附件
    
    Args:
        text: 文本字符串
        
    Returns:
        str: 替换后的完整文本
    """
    
    file_path = extract_file_path(text)
    if file_path != None:
        text += "\n\n附件: \n"
        resolved_path = resolve_file_path(file_path)
        if resolved_path and resolved_path.exists():
            original_filename = os.path.basename(file_path)

            stored_filename = safe_filename(original_filename)

            save_path = os.path.join(UPLOAD_DIR, stored_filename)
            # 复制文件到上传目录
            with open(resolved_path, 'rb') as src_file:
                with open(save_path, 'wb') as dest_file:
                    dest_file.write(src_file.read())
            
            encoded_original = quote(original_filename)
            href = f"/api/download/{encoded_original}"
   
            size = os.path.getsize(resolved_path)
            content = f"📦 [**{original_filename}**]({href}) · {size / 1024:.1f} KB\n"
            text += content
    
    return text

def parse_coder_response(text):
    """
    找到文本中的JSON对象，将其替换为parse_coder_json解析后的格式
    
    Args:
        text: 包含JSON对象的文本字符串
        
    Returns:
        str: 替换后的完整文本
    """
    

    # 找到所有JSON对象及其位置
    json_objects = find_json_objects_with_indices(text)
    
    if not json_objects:
        return text
    
    # 从后往前替换，避免索引变化问题
    result = text
    for obj_info in sorted(json_objects, key=lambda x: x['start'], reverse=True):
        json_str = obj_info['json_str']
        # start = obj_info['start']
        # end = obj_info['end']
        
        # 检查是否包含steps字段
        if "\"conclusion\":" in json_str:
            try:
                # 解析并格式化JSON
                parsed_text = parse_coder_json(json_str)
                # 替换原JSON字符串
                result = parsed_text
            except Exception as e:
                # 如果解析失败，保留原JSON字符串
                print(f"解析JSON失败: {e}")
                continue
        else:
            # 对于不包含steps的JSON，可以选择保留原样或进行其他处理
            # 这里我们保留原JSON字符串
            pass
    
    return result

def replace_string_pattern(input_str):
    """
    将类似 {'next': 'coder'} 的字符串替换为 "@coder"
    
    参数:
        input_str: 输入字符串
        
    返回:
        替换后的字符串
    """
    # 方法1: 使用正则表达式匹配模式
    pattern = r"\{'next':\s*'([^']+)'\}"
    
    def replace_match(match):
        value = match.group(1)
        return f"@{value}"
    
    # 使用正则替换
    result = re.sub(pattern, replace_match, input_str)
    
    return result   