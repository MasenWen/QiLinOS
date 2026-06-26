import logging
from typing import Annotated
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
# from .decorators import log_io

from baidusearch.baidusearch import search
import trafilatura
from search_bing import search_bing
import time
import random


logger = logging.getLogger(__name__)

def collect_url(keyword, max_retries=3):
    """收集URL，增加重试机制"""
    for attempt in range(max_retries):
        try:
            result_baidu = search(keyword)
            result_bing = search_bing(keyword)
            result = result_baidu + result_bing
            final_result = []
            for res in result:
                if 'zhihu' not in res['url'] and 'http' in res['url']:
                    final_result.append(res['url'])
            print(f"关键词 '{keyword}' 找到 {len(final_result)} 个URL")
            return final_result
        except Exception as e:
            logger.warning(f"第 {attempt + 1} 次收集URL失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 指数退避
            else:
                logger.error(f"收集URL最终失败: {e}")
                return []


def fetch_webpage_content(url, max_retries=2):
    """获取网页内容，增加重试和错误处理"""
    for attempt in range(max_retries):
        try:
            page_content = trafilatura.fetch_url(url)
            if not page_content:
                logger.warning(f"无法获取页面内容: {url}")
                return None

            text = trafilatura.extract(page_content)
            if text and len(text.strip()) > 50:  # 确保有足够的内容
                return text
            else:
                logger.warning(f"页面内容过短或为空: {url}")
                return None

        except Exception as e:
            logger.warning(f"第 {attempt + 1} 次获取页面内容失败: {url}, 错误: {e}")
            if attempt < max_retries - 1:
                time.sleep(1 + random.random())  # 随机延迟1-2秒

    return None


def process_webpage_content(client, model, keyword, current_content, webpage_text):
    """处理网页内容，增加错误处理"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": f"你是一个信息分析专家，负责从网页内容中提取和整合相关信息。\n\n当前任务：- 搜索关键词：{keyword} - 已有相关信息：{current_content}\n\n处理步骤：1. 从当前网页内容提取与关键词相关的核心信息，如果当前的网页信息为空或者与关键词不相关，保持已有的相关信息不变即可 2. 将新信息与已有信息去重、整合 3. 判断整合后的信息是否足够回答关于该关键词的问题 - 足够标准：信息准确、完整、有具体细节 - 不足标准：信息模糊、缺失关键细节、存在矛盾\n\n返回格式：{{\"content\": \"整合后的详细信息\", \"flag\": \"true/false\"}}严格按这种格式返回，不要添加任何前后缀"
                },
                {
                    "role": "user",
                    "content": f"网页内容：{webpage_text}\n请按上述要求处理并返回JSON格式结果。"
                }
            ],
            stream=False
        )

        result_str = response.choices[0].message.content.strip()
        # 安全的JSON解析
        if result_str.startswith('{') and result_str.endswith('}'):
            try:
                result = eval(result_str)
                if isinstance(result, dict) and 'content' in result and 'flag' in result:
                    return result
            except:
                logger.warning(f"JSON解析失败: {result_str}")

        # 如果解析失败，返回默认值
        return {"content": current_content, "flag": "false"}

    except Exception as e:
        logger.error(f"处理网页内容时发生错误: {e}")
        return {"content": current_content, "flag": "false"}


def web_search(query: Annotated[str, "User's query request."]) -> HumanMessage:
    r"""Search for relevant information on Baidu based on user input.
    """
    load_dotenv()
    API = os.getenv('DS_API_KEY')
    BASE_URL = os.getenv("DS_API_BASE")
    MODEL = os.getenv("DS_API_MODEL")

    if not all([API, BASE_URL, MODEL]):
        return HumanMessage(content="❌ 系统配置不完整，无法进行搜索")

    client = OpenAI(api_key=API, base_url=BASE_URL)
    answer_tmp = ""

    # 关键词生成
    try:
        response_step1 = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": f"你是一个专业的搜索关键词生成助手。根据用户问题，分析是否需要多维度搜索：- 如果问题简单明确，生成1个核心关键词 - 如果问题复杂或多方面，生成3-5个互补的关键词 要求：1. 关键词要具体、可搜索、覆盖问题核心 2. 用中文逗号分隔，格式：\"关键词1，关键词2，关键词3\" 3. 最多不超过5个关键词 4. 确保关键词组合能完整回答用户问题。用户输入：{query}"
                }
            ],
            stream=False
        )
        keywordList = response_step1.choices[0].message.content.split("，")
    except Exception as e:
        logger.error(f"生成关键词时发生错误: {e}")
        return HumanMessage(content="❌ 生成搜索关键词时发生错误")

    print(f"生成的关键词列表: {keywordList}")

    # 处理每个关键词
    for keyword in keywordList:
        keyword = keyword.strip()
        if not keyword:
            continue

        print(f"正在处理关键词: {keyword}")
        search_result = collect_url(keyword)

        if not search_result:
            logger.warning(f"关键词 '{keyword}' 没有找到可用的URL")
            answer_tmp += f"\n\n关于【{keyword}】没有找到相关信息。"
            continue

        keyword_search_result = ""
        content_found = False

        for url in search_result[:10]:  # 限制每个关键词最多处理10个URL
            try:
                print(f"正在处理URL: {url}")
                text = fetch_webpage_content(url)

                if not text:
                    continue

                # 处理网页内容
                res = process_webpage_content(client, MODEL, keyword, keyword_search_result, text)

                if res["content"] and res["content"] != keyword_search_result:
                    keyword_search_result = res["content"]
                    content_found = True
                    print(f"关键词 '{keyword}' 获取到内容，长度: {len(keyword_search_result)}")

                if res["flag"] == "true":
                    print(f"关键词 '{keyword}' 信息收集完成")
                    break

                # 添加延迟避免请求过快
                time.sleep(0.5 + random.random())

            except Exception as e:
                logger.error(f"处理URL {url} 时发生错误: {e}")
                continue

        # 将当前关键词的结果添加到总答案中
        if content_found and keyword_search_result:
            answer_tmp += f"\n\n{keyword_search_result}"
        else:
            answer_tmp += f"\n\n关于【{keyword}】的信息收集不完整，建议尝试其他搜索方式。"

    # 最终答案生成
    try:
        if not answer_tmp.strip():
            return HumanMessage(content="🔍 没有找到相关的网页内容，请尝试调整搜索关键词或稍后重试。")

        response_step3 = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个专业的文档编辑助手，负责将分散的信息整合成高质量的最终答案。\n\n要求：1. 基于所有收集的信息，构建逻辑清晰的回答结构 2. 去除重复内容，解决信息矛盾（以最新或最可信信息为准） 3. 用流畅的中文重新组织内容 4. 使用Markdown格式优化可读性（标题、列表、重点强调等） 5. 如果信息不足，在相应部分注明局限性 6. 确保回答直接回应用户原始问题"
                },
                {
                    "role": "user",
                    "content": f"用户原始问题：{query}\n收集到的所有信息：{answer_tmp}\n\n请生成最终的Markdown格式回答："
                }
            ],
            stream=False
        )
        final_answer = response_step3.choices[0].message.content.strip()
        print("最终答案生成成功")
    except Exception as e:
        logger.error(f"生成最终答案时发生错误: {e}")
        # 如果最终处理失败，至少返回原始收集的信息
        final_answer = f"## 搜索结果摘要\n\n基于您的查询\"{query}\"，我们收集到以下信息：\n\n{answer_tmp}\n\n*注：由于系统处理限制，信息可能未完全整合*"

    return {"role": "user", "content": final_answer}


if __name__ == "__main__":
    from src.agent.types import State

    a = web_search("长沙理工大学")
    print(a)