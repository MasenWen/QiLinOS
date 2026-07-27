"""
OCR 工具测试 — 使用麒麟 AI Vision SDK。

之前: subprocess.run(["ocr_tool", image_path])
现在: src.sdk.ai_vision.recognize_text(image_path)
"""
import sys
import os

# Make sure we can import from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.sdk.ai_vision import recognize_text, TextRecognitionError, is_available


def ocr_tool(image_path: str):
    """使用麒麟 AI SDK 对图片进行文字识别"""
    if not os.path.isfile(image_path):
        print(f"错误: 图片文件不存在: {image_path}")
        return None

    if not is_available():
        print("错误: Kylin AI Vision SDK 不可用（请在 Kylin 系统上运行）")
        return None

    try:
        text = recognize_text(image_path, timeout=60.0)
        if text:
            print("识别成功！")
            print("输出内容:")
            print(text)
            return text
        else:
            print("识别完成但未获取到文本内容")
            return None
    except TextRecognitionError as e:
        print(f"OCR SDK 错误: {e}")
        return None
    except Exception as e:
        print(f"未知错误: {e}")
        return None


if __name__ == "__main__":
    output = ocr_tool("/home/kylin/图片/test-ocr.png")
    print("=" * 60)
    print(output)
