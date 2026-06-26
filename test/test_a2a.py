import asyncio
import base64
import json
import os
import urllib

from uuid import uuid4

import asyncclick as click
import httpx

from a2a.client import A2ACardResolver, A2AClient
from a2a.extensions.common import HTTP_EXTENSION_HEADER
from a2a.types import (
    FilePart,
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





async def text_gen_image(prompt = "帮我生成一张小猫在河边的青草地上钓鱼，旁边的蝴蝶蜻蜓在飞，阳光明媚，小花绽放"):
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
        print(card.model_dump_json(exclude_none=True))

        client = A2AClient(httpx_client, agent_card=card)


        streaming = card.capabilities.streaming
        context_id = session if session > 0 else uuid4().hex


        continue_loop, _, task_id = await completeTask(client, prompt, streaming, None, context_id,
            )



async def completeTask(
    client: A2AClient,
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
                return False, context_id, task_id
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
                return False, context_id, task_id
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
        print(f'\n{message.model_dump_json(exclude_none=True)}')
        return True, context_id, task_id
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
        print(f'\n最终结果{result["artifacts"][0]["parts"][0]["text"]}')
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
        return True, context_id, task_id
    ## Failure case, shouldn't reach
    return True, context_id, task_id



if __name__ == '__main__':
    asyncio.run(text_gen_image())
