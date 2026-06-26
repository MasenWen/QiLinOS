import subprocess
import time

def ocr_tool(image_path):
    """
    调用OCR可执行文件并获取输出
    """
    try:
        # 运行可执行文件
        result = subprocess.run(
            ["ocr_tool", image_path],  # 假设可执行文件在当前目录
            capture_output=True,
            text=True,
            timeout=60  # 设置超时时间
        )
        
        # 检查返回码
        if result.returncode == 0:
            print("识别成功！")
            print("输出内容:")
            print(result.stdout)
            return result.stdout
        else:
            print(f"识别失败，错误码: {result.returncode}")
            print(f"错误信息: {result.stderr}")
            return None
            
    except FileNotFoundError:
        print("错误: 找不到可执行文件 'ocr_tool'")
        return None
    except subprocess.TimeoutExpired:
        print("错误: OCR处理超时")
        return None
    except Exception as e:
        print(f"未知错误: {e}")
        return None


if __name__ == "__main__":
    output = ocr_tool("/home/ok/图片/test-ocr.png")
    print("="*60)
    print(output)