import os
from openai import OpenAI

print(os.environ.get('DEEPSEEK_API_KEY'))
client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

response = client.chat.completions.create(
    model="deepseek-reasoner",#deepseek-reasoner
    messages=[
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "你好，介绍一下你自己。"},
    ],
    stream=False
)

print(response.choices[0].message.content)