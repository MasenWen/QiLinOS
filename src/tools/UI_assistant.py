"""
UI自动化操作工具 - 基于视觉的智能代理，可执行打开应用、点击、输入等UI任务。
依赖：pyautogui, pyperclip, Pillow, openai等，需在有图形界面的环境中运行。
"""

import os
import base64
import json
import time
import pyautogui
import pyperclip
import subprocess
import platform
from openai import OpenAI
from PIL import ImageGrab, Image, ImageStat, ImageChops
from datetime import datetime
import traceback
from typing import Dict, List, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import sys
from pathlib import Path
from dotenv import load_dotenv
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage
from typing import Annotated

# 加载环境变量
load_dotenv()

# 配置API密钥（从环境变量读取）
DASHSCOPE_API_KEY = os.getenv("REASONING_API_KEY")
DASHSCOPE_BASE_URL = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
if not DASHSCOPE_API_KEY:
    raise ValueError("请设置环境变量 DASHSCOPE_API_KEY")

# 初始化阿里云百炼客户端
client = OpenAI(
    api_key=DASHSCOPE_API_KEY,
    base_url=DASHSCOPE_BASE_URL,
)

# 移除不必要的模拟延迟，提升效率
pyautogui.MINIMUM_DURATION = 0.01
pyautogui.PAUSE = 0.02

