
import sys
import requests
from bs4 import BeautifulSoup
from baidusearch.baidusearch import search
ABSTRACT_MAX_LENGTH = 300  # abstract max length

user_agents = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
    'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)',
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko)'
    ' Ubuntu Chromium/49.0.2623.108 Chrome/49.0.2623.108 Safari/537.36',
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; pt-BR) AppleWebKit/533.3 '
    '(KHTML, like Gecko)  QtWeb Internet Browser/3.7 http://www.QtWeb.net',
    'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/41.0.2228.0 Safari/537.36',
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US) AppleWebKit/532.2 (KHTML, '
    'like Gecko) ChromePlus/4.0.222.3 Chrome/4.0.222.3 Safari/532.2',
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.4pre) '
    'Gecko/20070404 K-Ninja/2.1.3',
    'Mozilla/5.0 (Future Star Technologies Corp.; Star-Blade OS; x86_64; U; '
    'en-US) iNet Browser 4.7',
    'Mozilla/5.0 (Windows; U; Windows NT 6.1; rv:2.2) Gecko/20110201',
    'Mozilla/5.0 (Windows; U; Windows NT 5.1; en-US; rv:1.8.1.13) '
    'Gecko/20080414 Firefox/2.0.0.13 Pogo/2.0.0.13.6866'
]

# 请求头信息 - 更新为适合必应的Referer
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/68.0.3440.106 Safari/537.36',
    "Referer": "https://www.bing.com/",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"
}

bing_host_url = "https://www.bing.com"
bing_search_url = "https://www.bing.com/search?q="

session = requests.Session()
session.headers = HEADERS


def search_bing(keyword, num_results=30, debug=0):
    """
    通过关键字进行搜索
    :param keyword: 关键字
    :param num_results： 指定返回的结果个数
    :return: 结果列表
    """
    if not keyword:
        return None

    list_result = []
    page = 1

    # 起始搜索的url - 使用必应搜索URL
    next_url = bing_search_url + keyword

    # 循环遍历每一页的搜索结果，并返回下一页的url
    while len(list_result) < num_results:
        data, next_url = parse_html(next_url, rank_start=len(list_result), debug=debug)
        if data:
            list_result += data
            if debug:
                print("---searching[{}], finish parsing page {}, results number={}: ".format(keyword, page, len(data)))
                for d in data:
                    print(str(d))

        if not next_url:
            if debug:
                print(u"already search the last page。")
            break
        page += 1

    if debug:
        print("\n---search [{}] finished. total results number={}！".format(keyword, len(list_result)))
    return list_result[: num_results] if len(list_result) > num_results else list_result


def parse_html(url, rank_start=0, debug=0):
    """
    解析必应搜索结果
    :param url: 需要抓取的 url
    :return:  结果列表，下一页的url
    """
    try:
        res = session.get(url=url)
        res.encoding = "utf-8"
        root = BeautifulSoup(res.text, "lxml")

        list_data = []

        # 必应搜索结果的主要容器
        search_results = root.find("ol", id="b_results")
        if not search_results:
            if debug:
                print("No search results found")
            return list_data, None

        # 查找所有搜索结果项
        results = search_results.find_all("li", class_="b_algo")

        for result in results:
            title = ''
            url = ''
            abstract = ''

            try:
                # 提取标题和URL
                title_elem = result.find("h2")
                if title_elem and title_elem.a:
                    title = title_elem.a.get_text(strip=True)
                    url = title_elem.a.get("href", "").strip()

                # 提取摘要
                abstract_elem = result.find("div", class_="b_caption")
                if abstract_elem:
                    # 尝试获取摘要文本
                    p_elem = abstract_elem.find("p")
                    if p_elem:
                        abstract = p_elem.get_text(strip=True)
                    else:
                        abstract = abstract_elem.get_text(strip=True)

                # 如果没找到摘要，尝试其他可能的元素
                if not abstract:
                    summary_elem = result.find("div", class_="b_snippet")
                    if summary_elem:
                        abstract = summary_elem.get_text(strip=True)

                # 限制摘要长度
                if ABSTRACT_MAX_LENGTH and len(abstract) > ABSTRACT_MAX_LENGTH:
                    abstract = abstract[:ABSTRACT_MAX_LENGTH]

                if title:  # 只有有标题的结果才加入
                    rank_start += 1
                    list_data.append({
                        "title": title,
                        "abstract": abstract,
                        "url": url,
                        "rank": rank_start
                    })

            except Exception as e:
                if debug:
                    print("catch exception during parsing result, e={}".format(e))
                continue

        # 找到下一页按钮 - 必应的下一页通常在a标签中，有特定的类名
        next_btn = root.find("a", class_="sb_pagN")
        if not next_btn:
            # 尝试其他可能的下一页选择器
            next_btn = root.find("a", title="Next page")

        # 已经是最后一页了，没有下一页了
        if not next_btn:
            return list_data, None

        next_url = bing_host_url + next_btn["href"]
        return list_data, next_url

    except Exception as e:
        if debug:
            print(u"catch exception during parsing page html, e：{}".format(e))
        return None, None



