"""This file serves as the main entry point for the application.

It initializes the A2A server, defines the agent's capabilities,
and starts the server to handle incoming requests.
"""

import logging
import os

import click

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentSkill,
)
from a2a_server.agent import ImageGenerationAgent  # 使用简化版本
from a2a_server.agent_executor import ImageGenerationAgentExecutor
from dotenv import load_dotenv


load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""


@click.command()
@click.option('--host', 'host', default='0.0.0.0')
@click.option('--port', 'port', default=50076)
def main(host, port):
    """Entry point for the A2A + CrewAI Image generation sample."""
    try:
        # 检查千问API Key
        if not os.getenv('QWEN_API_KEY'):
            raise MissingAPIKeyError(
                'QWEN_API_KEY environment variable not set. '
                'Please set it to use Qwen models.\n'
                'Get your API key from: https://help.aliyun.com/zh/model-studio/get-api-key'
            )

        print("🚀 Starting Image Generation Agent Server (Qwen)")
        print(f"🔧 Using Qwen API Key: {os.getenv('QWEN_API_KEY')[:10]}...")

        capabilities = AgentCapabilities(streaming=False)
        skill = AgentSkill(
            id='image_generator',
            name='Image Generator',
            description=(
                'Generate high-quality images using Qwen image generation models.'
            ),
            tags=['generate image', 'qwen', 'image generation'],
            examples=['Generate a photorealistic image of raspberry lemonade'],
        )

        agent_host_url = (
            os.getenv('HOST_OVERRIDE')
            if os.getenv('HOST_OVERRIDE')
            else f'http://{host}:{port}/'
        )
        agent_card = AgentCard(
            name='Image Generator Agent (Qwen)',
            description=(
                'Generate high-quality images using Qwen image generation models.'
            ),
            url=agent_host_url,
            version='1.0.0',
            default_input_modes=ImageGenerationAgent.SUPPORTED_CONTENT_TYPES,
            default_output_modes=ImageGenerationAgent.SUPPORTED_CONTENT_TYPES,
            capabilities=capabilities,
            skills=[skill],
        )

        request_handler = DefaultRequestHandler(
            agent_executor=ImageGenerationAgentExecutor(),
            task_store=InMemoryTaskStore(),
        )
        server = A2AStarletteApplication(
            agent_card=agent_card, http_handler=request_handler
        )
        import uvicorn

        print(f"🌐 Server starting on {host}:{port}")
        print(f"📄 Agent URL: {agent_host_url}")
        print("✅ Server is ready!")

        uvicorn.run(server.build(), host=host, port=port)

    except MissingAPIKeyError as e:
        logger.error(f'Error: {e}')
        print(f"\n❌ Error: {e}")
        print("\n💡 How to fix:")
        print("1. Get your Qwen API key from: https://help.aliyun.com/zh/model-studio/get-api-key")
        print("2. Create a .env file with: QWEN_API_KEY=sk-your-api-key-here")
        print("3. Or set environment variable: export QWEN_API_KEY=sk-your-api-key-here")
        exit(1)
    except Exception as e:
        logger.error(f'An error occurred during server startup: {e}')
        print(f"\n❌ Server startup error: {e}")
        exit(1)


if __name__ == '__main__':
    main()
