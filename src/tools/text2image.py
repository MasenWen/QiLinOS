import asyncio
import base64
import json
import os
import urllib

from uuid import uuid4

import asyncclick as click
import httpx

from a2a.client import A2ACardResolver, Client
from a2a.extensions.common import HTTP_EXTENSION_HEADER
from a2a.types import (
    Part,
    FileWithBytes,
    GetTaskRequest,
    JSONRPCErrorResponse,
    Message,
    MessageSendConfiguration,
    MessageSendParams,
    Part,
    SendMessageRequest,
    SendStreamingMessageRequest,
    Task,
    TaskArtifactUpdateEvent,
    TaskQueryParams,
    TaskState,
    TaskStatusUpdateEvent,
    TextPart,
)

import re
import requests
import subprocess
import time
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from .decorators import log_io
import logging
from typing import Annotated
import os
from src.utils.db_manager import node_state
from src.utils.file_process import make_safe_filename, remove_uploads_prefix
from src.utils.db_manager import log_handler, node_state
import os
from src.utils.msg_process import resolve_file_path


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)

UPLOAD_DIR = "./uploads"

def get_image_path():
    save_path = os.path.join(UPLOAD_DIR, str(node_state))
    os.makedirs(save_path, exist_ok=True)

    original_filename = "image.png"
    # 核心修复：安全文件名由 “安全化后的主文件名 + 原扩展名/猜测扩展名” 组成
    stored_filename = make_safe_filename(original_filename, 'image/png', save_path)
    save_path = os.path.join(save_path, stored_filename)
    return save_path



