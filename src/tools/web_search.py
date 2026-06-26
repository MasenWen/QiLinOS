import logging
from typing import Annotated
from openai import OpenAI
import os
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_core.tools import tool
from .decorators import log_io

from baidusearch.baidusearch import search
import trafilatura
from .search_bing import search_bing
import time
import random
from src.utils.db_manager import log_handler, ppt_state

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(log_handler)


def collect_url(keyword, max_retries=3, max_urls=10):
    """收集URL，确保能获取到足够的结果"""
    for attempt in range(max_retries):
        try:
            # 恢复原来的搜索方式，不限制结果数量
            result_baidu = search(keyword)
            result_bing = search_bing(keyword)
            result = result_baidu + result_bing
            final_result = []
            for res in result:
                if 'zhihu' not in res['url'] and 'http' in res['url']:
                    final_result.append(res['url'])
                if len(final_result) >= max_urls:  # 只限制最终返回数量，不限制搜索
                    break

            logger.info(f"{ppt_state}-=-研究员===关键词 '{keyword}' 找到 {len(final_result)} 个URL")
            return final_result
        except Exception as e:
            print(f"第 {attempt + 1} 次收集URL失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                print(f"收集URL最终失败: {e}")
                return []


def fetch_webpage_content(url, min_content = 50, max_retries=2):
    """获取网页内容，增加重试和错误处理"""
    for attempt in range(max_retries):
        try:
            page_content = trafilatura.fetch_url(url)
            if not page_content:
                logger.info(f"{ppt_state}-=-研究员===无法获取页面内容: {url}")
                return None

            text = trafilatura.extract(page_content)
            if text and len(text.strip()) > min_content:  # 确保有足够的内容
                return text
            else:
                logger.info(f"{ppt_state}-=-研究员===页面内容过短或为空: {url}")
                return None

        except Exception as e:
            logger.info(f"{ppt_state}-=-研究员===第 {attempt + 1} 次获取页面内容失败: {url}, 错误: {e}")
            if attempt < max_retries - 1:
                time.sleep(1 + random.random())

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
                print(f"JSON解析失败: {result_str}")

        # 如果解析失败，返回默认值
        return {"content": current_content, "flag": "false"}

    except Exception as e:
        print(f"处理网页内容时发生错误: {e}")
        return {"content": current_content, "flag": "false"}


def assess_query_complexity(client, model, query):
    """使用大模型评估查询复杂度"""
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个查询复杂度评估专家。请分析用户查询的复杂度：\n- 简单查询：单一事实、定义、简单问题（如'什么是AI'、'北京人口'）\n- 复杂查询：需要多角度分析、比较、深度解释的问题（如'AI对社会的影响'、'比较不同编程语言的优缺点'）\n\n返回格式：{\"complexity\": \"simple/complex\", \"keywords_count\": \"建议的关键词数量\"}"
                },
                {
                    "role": "user",
                    "content": f"分析这个查询的复杂度：{query}"
                }
            ],
            stream=False
        )

        result_str = response.choices[0].message.content.strip()
        if result_str.startswith('{') and result_str.endswith('}'):
            try:
                result = eval(result_str)
                complexity = result.get('complexity', 'complex')
                keywords_count = result.get('keywords_count', '3')
                return complexity, int(keywords_count)
            except:
                print(f"复杂度评估解析失败: {result_str}")

        return 'complex', 3  # 解析失败时默认为复杂查询，3个关键词
    except Exception as e:
        print(f"评估查询复杂度时发生错误: {e}")
        return 'complex', 3  # 出错时默认为复杂查询，3个关键词


def check_sufficiency(client, model, query, collected_info):
    """检查当前收集的信息是否足够回答用户问题"""
    if not collected_info.strip():
        return False

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": "你是一个信息充足性评估专家。基于用户问题和当前收集的信息，判断信息是否足够直接回答用户问题。\n\n判断标准：\n- 足够：信息直接、准确回答了用户的核心问题，没有明显缺失\n- 不足：信息模糊、不完整、缺乏关键细节或与问题相关性不强\n\n只返回 'true' 或 'false'，不要其他内容。"
                },
                {
                    "role": "user",
                    "content": f"用户问题：{query}\n当前收集的信息：{collected_info}\n\n信息是否足够直接回答用户问题？只回答 true 或 false："
                }
            ],
            stream=False,
            max_tokens=10
        )

        result = response.choices[0].message.content.strip().lower()
        return result == 'true'
    except Exception as e:
        print(f"检查信息充足性时发生错误: {e}")
        return False


