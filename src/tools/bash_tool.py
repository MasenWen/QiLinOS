import logging
import subprocess
from typing import Annotated
from langchain_core.tools import tool
from .decorators import log_io
from src.utils.db_manager import log_handler

from src.utils.db_manager import node_state
# Initialize logger
logger = logging.getLogger(__name__)
logger.addHandler(log_handler)

@tool
@log_io
def bash_tool(
    cmd: Annotated[str, "The bash command to be executed."],
):
    """Use this to execute bash command and do necessary operations."""
    logger.info(f"{node_state}-=-程序员===执行Bash命令: \n{cmd}|||")
    try:
        # Execute the command and capture output
        result = subprocess.run(
            cmd, shell=True, check=True, text=True, capture_output=True
        )
        # Return stdout as the result
        logger.info(f"{node_state}-=-程序员===Bash Stdout输出: \n{result.stdout}|||")
        return result.stdout
    except subprocess.CalledProcessError as e:
        # If command fails, return error information
        error_message = f"{node_state}-=-程序员===Bash返回执行错误代码： {e.returncode}|||.\nStdout: \n{e.stdout}|||\nStderr: \n{e.stderr}|||"
        logger.error(error_message)
        return error_message
    except Exception as e:
        # Catch any other exceptions
        error_message = f"{node_state}-=-程序员===执行命令出错: \n{str(e)}|||"
        logger.error(error_message)
        return error_message


if __name__ == "__main__":
    print(bash_tool.invoke("ls -all"))