# 增强系统指令
SYSTEM_PROMPT = """
你是一个顶级的AI视觉操作代理，需要高效、准确地操作电脑。你的任务是分析电脑屏幕截图，理解用户的指令，然后将任务分解为智能、高效的操作。
**当前操作系统为Linux（但可使用Windows快捷键）**

**核心工作流程（必须严格遵守）：**
1. **观察屏幕**：分析当前屏幕状态，理解界面元素
2. **决策操作**：基于当前状态和目标，选择最合适的原子操作
3. **执行操作**：执行决策的操作
4. **观察反馈**：检查操作后的屏幕变化，确认操作效果

**屏幕观察重点：**
**必须特别关注屏幕底部的任务栏区域！**
1. **任务栏位置**：屏幕最下方（有时在左侧或右侧）的一条窄条。- 特别注意：如果屏幕下方任务栏有对应应用的图标，优先使用**CLICK**操作点击它打开它！
2. **图标特征**：通常是较小的应用程序图标
3. **查找策略**：分析截图时，首先查看屏幕底部区域，寻找任何应用程序图标

**应用图标识别指南：**
**任务栏图标（必须优先检查！）：**
- **位置**：屏幕底部边缘区域（可能是一行小图标）
- **外观**：各种应用程序的小图标，可能包括浏览器、微信、终端等
- **搜索顺序**：当需要打开应用时，首先检查底部任务栏，然后是桌面，最后才是其他方式

**桌面图标（其次检查）：**
- **位置**：屏幕中央区域
- **外观**：较大的图标，通常带有应用名称

**智能决策原则：**
1. **基于状态决策**：根据当前屏幕状态决定下一步操作，不要假设未看到的状态
2. **避免重复操作**：记住已执行的操作，不要重复相同的操作
3. **确认操作效果**：每次操作后检查屏幕变化，确保操作成功
4. **逐步推进**：将复杂任务分解为简单的原子操作步骤
5. **灵活重试**：如果操作失败，尝试其他方法，最多重试3次

**微信任务专项指导（特别重要）：**
对于微信相关任务，请严格按以下逻辑判断和决策：

**判断当前微信状态：**
1. **未打开状态**：看不到微信登录窗口
2. **已打开但未登录**：看到微信有登录按钮登录界面（屏幕中间）或二维码
3. **已登录主界面**：看到微信主界面，可能包括搜索框、联系人列表、聊天列表
4. **对话框界面**：看到消息输入框和发送按钮
5. **消息发送完成**：已经执行了SEND，并且在聊天框中能够看到用户发送的指定信息

**操作策略（严格按照顺序执行）：**
**特别重要！打开微信的正确顺序：**
1. **第一步：先返回桌面** - 使用RETURN_TO_DESKTOP返回桌面，确保桌面和任务栏清晰可见，全程只需要执行一次即可
2. **第二步：查找并点击图标** - 在桌面环境下查找微信图标：
   - 如果任务栏有微信图标，使用**CLICK**操作点击它
   - 如果桌面有微信图标，使用**DOUBLE_CLICK**操作打开它
   - 特别注意：如果屏幕下方任务栏有微信图标，优先使用**CLICK**操作点击它打开微信！
3. **第三步：命令行备用** - 如果都找不到，则命令行执行"wechat"打开

**重要原则：**
- **必须先用RETURN_TO_DESKTOP返回桌面**，然后再查找和点击微信图标
- 如果看到登录界面，如果显示了登录界面且显示了登录按钮，自动帮用户点击这个按钮；如果是二维码，等待10秒，让用户扫描二维码
- **特别重要！** 如果看到微信主界面，直接使用SEND操作，绝对不要采用CLICK动作打开任何联系人的对话框，因为这会导致SEND操作失败！
- **特别重要！** 如果屏幕下方任务栏有微信图标，优先使用**CLICK**操作点击它打开微信！
**应用打开通用策略：**
1. **返回桌面**：先使用RETURN_TO_DESKTOP返回桌面，全程只需要执行一次即可
2. **任务栏查找**：在桌面环境下仔细检查屏幕底部任务栏，寻找目标应用的图标
3. **桌面查找**：如果任务栏没有，再检查桌面区域
4. **搜索打开**：如果都找不到，使用SUPER_SEARCH或命令行

**原子操作类型：**
1. CLICK: 点击坐标 (x, y) - 用于任务栏图标、按钮等
2. DOUBLE_CLICK: 双击坐标 (x, y) - 用于桌面图标
3. RIGHT_CLICK: 右键点击坐标 (x, y)
4. TYPE: 输入文本（可指定是否使用Ctrl+V粘贴）
5. PRESS: 按下键盘按键或组合键
6. RUN_CMD: 执行命令行命令
7. SEARCH_SCREEN: 在屏幕上搜索特定文本或元素（会返回坐标）
8. WAIT: 等待指定时间（秒）
9. SEND: 发送微信消息给指定联系人（高效操作）
10. RETURN_TO_DESKTOP: 返回桌面（使用Win+D快捷键）
11. SUPER_SEARCH: 按Super键（Windows键）搜索应用
12. FINISH: 任务完成
13. FAIL: 任务失败
14. RETRY: 重试当前步骤（内部使用）

**输出格式（必须严格遵守）：**
{
  "thought": "分析当前屏幕状态和下一步应该执行的操作",
  "action": "CLICK",  // 必须是大写
  "parameters": {
    "x": 100,            // CLICK, DOUBLE_CLICK, RIGHT_CLICK时需要的坐标
    "y": 200,
    "text": "Hello",     // TYPE时需要的文本
    "use_paste": true,   // TYPE时是否使用Ctrl+V粘贴（长文本建议true）
    "keys": ["ctrl", "c"],  // PRESS时需要的按键组合
    "command": "wechat", // RUN_CMD时需要的命令
    "search_term": "微信", // SEARCH_SCREEN时的搜索词
    "wait_time": 1,      // WAIT时的等待时间（秒）
    "contactor": "张三",  // SEND时需要的联系人姓名
    "content": "你好",    // SEND时需要的消息内容
    "message": "任务完成！",  // FINISH时的说明
    "reason": "失败原因"  // FAIL时的失败原因
  }
}

**特别注意事项：**
1. **打开微信时，必须严格按照顺序：先RETURN_TO_DESKTOP，再点击图标**
2. 分析截图时，必须首先查看屏幕底部任务栏区域！
3. 任务栏图标通常较小，位于屏幕最下方边缘
4. 如果看到应用图标，优先点击图标而不是使用命令行
5. 微信任务中，如果看到主界面，立即使用SEND操作发送消息
6. 根据当前屏幕状态做出决策，不要假设未看到的状态
7. 避免重复执行相同的操作，除非有明确的屏幕反馈表明需要重试
8. 每次决策只选择一个最合适的原子操作
9. 如果操作失败或界面混乱，可以使用RETURN_TO_DESKTOP（Win+D）返回桌面重新开始
10. 最大重试次数为3次，超过则标记为失败
"""