def generate_keywords(client, model, query, complexity, max_keywords):
    """生成搜索关键词"""
    try:
        if complexity == 'simple':
            system_prompt = f"你是一个专业的搜索关键词生成助手。用户的问题是简单查询，请生成{max_keywords}个最核心的关键词来回答这个问题。要求：关键词要精准、直接对应问题核心。用中文逗号分隔。用户输入：{query}"
        else:
            system_prompt = f"你是一个专业的搜索关键词生成助手。根据用户问题，分析需要哪些方面的信息，生成{max_keywords}个互补的关键词。要求：关键词要具体、可搜索、覆盖问题核心。用中文逗号分隔。用户输入：{query}"

        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}],
            stream=False
        )
        keyword_text = response.choices[0].message.content.strip()
        # 处理可能的多种分隔符
        keywordList = []
        for sep in ['，', ',', '、']:
            if sep in keyword_text:
                keywordList = [k.strip() for k in keyword_text.split(sep) if k.strip()]
                break
        if not keywordList:
            keywordList = [keyword_text]

        return keywordList[:max_keywords]  # 限制关键词数量
    except Exception as e:
        print(f"生成关键词时发生错误: {e}")
        # 出错时返回查询本身作为关键词
        return [query]

def web_search_ppt(query) -> str:
    load_dotenv()
    API = os.getenv('DS_API_KEY')
    BASE_URL = os.getenv("DS_API_BASE")
    MODEL = os.getenv("DS_API_MODEL")
    logger.info(f"{ppt_state}-=-研究员===搜索:{query}")
    if not all([API, BASE_URL, MODEL]):
        return HumanMessage(content="❌ 系统配置不完整，无法进行搜索")

    client = OpenAI(api_key=API, base_url=BASE_URL)
    answer_tmp = ""

    # 第一步：评估查询复杂度
    logger.info(f"{ppt_state}-=-研究员===正在评估查询复杂度...")
    complexity, suggested_keywords_count = assess_query_complexity(client, MODEL, query)
    logger.info(f"{ppt_state}-=-研究员===查询复杂度评估结果: {complexity}, 建议关键词数量: {suggested_keywords_count}")

    # 根据复杂度确定实际使用的关键词数量
    if complexity == 'simple':
        max_keywords = min(suggested_keywords_count, 2)  # 简单查询最多2个关键词
        max_urls_per_keyword = 5  # 简单查询每个关键词处理5个URL
    else:
        max_keywords = min(suggested_keywords_count, 4)  # 复杂查询最多4个关键词
        max_urls_per_keyword = 8  # 复杂查询每个关键词处理8个URL

    # 生成关键词
    keywordList = generate_keywords(client, MODEL, query, complexity, max_keywords)
    logger.info(f"{ppt_state}-=-研究员===生成的关键词列表: {keywordList}")

    # 处理每个关键词
    for i, keyword in enumerate(keywordList):
        keyword = keyword.strip()
        if not keyword:
            continue

        logger.info(f"{ppt_state}-=-研究员===正在处理关键词 ({i + 1}/{len(keywordList)}): {keyword}")

        # 搜索URL - 不限制搜索数量，只限制处理数量
        search_result = collect_url(keyword, max_urls=15)  # 收集最多15个URL，确保有足够结果

        if not search_result:
            logger.info(f"{ppt_state}-=-研究员===关键词 '{keyword}' 没有找到可用的URL")
            answer_tmp += f"\n\n关于【{keyword}】没有找到相关信息。"
            continue

        keyword_search_result = ""
        content_found = False
        processed_urls = 0

        for j, url in enumerate(search_result):
            if processed_urls >= max_urls_per_keyword:
                break

            try:
                print(f"正在处理URL ({j + 1}/{len(search_result)}): {url}")
                text = fetch_webpage_content(url)

                if not text:
                    continue

                # 处理网页内容
                res = process_webpage_content(client, MODEL, keyword, keyword_search_result, text)

                if res["content"] and res["content"] != keyword_search_result:
                    keyword_search_result = res["content"]
                    content_found = True
                    print(f"关键词 '{keyword}' 获取到内容，长度: {len(keyword_search_result)}")

                processed_urls += 1

                # 定期检查是否已经收集到足够信息
                if processed_urls % 2 == 0 and answer_tmp.strip() and keyword_search_result.strip():
                    current_total_info = answer_tmp + "\n\n" + keyword_search_result if answer_tmp else keyword_search_result
                    is_sufficient = check_sufficiency(client, MODEL, query, current_total_info)
                    if is_sufficient:
                        print("信息已足够，提前结束当前关键词搜索")
                        answer_tmp = current_total_info
                        break  # 跳出URL循环

                if res["flag"] == "true":
                    print(f"关键词 '{keyword}' 信息收集完成")
                    break

                # 添加延迟避免请求过快
                time.sleep(0.3 + random.random())

            except Exception as e:
                print(f"处理URL {url} 时发生错误: {e}")
                continue

        # 将当前关键词的结果添加到总答案中
        if content_found and keyword_search_result:
            if answer_tmp:
                answer_tmp += "\n\n" + keyword_search_result
            else:
                answer_tmp = keyword_search_result

        # 检查总体信息是否足够（在每个关键词处理后）
        if answer_tmp.strip():
            is_sufficient = check_sufficiency(client, MODEL, query, answer_tmp)
            if is_sufficient:
                print("总体信息已足够，提前结束所有搜索")
                break  # 跳出关键词循环

        # 简单查询在第一个关键词找到足够信息后就停止
        if complexity == 'simple' and content_found and answer_tmp.strip():
            print("简单查询已找到信息，提前结束搜索")
            break

    # 最终答案生成
    try:
        if not answer_tmp.strip():
            return HumanMessage(content="🔍 没有找到相关的网页内容，请尝试调整搜索关键词或稍后重试。")

        # 如果信息足够且是简单查询，可以简化最终处理
        if complexity == 'simple' and len(answer_tmp) < 1000:
            # 简单查询直接返回整理后的信息
            final_answer = f"## 搜索结果\n\n{answer_tmp}"
        else:
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
        print(f"生成最终答案时发生错误: {e}")
        # 如果最终处理失败，至少返回原始收集的信息
        final_answer = f"## 搜索结果摘要\n\n基于您的查询\"{query}\"，我们收集到以下信息：\n\n{answer_tmp}\n\n*注：由于系统处理限制，信息可能未完全整合*"

    print(final_answer)
    return final_answer
