from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.types import (
    FilePart,
    FileWithBytes,
    InvalidParamsError,
    Part,
    Task,
    TextPart,
    UnsupportedOperationError,
)
from a2a.utils import (
    completed_task,
    new_artifact,
)
from a2a.utils.errors import ServerError
from a2a_server.agent import ImageGenerationAgent  # 使用简化版本


class ImageGenerationAgentExecutor(AgentExecutor):
    """Image Generation AgentExecutor using Qwen models."""

    def __init__(self) -> None:
        self.agent = ImageGenerationAgent()

    async def execute(
            self,
            context: RequestContext,
            event_queue: EventQueue,
    ) -> None:
        error = self._validate_request(context)
        if error:
            raise ServerError(error=InvalidParamsError())

        query = context.get_user_input()
        print(f"📨 Received query: {query}")
        print(f"📦 Task ID: {context.task_id}")
        print(f"📦 Context ID: {context.context_id}")

        try:
            result = self.agent.invoke(query, context.context_id)
            print(f'📦 Agent Result: {result}')

            # 检查结果状态
            if result.get("status") == "error":
                error_msg = result.get("error", "Image generation failed")
                print(f'❌ {error_msg}')

                # 只返回文本部分，包含错误信息
                parts = [
                    Part(
                        root=TextPart(
                            text=f"图片生成失败: {error_msg}"
                        ),
                    )
                ]

                await event_queue.enqueue_event(
                    completed_task(
                        context.task_id,
                        context.context_id,
                        [new_artifact(parts, f'image_error_{context.task_id}')],
                        [context.message],
                    )
                )
                return

            elif result.get("status") == "success":
                image_id = result.get("image_id")
                image_url = result.get("image_url")

                print(f'✅ Image generated successfully. ID: {image_id}, URL: {image_url}')

                try:
                    data = self.agent.get_image_data(
                        session_id=context.context_id, image_key=image_id
                    )

                    if data and not data.error:
                        # 创建两个部分：文本部分（包含URL）和文件部分（图片数据）
                        parts = [
                            # 文本部分，包含图片URL
                            Part(
                                root=TextPart(
                                    text=f"{image_url}"
                                ),
                            ),
                            # 文件部分，包含图片数据
                            FilePart(
                                file=FileWithBytes(
                                    bytes=data.bytes,
                                    mime_type=data.mime_type,
                                    name=data.name or f"image_{image_id[:8]}.png",
                                )
                            )
                        ]
                        print(f'✅ Successfully generated image: {data.id}')
                    else:
                        error_msg = data.error if data else 'Failed to generate image'
                        print(f'❌ Image generation error: {error_msg}')
                        parts = [
                            Part(
                                root=TextPart(
                                    text=f"图片生成失败: {error_msg}"
                                ),
                            )
                        ]

                    await event_queue.enqueue_event(
                        completed_task(
                            context.task_id,
                            context.context_id,
                            [new_artifact(parts, f'image_{context.task_id}')],
                            [context.message],
                        )
                    )
                except Exception as e:
                    print(f'❌ Error processing image data: {e}')
                    raise ServerError(
                        error=ValueError(f'Error processing image data: {e}')
                    ) from e
            else:
                # 未知状态
                error_msg = f"Unknown result status: {result}"
                print(f'❌ {error_msg}')
                parts = [
                    Part(
                        root=TextPart(
                            text=f"图片生成失败: {error_msg}"
                        ),
                    )
                ]
                await event_queue.enqueue_event(
                    completed_task(
                        context.task_id,
                        context.context_id,
                        [new_artifact(parts, f'image_error_{context.task_id}')],
                        [context.message],
                    )
                )

        except Exception as e:
            print(f'❌ Error invoking agent: {e}')
            # 返回错误信息给客户端
            parts = [
                Part(
                    root=TextPart(
                        text=f"图片生成失败: {str(e)}"
                    ),
                )
            ]
            await event_queue.enqueue_event(
                completed_task(
                    context.task_id,
                    context.context_id,
                    [new_artifact(parts, f'image_error_{context.task_id}')],
                    [context.message],
                )
            )

    async def cancel(
            self, request: RequestContext, event_queue: EventQueue
    ) -> Task | None:
        raise ServerError(error=UnsupportedOperationError())

    def _validate_request(self, context: RequestContext) -> bool:
        # 验证请求
        if not context.get_user_input():
            print("❌ Empty user input")
            return True
        return False