class ActionType(Enum):
    """操作类型枚举"""
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    TYPE = "TYPE"
    PRESS = "PRESS"
    SCROLL = "SCROLL"
    RUN_CMD = "RUN_CMD"
    SEARCH_SCREEN = "SEARCH_SCREEN"
    WAIT = "WAIT"
    SEND = "SEND"
    RETURN_TO_DESKTOP = "RETURN_TO_DESKTOP"
    SUPER_SEARCH = "SUPER_SEARCH"
    FINISH = "FINISH"
    FAIL = "FAIL"
    RETRY = "RETRY"


@dataclass
class ActionRecord:
    """操作记录"""
    timestamp: datetime
    action_type: str
    parameters: Dict[str, Any]
    thought: str
    success: Optional[bool] = None
    screen_change: bool = False
    result_info: str = ""
    retry_count: int = 0


class ScreenAnalyzer:
    """屏幕分析器"""

    def __init__(self):
        self.last_screenshot = None
        self.last_screenshot_time = None
        self.screen_width, self.screen_height = pyautogui.size()

    def capture_screen(self, save_path=None):
        """捕获屏幕并返回图像对象"""
        try:
            screenshot = ImageGrab.grab()
            if save_path:
                screenshot.save(save_path)

            self.last_screenshot = screenshot
            self.last_screenshot_time = datetime.now()
            return screenshot
        except Exception as e:
            print(f"截图失败: {e}")
            return None

    def compare_screens(self, img1, img2, threshold=0.01):
        """比较两张屏幕截图的变化"""
        if img1 is None or img2 is None:
            return False, 0.0

        # 转换为灰度图
        img1_gray = img1.convert('L')
        img2_gray = img2.convert('L')

        # 计算差异
        diff = ImageChops.difference(img1_gray, img2_gray)
        stat = ImageStat.Stat(diff)
        diff_mean = sum(stat.mean) / 255.0

        has_change = diff_mean > threshold
        return has_change, diff_mean

    def get_screen_size(self):
        """获取屏幕尺寸"""
        return self.screen_width, self.screen_height


