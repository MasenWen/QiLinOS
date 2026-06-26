import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.msg_process import parse_coder_response, parse_filler_response


# content = '''```json
# {
#   "conclusion": "已成功完成关于人工智能对未来工作影响的文章撰写，并将其保存为名为“人工智能对未来工作的影响.docx”的Word文档。文档结构清晰，内容详实，涵盖了引言、岗位增减趋势、行业变革、技能需求演变、机遇与挑战、应对策略及结论等部分。",
#   "process": "首先，根据研究员提供的资料，使用Python脚本对信息进行了结构化处理并保存为JSON文件。接着，基于该结构化数据，生成了一篇完整的中文文章并保存为Markdown格式作为中间产物。最后，利用python-docx库将文章内容转换并格式化为Word文档，设置了标题、正文样式和中文字体，并验证了文件的成功创建。",
#   "files": [
#     {
#       "file_name": "人工智能对未来工作的影响.docx",
#       "file_path": "/home/ubuntu/nex-agent-output/人工智能对未来工作的影响.docx"
#     }
#   ]
# }'''
# content = parse_coder_response(content)
# print(content)

text = "表格已成功填写，共填写16个字段，跳过14个字段。填写完成的文件路径为：out-data/output/demo_form-1_filled_20251205_171801.docx。"
text = parse_filler_response(text)
print(text)