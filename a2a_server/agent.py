import base64
import logging
import os
import re
import requests
import json
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath
from collections.abc import AsyncIterable
from io import BytesIO
from typing import Any, Optional
from uuid import uuid4

from PIL import Image
from dotenv import load_dotenv
from pydantic import BaseModel
import dashscope
from http import HTTPStatus
from dashscope import ImageSynthesis
import os
from urllib.parse import urlparse, unquote
from pathlib import PurePosixPath

load_dotenv()

logger = logging.getLogger(__name__)


class Imagedata(BaseModel):
    """Represents image data.

    Attributes:
      id: Unique identifier for the image.
      name: Name of the image.
      mime_type: MIME type of the image.
      bytes: Base64 encoded image data.
      url: URL of the generated image (新增字段).
      error: Error message if there was an issue with the image.
    """

    id: str | None = None
    name: str | None = None
    mime_type: str | None = None
    bytes: str | None = None
    url: str | None = None  # 新增URL字段
    error: str | None = None


class SimpleQwenClient:
    """简单的千问API客户端，用于文本生成"""

    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv('QWEN_API_KEY')
        if not self.api_key:
            raise ValueError("QWEN_API_KEY environment variable not set")

        self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        self.model = "qwen-plus"

    def generate_text(self, prompt, max_tokens=500):
        """调用千问文本生成API"""
        url = f"{self.base_url}/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }

        data = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "你是一个专业的图像生成助手。你的任务是分析用户的需求并生成合适的图像描述。直接返回图像描述即可，不需要其他内容。"
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "max_tokens": max_tokens,
            "temperature": 0.7
        }

        try:
            response = requests.post(url, headers=headers, json=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            print(f"📊 Text API Response: {json.dumps(result, ensure_ascii=False)[:200]}...")

            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"]["content"]
                # 清理内容，移除可能的多余描述
                content = content.strip()
                # 移除开头的"图像描述："等前缀
                for prefix in ["图像描述：", "图片描述：", "描述：", "生成的图像描述："]:
                    if content.startswith(prefix):
                        content = content[len(prefix):].strip()
                return content
            else:
                raise ValueError(f"Unexpected response format: {result}")

        except Exception as e:
            logger.error(f"Error calling Qwen text API: {e}")
            print(f"❌ Error calling Qwen text API: {e}")
            # 如果文本API失败，返回原始提示词
            return prompt


def download_image_from_url(image_url: str) -> bytes:
    """Download image from URL and return bytes."""
    try:
        print(f"⬇️ Downloading image from URL: {image_url}")
        response = requests.get(image_url, timeout=60)  # 增加超时时间
        response.raise_for_status()
        content_length = len(response.content)
        print(f"✅ Downloaded {content_length} bytes")
        return response.content
    except Exception as e:
        logger.error(f"Failed to download image from {image_url}: {e}")
        raise


class ImageGenerationAgent:
    """简化的Agent，直接调用千问API生成图像"""

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain', 'image/png']

    def __init__(self):
        # 初始化缓存
        from a2a_server.in_memory_cache import InMemoryCache
        self.cache = InMemoryCache()

        # 初始化千问客户端
        self.qwen_client = SimpleQwenClient()

        # 设置DashScope
        dashscope.base_http_api_url = 'https://dashscope.aliyuncs.com/api/v1'

        print("✅ ImageGenerationAgent initialized with Qwen")

    def extract_artifact_file_id(self, query):
        try:
            pattern = r'(?:id|artifact-file-id)\s+([0-9a-f]{32})'
            match = re.search(pattern, query)

            if match:
                return match.group(1)
            return None
        except Exception:
            return None

    def invoke(self, query, session_id) -> dict:
        """直接处理用户查询并生成图像，返回包含图片URL的字典"""
        print(f"📝 Received query: {query}")
        print(f"📝 Session ID: {session_id}")

        # 提取artifact_file_id
        artifact_file_id = self.extract_artifact_file_id(query)
        print(f"📝 Artifact file ID: {artifact_file_id}")

        try:
            # 调用千问文本API来分析用户需求
            analysis_prompt = f"""
            用户要求: {query}

            请分析这个图像生成请求，并生成一个适合用于图像生成的详细描述。
            考虑以下因素：
            1. 图像的主题和主要内容
            2. 颜色、风格和氛围
            3. 构图和视角
            4. 任何特殊要求

            请只返回图像描述，不要添加其他内容。直接描述图像即可。
            """

            print("🤔 Analyzing user request with Qwen...")
            image_description = self.qwen_client.generate_text(analysis_prompt)
            print(f"📋 Generated image description: {image_description}")

            # 调用千问图像生成API
            return self._generate_image(image_description, session_id)

        except Exception as e:
            print(f"❌ Error in invoke: {e}")
            # 如果文本生成失败，直接使用原始查询
            return self._generate_image(query, session_id)

    def _generate_image(self, prompt: str, session_id: str) -> dict:
        """生成图像的核心方法，返回包含状态、URL和错误信息的字典"""
        try:
            from dashscope import ImageSynthesis
            from http import HTTPStatus

            qwen_api_key = os.getenv('QWEN_API_KEY')
            if not qwen_api_key:
                raise ValueError("QWEN_API_KEY not set")

            print(f"🖼️ Generating image with description: {prompt[:100]}...")

            # 调用图像生成API
            rsp = ImageSynthesis.call(
                api_key=qwen_api_key,
                model="qwen-image-plus",
                prompt=prompt,
                n=1,
                size='1472*1140',
                prompt_extend=True,
                watermark=False
            )

            print(f"📡 Qwen API Response Status: {rsp.status_code}")

            if rsp.status_code == HTTPStatus.OK:
                # 检查输出结果
                if not hasattr(rsp, 'output') or not rsp.output:
                    print("❌ API returned success but output is empty")
                    return {
                        "status": "error",
                        "error": "API returned success but output is empty",
                        "image_url": None
                    }

                if not hasattr(rsp.output, 'results') or not rsp.output.results:
                    print("❌ API returned success but results list is empty")
                    return {
                        "status": "error",
                        "error": "API returned success but results list is empty",
                        "image_url": None
                    }

                # 获取第一个结果
                result = rsp.output.results[0]

                if not hasattr(result, 'url') or not result.url:
                    print("❌ Result has no URL")
                    return {
                        "status": "error",
                        "error": "Result has no URL",
                        "image_url": None
                    }

                image_url = result.url
                print(f"✅ Image generated successfully. URL: {image_url}")

                try:
                    # 下载图片
                    image_bytes = download_image_from_url(image_url)

                    # 转换为base64
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')

                    # 获取原始文件名
                    file_name = PurePosixPath(unquote(urlparse(image_url).path)).parts[-1]
                    if not file_name or not file_name.endswith(('.png', '.jpg', '.jpeg')):
                        file_name = 'generated_image.png'

                    # 创建图片数据对象，包含URL
                    data = Imagedata(
                        bytes=image_base64,
                        mime_type='image/png',
                        name=file_name,
                        id=uuid4().hex,
                        url=image_url  # 保存URL
                    )

                    # 保存到缓存
                    session_data = self.cache.get(session_id)
                    if session_data is None:
                        # Session doesn't exist, create it with the new item
                        self.cache.set(session_id, {data.id: data})
                    else:
                        # Session exists, update the existing dictionary directly
                        session_data[data.id] = data

                    print(f"✅ Image saved to cache with ID: {data.id}")

                    # 返回成功结果，包含图片URL
                    return {
                        "status": "success",
                        "image_id": data.id,
                        "image_url": image_url,
                        "error": None
                    }

                except Exception as download_error:
                    print(f"❌ Error downloading image: {download_error}")
                    return {
                        "status": "error",
                        "error": f"Error downloading image: {download_error}",
                        "image_url": None
                    }

            else:
                error_msg = f"Qwen image generation failed: status_code={rsp.status_code}, code={rsp.code}, message={rsp.message}"
                print(f"❌ {error_msg}")
                return {
                    "status": "error",
                    "error": error_msg,
                    "image_url": None
                }

        except Exception as e:
            error_msg = f"Error generating image: {type(e).__name__}: {str(e)}"
            print(f"❌ {error_msg}")
            import traceback
            traceback.print_exc()
            return {
                "status": "error",
                "error": error_msg,
                "image_url": None
            }

    async def stream(self, query: str) -> AsyncIterable[dict[str, Any]]:
        """Streaming is not supported."""
        raise NotImplementedError('Streaming is not supported.')

    def get_image_data(self, session_id: str, image_key: str) -> Imagedata:
        """Return Imagedata given a key."""
        session_data = self.cache.get(session_id)
        try:
            if session_data and image_key in session_data:
                return session_data[image_key]
            else:
                print(f"❌ Image key {image_key} not found in session {session_id}")
                return Imagedata(error='Error retrieving image, please try again.')
        except Exception as e:
            print(f"❌ Error getting image data: {e}")
            return Imagedata(error='Error retrieving image data.')