@tool
@log_io
def web_search(query: Annotated[str, "User's query request."]) -> HumanMessage:
    r"""Search for relevant information on Baidu based on user input.
    """
    load_dotenv()
    API = os.getenv('DS_API_KEY')
    BASE_URL = os.getenv("DS_API_BASE")
    MODEL = os.getenv("DS_API_MODEL")
    logger.info(f"{ppt_state}-=-研究员===搜索:{query}")
    if not all([API, BASE_URL, MODEL]):
        return HumanMessage(content="❌ 系统配置不完整，无法进行搜索")

    client = OpenAI(api_key=API, base_url=BASE_URL)
    answer_tmp = ""

    # 第一步：评估查询复杂度
    logger.info(f"{ppt_state}-=-研究员===正在评估查询复杂度...")
    complexity, suggested_keywords_count = assess_query_complexity(client, MODEL, query)
    logger.info(f"{ppt_state}-=-研究员===查询复杂度评估结果: {complexity}, 建议关键词数量: {suggested_keywords_count}")

    # 根据复杂度确定实际使用的关键词数量
    if complexity == 'simple':
        max_keywords = min(suggested_keywords_count, 2)  # 简单查询最多2个关键词
        max_urls_per_keyword = 5  # 简单查询每个关键词处理5个URL
    else:
        max_keywords = min(suggested_keywords_count, 4)  # 复杂查询最多4个关键词
        max_urls_per_keyword = 8  # 复杂查询每个关键词处理8个URL

    # 生成关键词
    keywordList = generate_keywords(client, MODEL, query, complexity, max_keywords)
    logger.info(f"{ppt_state}-=-研究员===生成的关键词列表: {keywordList}")

    # 处理每个关键词
    for i, keyword in enumerate(keywordList):
        keyword = keyword.strip()
        if not keyword:
            continue

        logger.info(f"{ppt_state}-=-研究员===正在处理关键词 ({i + 1}/{len(keywordList)}): {keyword}")

        # 搜索URL - 不限制搜索数量，只限制处理数量
        search_result = collect_url(keyword, max_urls=15)  # 收集最多15个URL，确保有足够结果

        if not search_result:
            logger.info(f"{ppt_state}-=-研究员===关键词 '{keyword}' 没有找到可用的URL")
            answer_tmp += f"\n\n关于【{keyword}】没有找到相关信息。"
            continue

        keyword_search_result = ""
        content_found = False
        processed_urls = 0

        for j, url in enumerate(search_result):
            if processed_urls >= max_urls_per_keyword:
                break

            try:
                logger.info(f"{ppt_state}-=-研究员===正在处理URL ({j + 1}/{len(search_result)}): {url}")
                text = fetch_webpage_content(url)

                if not text:
                    continue

                # 处理网页内容
                res = process_webpage_content(client, MODEL, keyword, keyword_search_result, text)

                if res["content"] and res["content"] != keyword_search_result:
                    keyword_search_result = res["content"]
                    content_found = True
                    logger.info(f"{ppt_state}-=-研究员===关键词 '{keyword}' 获取到内容，长度: {len(keyword_search_result)}")

                processed_urls += 1

                # 定期检查是否已经收集到足够信息
                if processed_urls % 2 == 0 and answer_tmp.strip() and keyword_search_result.strip():
                    current_total_info = answer_tmp + "\n\n" + keyword_search_result if answer_tmp else keyword_search_result
                    is_sufficient = check_sufficiency(client, MODEL, query, current_total_info)
                    if is_sufficient:
                        logger.info(f"{ppt_state}-=-研究员===信息已足够，提前结束当前关键词搜索")
                        answer_tmp = current_total_info
                        break  # 跳出URL循环

                if res["flag"] == "true":
                    logger.info(f"{ppt_state}-=-研究员===关键词 '{keyword}' 信息收集完成")
                    break

                # 添加延迟避免请求过快
                time.sleep(0.3 + random.random())

            except Exception as e:
                print(f"处理URL {url} 时发生错误: {e}")
                continue

        # 将当前关键词的结果添加到总答案中
        if content_found and keyword_search_result:
            if answer_tmp:
                answer_tmp += "\n\n" + keyword_search_result
            else:
                answer_tmp = keyword_search_result

        # 检查总体信息是否足够（在每个关键词处理后）
        if answer_tmp.strip():
            is_sufficient = check_sufficiency(client, MODEL, query, answer_tmp)
            if is_sufficient:
                logger.info(f"{ppt_state}-=-研究员===总体信息已足够，提前结束所有搜索")
                break  # 跳出关键词循环

        # 简单查询在第一个关键词找到足够信息后就停止
        if complexity == 'simple' and content_found and answer_tmp.strip():
            logger.info(f"{ppt_state}-=-研究员===简单查询已找到信息，提前结束搜索")
            break

    # 最终答案生成
    try:
        if not answer_tmp.strip():
            return HumanMessage(content="🔍 没有找到相关的网页内容，请尝试调整搜索关键词或稍后重试。")

        # 如果信息足够且是简单查询，可以简化最终处理
        if complexity == 'simple' and len(answer_tmp) < 1000:
            # 简单查询直接返回整理后的信息
            final_answer = f"## 搜索结果\n\n{answer_tmp}"
        else:
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
        print(f"生成最终答案时发生错误: {e}")
        # 如果最终处理失败，至少返回原始收集的信息
        final_answer = f"## 搜索结果摘要\n\n基于您的查询\"{query}\"，我们收集到以下信息：\n\n{answer_tmp}\n\n*注：由于系统处理限制，信息可能未完全整合*"

    return HumanMessage(content=final_answer)

# a = web_search("比亚迪新能源汽车市场情况")
# print(a)