from typing import Literal, Dict, Any
import httpx
import pandas as pd
from mcp.server.fastmcp import FastMCP
import requests
import hashlib
import random

mcp = FastMCP("api_server")

server_name = 'API接口'

@mcp.tool()
async def get_city_weather(city: str) -> str:
    """
    根据城市名称查询实况天气
    """
    adcode_df = pd.read_excel("./mcp_server/server/AMap_adcode_citycode.xlsx")
    GAODE_API_KEY = "<API_KEY>"
    adcode_row = adcode_df[adcode_df["中文名"].str.contains(city, na=False)]

    if adcode_row.empty:
        return f"未找到城市：{city} 的 adcode，请检查名称是否正确"

    adcode = str(adcode_row.iloc[0]["adcode"])

    url = "https://restapi.amap.com/v3/weather/weatherInfo"
    params = {
        "key": GAODE_API_KEY,
        "city": adcode,
        "extensions": "base",  # 实况天气
        "output": "JSON"
    }

    response = requests.get(url, params=params)

    data = response.json()

    if data.get("status") != "1":
        return f"获取天气失败：{data.get('info', '未知错误')}"

    weather_data = data["lives"][0]
    weather_context = (
        f"城市：{weather_data['province']} {weather_data['city']}\n"
        f"天气：{weather_data['weather']}\n"
        f"气温：{weather_data['temperature']}°C\n"
        f"风向：{weather_data['winddirection']}\n"
        f"风力：{weather_data['windpower']}级\n"
        f"湿度：{weather_data['humidity']}%\n"
        f"更新时间：{weather_data['reporttime']}"
    )

    return weather_context

@mcp.tool()
async def get_baidu_translate(text: str, from_lang: str = 'en', to_lang: str = 'zh') -> str:
    """
    根据内容进行翻译（百度翻译）
    """
    appid = "<APPID>"
    appkey = "<APPKEY>"

    endpoint = 'http://api.fanyi.baidu.com'
    path = '/api/trans/vip/translate'
    url = endpoint + path

    def make_md5(s, encoding='utf-8'):
        return hashlib.md5(s.encode(encoding)).hexdigest()

    salt = random.randint(32768, 65536)
    sign = make_md5(appid + text + str(salt) + appkey)

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    payload = {
        'appid': appid,
        'q': text,
        'from': from_lang,
        'to': to_lang,
        'salt': salt,
        'sign': sign
    }

    try:
        response = requests.post(url, data=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

        if 'trans_result' in result:
            translated_text = result['trans_result'][0]['dst']
            return translated_text
        else:
            return "翻译失败，请检查API返回的结果。"

    except requests.exceptions.RequestException as e:
        return f"请求失败: {e}"


@mcp.tool()
async def get_constellation_fortune(
    constellation_name: str,
    fortune_type: Literal["today", "tomorrow", "week", "month", "year"] = "today"
) -> Dict[str, Any]:
    """
    查询指定星座的运势。

    参数:
      - constellation_name: 星座中文全称（如 "白羊座"、"金牛座"…）
      - fortune_type: 运势类型，可选 "today", "tomorrow", "week", "month", "year"
          默认 "today"（今日运势）
    """
    API_KEY = "<API_KEY>"
    BASE_URL = "https://api.tanshuapi.com/api/constellation/v1/index"
    NAME_TO_CID: Dict[str, str] = {
        "白羊座": "1",
        "金牛座": "2",
        "双子座": "3",
        "巨蟹座": "4",
        "狮子座": "5",
        "处女座": "6",
        "天秤座": "7",
        "天蝎座": "8",
        "射手座": "9",
        "摩羯座": "10",
        "水瓶座": "11",
        "双鱼座": "12",
    }
    cid = NAME_TO_CID.get(constellation_name)
    if cid is None:
        return {
            "code": 0,
            "msg": f"未识别的星座名称：{constellation_name}，请传入完整中文名，如“白羊座”",
            "data": {}
        }

    # 2. 调用远程 API
    params = {"key": API_KEY, "cid": cid, "type": fortune_type}
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(BASE_URL, params=params)
        resp.raise_for_status()
        result = resp.json()

    # 3. 透传结果
    return {
        "code": result.get("code", 0),
        "msg": result.get("msg", "调用失败"),
        "data": result.get("data", {})
    }


if __name__ == "__main__":
    mcp.run(transport='stdio')