def download_image_requests(url, save_path):
    """
    使用requests库下载图片
    
    Args:
        url (str): 图片URL
        save_path (str): 保存路径，例如：'./images/image.png'
    """
    try:
        # 创建目录（如果不存在）
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        # 发送GET请求
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()  # 检查请求是否成功
        
        # 保存图片
        with open(save_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        print(f"图片已成功下载到: {save_path}")
        print(f"文件大小: {os.path.getsize(save_path)} 字节")
        return save_path
        
    except requests.exceptions.RequestException as e:
        print(f"下载失败: {e}")
        return None
    except Exception as e:
        print(f"发生错误: {e}")
        return None

async def text_gen_image(prompt, path):
    agent = "http://localhost:50076"
    bearer_token = None
    header = ()
    session = 0
    history = False
    enabled_extensions = ""
    headers = {h.split('=')[0]: h.split('=')[1] for h in header}
    if bearer_token:
        headers['Authorization'] = f'Bearer {bearer_token}'

    # --- Add enabled_extensions support ---
    # If the user provided a comma-separated list of extensions,
    # we set the X-A2A-Extensions header.
    # This allows the server to know which extensions are activated.
    # Note: We assume the extensions are supported by the server.
    # This headers will be used by the server to activate the extensions.
    # If the server does not support the extensions, it will ignore them.
    if enabled_extensions:
        ext_list = [
            ext.strip() for ext in enabled_extensions.split(',') if ext.strip()
        ]
        if ext_list:
            headers[HTTP_EXTENSION_HEADER] = ', '.join(ext_list)
    print(f'Will use headers: {headers}')
    async with httpx.AsyncClient(timeout=30, headers=headers) as httpx_client:
        card_resolver = A2ACardResolver(httpx_client, agent)
        card = await card_resolver.get_agent_card()

        print('======= Agent Card ========')
        logger.info(f"{node_state}-=-图片制作员===A2A：{card.model_dump_json(exclude_none=True)}")

        client = Client(httpx_client, agent_card=card)


        streaming = card.capabilities.streaming
        context_id = session if session > 0 else uuid4().hex


        image_url = await completeTask(client, prompt, streaming, None, context_id,
            )
        if path == None:
            path = get_image_path()

        return download_image_requests(image_url, path)



async def completeTask(
    client: Client,
    prompt,
    streaming,
    task_id,
    context_id,
):


    message = Message(
        role='user',
        parts=[TextPart(text=prompt)],
        message_id=str(uuid4()),
        task_id=task_id,
        context_id=context_id,
    )

    file_path = ''
    if file_path and file_path.strip() != '':
        with open(file_path, 'rb') as f:
            file_content = base64.b64encode(f.read()).decode('utf-8')
            file_name = os.path.basename(file_path)

        message.parts.append(
            Part(
                root=FilePart(
                    file=FileWithBytes(name=file_name, bytes=file_content)
                )
            )
        )

    payload = MessageSendParams(
        id=str(uuid4()),
        message=message,
        configuration=MessageSendConfiguration(
            accepted_output_modes=['text'],
        ),
    )

   

    taskResult = None
    message = None
    task_completed = False
    if streaming:
        response_stream = client.send_message_streaming(
            SendStreamingMessageRequest(
                id=str(uuid4()),
                params=payload,
            )
        )
        async for result in response_stream:
            if isinstance(result.root, JSONRPCErrorResponse):
                print(
                    f'Error: {result.root.error}, context_id: {context_id}, task_id: {task_id}'
                )
                return ""
            event = result.root.result
            context_id = event.context_id
            if isinstance(event, Task):
                task_id = event.id
            elif isinstance(event, TaskStatusUpdateEvent) or isinstance(
                event, TaskArtifactUpdateEvent
            ):
                task_id = event.task_id
                if (
                    isinstance(event, TaskStatusUpdateEvent)
                    and event.status.state == 'completed'
                ):
                    task_completed = True
            elif isinstance(event, Message):
                message = event
            print(f'stream event => {event.model_dump_json(exclude_none=True)}')
        # Upon completion of the stream. Retrieve the full task if one was made.
        if task_id and not task_completed:
            taskResultResponse = await client.get_task(
                GetTaskRequest(
                    id=str(uuid4()),
                    params=TaskQueryParams(id=task_id),
                )
            )
            if isinstance(taskResultResponse.root, JSONRPCErrorResponse):
                print(
                    f'Error: {taskResultResponse.root.error}, context_id: {context_id}, task_id: {task_id}'
                )
                return ""
            taskResult = taskResultResponse.root.result
    else:
        try:
            # For non-streaming, assume the response is a task or message.
            event = await client.send_message(
                SendMessageRequest(
                    id=str(uuid4()),
                    params=payload,
                )
            )
            event = event.root.result
        except Exception as e:
            print('Failed to complete the call', e)
        if not context_id:
            context_id = event.context_id
        if isinstance(event, Task):
            if not task_id:
                task_id = event.id
            taskResult = event
        elif isinstance(event, Message):
            message = event

    if message:
        return ""
    if taskResult:
        # Don't print the contents of a file.
        task_content = taskResult.model_dump_json(
            exclude={
                'history': {
                    '__all__': {
                        'parts': {
                            '__all__': {'file'},
                        },
                    },
                },
            },
            exclude_none=True,
        )
        result = json.loads(task_content)
        image_url = result["artifacts"][0]["parts"][0]["text"]
        ## if the result is that more input is required, loop again.
        state = TaskState(taskResult.status.state)
        if state.name == TaskState.input_required.name:
            return await completeTask(
                client,
                streaming,
                task_id,
                context_id,
            )
        ## task is complete
        return image_url
    ## Failure case, shouldn't reach
    return ""




@tool
@log_io
def gen_image_tool(prompt: Annotated[str, "prompt to generate image"], path: Annotated[str, "path to save image"]) -> HumanMessage:
    """
    调用多模态大模型生成图片
    """
    path = str(resolve_file_path(path))
    image_path = asyncio.run(text_gen_image(prompt, path))
    if image_path:
        print(f"生成图片：{image_path}")
        #![AI生成图片](/api/download/{remove_uploads_prefix(image_path)})
        #<img class="chat-image" alt="image.png" loading="lazy" referrerpolicy="no-referrer" 
        # if "/uploads/" in image_path:
        #     return HumanMessage(content=f"已按要求生成图片,保存路径为：{image_path}，预览图如下：\n<img class=\"chat-image\" alt=\"{image_path}\"  src=\"/api/download/{remove_uploads_prefix(image_path)}\">")
        # else:
        # return HumanMessage(content=f"已按要求生成图片，保存路径为: {image_path}\n预览图如下：\n<img class=\"chat-image\" alt=\"{image_path}\" src=\"{image_path}\">")
        return HumanMessage(content=f"已按要求生成图片，保存路径为: {image_path}\n")
    else:
        return HumanMessage(content=f"生成图片失败，请检查网络或模型配置")