class TaskExecutor:
    """任务执行器 - 遵循观察->决策->执行->观察的循环"""

    def __init__(self, task_id=None):
        self.action_history = []
        self.screenshot_paths = []
        self.screenshots_dir = "screenshots"
        self.max_steps = 50  # 增加最大步数
        self.max_retries = 3  # 最大重试次数
        self.step_count = 0
        self.retry_count = {}  # 记录每个步骤的重试次数
        self.consecutive_failures = 0  # 连续失败次数

        # 任务ID，用于区分不同任务
        self.task_id = task_id or datetime.now().strftime("%Y%m%d_%H%M%S")

        # 初始化组件
        self.screen_analyzer = ScreenAnalyzer()

        # 创建目录
        if not os.path.exists(self.screenshots_dir):
            os.makedirs(self.screenshots_dir)

    def cleanup_screenshots(self):
        """清理本次任务的所有截图"""
        try:
            if os.path.exists(self.screenshots_dir):
                # 获取所有截图文件
                for filename in os.listdir(self.screenshots_dir):
                    if filename.startswith(f"screen_{self.task_id}_") or f"_{self.task_id}_" in filename:
                        filepath = os.path.join(self.screenshots_dir, filename)
                        os.remove(filepath)
                        print(f"🗑️ 清理截图: {filename}")
                print("✅ 所有截图已清理")
        except Exception as e:
            print(f"清理截图时出错: {e}")

    def capture_screen(self, description=""):
        """捕获屏幕并保存"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.screenshots_dir}/screen_{self.task_id}_{timestamp}.png"

        try:
            screenshot = self.screen_analyzer.capture_screen(filename)
            self.screenshot_paths.append(filename)

            with open(filename, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8'), filename, screenshot
        except Exception as e:
            print(f"截图失败: {e}")
            # 创建黑色占位图
            fallback_img = Image.new('RGB', (100, 100), color='black')
            fallback_img.save(filename)
            with open(filename, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8'), filename, fallback_img

    def get_action_history_context(self, max_history=8):
        """获取最近的操作历史作为上下文"""
        if not self.action_history:
            return "暂无操作历史"

        context_lines = ["=== 最近操作历史 ==="]
        for i, record in enumerate(self.action_history[-max_history:]):
            status = "✓" if record.success else "✗" if record.success is False else "?"
            retry_info = f"[重试{record.retry_count}次] " if record.retry_count > 0 else ""
            context_lines.append(f"{i + 1}. {status} {retry_info}[{record.action_type}] - {record.thought[:50]}...")
            if record.result_info:
                context_lines.append(f"   结果: {record.result_info[:50]}")

        return "\n".join(context_lines)

    def should_retry(self, action_type, parameters):
        """判断是否应该重试当前操作"""
        # 获取当前步骤的重试次数
        step_key = f"{action_type}_{hash(str(parameters))}"
        retry_count = self.retry_count.get(step_key, 0)

        if retry_count >= self.max_retries:
            print(f"⚠️ 达到最大重试次数 ({retry_count}/{self.max_retries})")
            return False

        # 检查连续失败次数
        if self.consecutive_failures >= self.max_retries:
            print(f"⚠️ 连续失败次数过多 ({self.consecutive_failures}/{self.max_retries})")
            return False

        return True

    def mark_retry(self, action_type, parameters):
        """标记当前操作为重试"""
        step_key = f"{action_type}_{hash(str(parameters))}"
        current_count = self.retry_count.get(step_key, 0) + 1
        self.retry_count[step_key] = current_count
        return current_count

    def analyze_and_decide(self, user_instruction: str, base64_image: str, screenshot=None) -> Dict[str, Any]:
        """分析屏幕状态并决策下一步操作"""
        # 获取操作历史上下文
        history_context = self.get_action_history_context()

        # 构建提示
        messages = [
            {
                "role": "system",
                "content": SYSTEM_PROMPT + f"""

                        当前是第 {self.step_count + 1} 步
                        连续失败次数: {self.consecutive_failures}
                        {history_context}

                        屏幕尺寸: {self.screen_analyzer.get_screen_size()}
                        返回桌面快捷键: Win+D

                        **特别提醒：**
                        - **打开应用时，必须先返回桌面，再查找并点击图标！**
                        - 操作顺序：RETURN_TO_DESKTOP → 查找任务栏图标 → 查找桌面图标 → 命令行
                        - 分析截图时，先看底部，再看中间，最后看其他区域
                        - 任务栏图标通常较小，紧贴屏幕边缘
                        """
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{base64_image}"
                        }
                    },
                    {
                        "type": "text",
                        "text": f"""用户指令: {user_instruction}

        请严格遵循观察->决策->执行->观察的流程：
        **第一步：判断是否需要打开应用**
        1. 如果需要打开应用（如微信），严格按照以下顺序操作：
           a. 首先执行RETURN_TO_DESKTOP返回桌面
           b. 然后在桌面环境下查找任务栏图标
           c. 最后查找桌面图标
        2. 分析当前状态与目标的关系
        3. 决策一个最合适的原子操作
        4. 输出JSON格式的操作指令

        **重要提示：**
        - **打开应用时，必须先返回桌面！** 使用RETURN_TO_DESKTOP操作
        - 分析截图时，**首先关注屏幕底部边缘的任务栏区域**
        - 如果当前界面混乱或找不到目标，可以先用RETURN_TO_DESKTOP返回桌面（使用Win+D）
        - 每个操作最多重试{self.max_retries}次
        - 如果是微信发送消息任务，请从用户指令中提取联系人和消息内容，并填充到SEND操作的参数中
        """
                    }
                ]
            }
        ]

        try:
            response = client.chat.completions.create(
                model="gui-plus",
                messages=messages,
                extra_body={"vl_high_resolution_images": True},
                temperature=0.1,  # 降低随机性，提高稳定性
                max_tokens=1000
            )

            result_text = response.choices[0].message.content
            return self._extract_json_from_text(result_text)

        except Exception as e:
            print(f"模型调用失败: {e}")
            return {
                "thought": "模型调用失败，等待后重试",
                "action": "WAIT",
                "parameters": {"wait_time": 1}
            }

    def _extract_json_from_text(self, text):
        """从文本中提取JSON"""
        try:
            # 尝试直接解析
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取JSON
            try:
                start = text.find('{')
                end = text.rfind('}') + 1
                if start >= 0 and end > start:
                    json_str = text[start:end]
                    return json.loads(json_str)
            except:
                pass

        # 默认等待
        return {
            "thought": "无法解析响应，等待后重试",
            "action": "WAIT",
            "parameters": {"wait_time": 1}
        }

    def execute_action(self, action_result: Dict[str, Any], prev_screenshot) -> Tuple[bool, str]:
        """执行操作并返回结果"""
        action = action_result.get("action", "").upper()
        params = action_result.get("parameters", {})
        thought = action_result.get("thought", "")

        print(f"\n🤔 思考: {thought}")
        print(f"🎯 执行: {action}")

        # 检查是否应该重试
        if action not in ["FINISH", "FAIL", "RETRY"]:
            if not self.should_retry(action, params):
                return False, f"操作{action}达到最大重试次数，任务失败"

        try:
            if action == "CLICK":
                x, y = params.get("x", 0), params.get("y", 0)
                # 验证坐标是否在屏幕范围内
                screen_width, screen_height = self.screen_analyzer.get_screen_size()
                if 0 <= x < screen_width and 0 <= y < screen_height:
                    pyautogui.moveTo(x, y, duration=0.05)
                    pyautogui.click()
                    result_info = f"点击 ({x}, {y})"
                else:
                    result_info = f"坐标({x}, {y})超出屏幕范围({screen_width}x{screen_height})"
                    return False, result_info

            elif action == "DOUBLE_CLICK":
                x, y = params.get("x", 0), params.get("y", 0)
                screen_width, screen_height = self.screen_analyzer.get_screen_size()
                if 0 <= x < screen_width and 0 <= y < screen_height:
                    pyautogui.moveTo(x, y, duration=0.05)
                    pyautogui.doubleClick()
                    result_info = f"双击 ({x}, {y})"
                else:
                    result_info = f"坐标({x}, {y})超出屏幕范围"
                    return False, result_info

            elif action == "RIGHT_CLICK":
                x, y = params.get("x", 0), params.get("y", 0)
                screen_width, screen_height = self.screen_analyzer.get_screen_size()
                if 0 <= x < screen_width and 0 <= y < screen_height:
                    pyautogui.moveTo(x, y, duration=0.05)
                    pyautogui.rightClick()
                    result_info = f"右键点击 ({x}, {y})"
                else:
                    result_info = f"坐标({x}, {y})超出屏幕范围"
                    return False, result_info

            elif action == "TYPE":
                text = params.get("text", "")
                use_paste = params.get("use_paste", len(text) > 20)  # 长文本自动使用粘贴

                if use_paste:
                    pyperclip.copy(text)
                    time.sleep(0.1)
                    pyautogui.hotkey('ctrl', 'v')
                    result_info = f"粘贴文本: {text[:30]}..."
                else:
                    pyautogui.write(text)
                    result_info = f"输入文本: {text[:30]}..."

            elif action == "PRESS":
                keys = params.get("keys", [])
                if isinstance(keys, str):
                    keys = [keys]

                if len(keys) == 1:
                    pyautogui.press(keys[0])
                else:
                    pyautogui.hotkey(*keys)
                result_info = f"按键: {keys}"

            elif action == "RUN_CMD":
                command = params.get("command", "")
                if command:
                    try:
                        # 使用Popen而不是run，避免阻塞
                        process = subprocess.Popen(
                            command,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            start_new_session=True  # 创建新会话，避免阻塞
                        )
                        # 等待一段时间检查进程状态
                        time.sleep(1)
                        if process.poll() is None:
                            result_info = f"命令已启动: {command}"
                        else:
                            stdout, stderr = process.communicate(timeout=2)
                            if process.returncode == 0:
                                result_info = f"执行命令成功: {command}"
                            else:
                                result_info = f"命令执行失败: {stderr.decode()[:100]}"
                    except Exception as e:
                        result_info = f"命令执行异常: {e}"
                        return False, result_info
                else:
                    result_info = "未提供命令"
                    return False, result_info

            elif action == "SEARCH_SCREEN":
                # 搜索操作本身不执行具体动作，只是告诉模型搜索屏幕
                result_info = f"搜索: {params.get('search_term', '')}"

            elif action == "WAIT":
                wait_time = min(params.get("wait_time", 1), 10)  # 限制最大等待时间
                print(f"⏳ 等待 {wait_time} 秒...")
                time.sleep(wait_time)
                result_info = f"等待 {wait_time} 秒"

            elif action == "RETURN_TO_DESKTOP":
                # 返回桌面：使用Win+D快捷键
                time.sleep(1)
                pyautogui.hotkey('win', 'd')
                time.sleep(0.8)  # 稍微多等待一点时间，确保桌面完全显示
                result_info = "返回桌面 (Win+D)"

                # 返回桌面后，最好再等待一下让桌面稳定
                time.sleep(0.3)

            elif action == "SUPER_SEARCH":
                # 按Super键（Windows键）打开搜索
                pyautogui.press('win')
                time.sleep(0.8)  # 等待搜索界面打开
                result_info = "打开应用搜索"

            elif action == "SEND":
                # 执行微信发送消息操作
                contactor = params.get("contactor", "")
                content = params.get("content", "")

                if not contactor or not content:
                    result_info = "SEND操作缺少contactor或content参数"
                    return False, result_info

                result_info = self._send_wechat_message(contactor, content)
                return False, result_info  # 返回False表示结束循环

            elif action == "FINISH":
                result_info = params.get("message", "任务完成")
                self.consecutive_failures = 0  # 重置连续失败计数
                return False, result_info  # 返回False表示结束循环

            elif action == "FAIL":
                result_info = params.get("reason", "任务失败")
                return False, result_info  # 返回False表示结束循环

            elif action == "RETRY":
                # 重试标记，由主循环处理
                result_info = "请求重试当前步骤"
                return True, result_info  # 返回True继续循环

            else:
                result_info = f"未知操作类型: {action}"
                return False, result_info

            # 检查屏幕变化
            time.sleep(0.5)  # 等待界面响应
            new_screenshot = self.screen_analyzer.capture_screen()
            screen_change, _ = self.screen_analyzer.compare_screens(prev_screenshot, new_screenshot)

            # 创建记录
            retry_count = self.retry_count.get(f"{action}_{hash(str(params))}", 0)
            record = ActionRecord(
                timestamp=datetime.now(),
                action_type=action,
                parameters=params,
                thought=thought,
                success=True,
                screen_change=screen_change,
                result_info=result_info,
                retry_count=retry_count
            )
            self.action_history.append(record)

            # 重置连续失败计数
            if action not in ["WAIT", "SEARCH_SCREEN", "RETURN_TO_DESKTOP"]:
                self.consecutive_failures = 0

            return True, result_info  # 返回True表示继续循环

        except Exception as e:
            error_msg = f"执行失败: {str(e)}"
            print(f"❌ {error_msg}")
            traceback.print_exc()

            # 增加连续失败计数
            self.consecutive_failures += 1

            # 标记重试
            self.mark_retry(action, params)

            retry_count = self.retry_count.get(f"{action}_{hash(str(params))}", 0)
            record = ActionRecord(
                timestamp=datetime.now(),
                action_type=action,
                parameters=params,
                thought=thought,
                success=False,
                screen_change=False,
                result_info=error_msg,
                retry_count=retry_count
            )
            self.action_history.append(record)

            # 如果连续失败太多，建议返回桌面
            if self.consecutive_failures >= 2:
                print("⚠️ 连续失败，建议返回桌面重新开始")

            return True, error_msg  # 继续循环尝试

    def _send_wechat_message(self, contactor: str, content: str) -> str:
        """执行微信发送消息的高效操作"""
        print(f"💬 发送微信消息: 给 {contactor} 发送 '{content}'")

        try:
            # 1. 搜索联系人
            pyautogui.hotkey('ctrl', 'f')
            time.sleep(0.8)

            # 2. 输入联系人
            pyperclip.copy(contactor)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(1.5)  # 增加等待时间，确保搜索完成

            # 3. 选择第一个结果
            pyautogui.hotkey('enter')
            time.sleep(1)

            # 4. 输入消息
            pyperclip.copy(content)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.8)

            # 5. 发送消息
            pyautogui.hotkey('enter')
            time.sleep(1)

            return f"成功发送消息给 {contactor}: {content}"

        except Exception as e:
            return f"发送消息失败: {str(e)}"


def ui_automation_tool(user_instruction: str) -> str:
    """
    执行UI自动化任务的主函数

    Args:
        user_instruction: 用户指令，例如 "打开微信并给张三发送消息你好"

    Returns:
        任务执行结果报告
    """
    print("🚀 AI智能视觉操作代理启动")
    print(f"📝 任务指令: {user_instruction}")
    print("-" * 50)

    # 生成唯一任务ID
    task_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    executor = TaskExecutor(task_id)
    final_status = "未知"

    try:
        # 初始观察
        print("📸 观察初始屏幕状态...")
        base64_img, _, screenshot = executor.capture_screen("initial")

        while executor.step_count < executor.max_steps:
            executor.step_count += 1
            print(f"\n📋 第 {executor.step_count}/{executor.max_steps} 步")

            # 1. 观察屏幕并决策
            print("🧠 分析屏幕并决策...")
            action_result = executor.analyze_and_decide(user_instruction, base64_img, screenshot)

            # 2. 执行操作
            continue_loop, result_info = executor.execute_action(action_result, screenshot)

            print(f"📊 结果: {result_info}")

            # 检查是否需要结束
            action = action_result.get("action", "")
            if action in ["FINISH", "FAIL"] or not continue_loop:
                if action == "FINISH":
                    final_status = "成功完成"
                elif action == "FAIL":
                    final_status = "任务失败"
                else:
                    final_status = "执行中断"
                break

            # 3. 观察反馈（重新截图）
            print("📸 观察操作后的屏幕...")
            base64_img, _, screenshot = executor.capture_screen(f"step_{executor.step_count}")

            # 短暂等待
            time.sleep(0.3)
        else:
            final_status = "达到最大步数"

    except KeyboardInterrupt:
        final_status = "用户中断"
        print("\n⏹️ 用户中断执行")
    except Exception as e:
        final_status = f"异常中断: {e}"
        print(f"❌ 发生异常: {e}")
        traceback.print_exc()
    finally:
        # 无论成功还是异常，都清理截图
        executor.cleanup_screenshots()

    # 生成报告
    report_lines = []
    report_lines.append(f"{'=' * 50}")
    report_lines.append(f"📋 任务执行报告")
    report_lines.append(f"{'=' * 50}")
    report_lines.append(f"指令: {user_instruction}")
    report_lines.append(f"任务ID: {task_id}")
    report_lines.append(f"最终状态: {final_status}")
    report_lines.append(f"总步数: {executor.step_count}")

    if executor.action_history:
        successful_actions = [a for a in executor.action_history if a.success is True]
        success_rate = len(successful_actions) / len(executor.action_history) * 100
        report_lines.append(f"成功率: {success_rate:.1f}%")

        # 统计重试次数
        total_retries = sum(a.retry_count for a in executor.action_history)
        if total_retries > 0:
            report_lines.append(f"总重试次数: {total_retries}")

    return "\n".join(report_lines)


def cleanup_old_screenshots(keep_last=10):
    """清理旧的截图文件，只保留最近的一些"""
    screenshots_dir = "screenshots"
    if not os.path.exists(screenshots_dir):
        return

    try:
        # 获取所有截图文件
        all_files = [f for f in os.listdir(screenshots_dir) if f.endswith('.png')]

        if len(all_files) > keep_last:
            # 按时间排序
            all_files.sort(key=lambda x: os.path.getmtime(os.path.join(screenshots_dir, x)))

            # 删除旧的
            for file_to_delete in all_files[:-keep_last]:
                os.remove(os.path.join(screenshots_dir, file_to_delete))
                print(f"🗑️ 清理旧截图: {file_to_delete}")

    except Exception as e:
        print(f"清理截图时出错: {e}")


@tool
def ui_automator(
    user_instruction: Annotated[str, "用户的UI操作指令，例如'打开微信并给张三发送消息你好'"]
) -> HumanMessage:
    """
    自动执行用户的UI操作任务，如打开应用、点击按钮、输入文本、发送微信消息等。
    该工具通过视觉识别屏幕内容，模拟鼠标键盘操作完成任务。
    注意：此工具需要在有图形界面的环境中运行，且需要DASHSCOPE_API_KEY环境变量。
    """
    try:
        result = ui_automation_tool(user_instruction)
        return HumanMessage(content=result)
    except Exception as e:
        error_msg = f"UI自动化任务执行失败: {repr(e)}"
        return HumanMessage(content=error_msg)
