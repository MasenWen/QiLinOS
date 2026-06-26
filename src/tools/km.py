import logging
from typing import Annotated
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from .decorators import log_io

from src.tools.web_search import fetch_webpage_content
import trafilatura
import time
import random
from pathlib import Path
from typing import Dict, Type, Optional, Any
from autofill.parsers.document_factory import DocumentParserFactory
from src.utils.db_manager import db_manager
import asyncio
from src.utils.db_manager import node_state

logger = logging.getLogger(__name__)
from src.rag.ps_rag import RAG_PS

def parse_document(document_path: Path) -> Optional[Dict[str, Any]]:
        """解析文档"""
        logger.info(f"{node_state}-=-填表员===开始解析文档: {document_path}")
        try:
            if not document_path.exists():
                logger.error(f"文档不存在: {document_path}")
                return None
            parser_factory = DocumentParserFactory()
            parser = parser_factory.create_parser(document_path)
            if not parser:
                logger.error(f"不支持的文档格式: {document_path}")
                return None
            
            parsed_doc = parser.parse(document_path)
            logger.info(f"{node_state}-=-填表员===文档解析完成: {document_path}")
            return parsed_doc
            
        except Exception as e:
            logger.error(f"文档解析失败: {e}")
            return None


async def aquery(content):
    rag_gps = RAG_PS()
    result = await rag_gps.aquery(content)
    return result

async def ainsert_document(content, path = None):
    rag_gps = RAG_PS()
    result = await rag_gps.insert_document(content, path)
    return result

@tool
@log_io
def km_add_content(content: Annotated[str, "content adding to knowledge base"]) -> HumanMessage:
    """add content to knowledge base"""
    print(f"km_add_content: {content}")
    flag = asyncio.run(ainsert_document(content))
    db_manager.set_km_updated()
    return HumanMessage(content="以上内容已添加到知识库" if flag else "以上内容添加到知识库失败！")

def km_add_link(link: Annotated[str, "link adding to knowledge base"]) -> HumanMessage:
    """add content of link to knowledge base"""
    print(f"km_add_link: {link}")
    content = fetch_webpage_content(link, 5)
    flag = False
    if content:
        flag = asyncio.run(ainsert_document(content))
        db_manager.set_km_updated()
    return HumanMessage(content="以上链接中的内容已添加到知识库" if flag else "无法添加链接中的内容到知识库，请检查链接内容是否存在！")

def km_add_file(file: Annotated[str, "file adding to knowledge base"]) -> HumanMessage:
    """add content to knowledge base"""
    print(f"km_add_file: {file}")
    result = parse_document(Path(file))
    content = result["text_content"]
    print(f"file content: {content}")
    flag = asyncio.run(ainsert_document(content, file))
    db_manager.set_km_updated()
    return HumanMessage(content="以上文件内容已添加到知识库" if flag else "无法添加文件中的内容到知识库，请检查文件是否存在或可读！")