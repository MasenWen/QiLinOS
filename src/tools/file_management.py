import logging
from langchain_community.tools.file_management import WriteFileTool
from .decorators import create_logged_tool
from src.utils.db_manager import log_handler

logger = logging.getLogger(__name__)
logger.addHandler(log_handler)

# Initialize file management tool with logging
LoggedWriteFile = create_logged_tool(WriteFileTool)
write_file_tool = LoggedWriteFile()
