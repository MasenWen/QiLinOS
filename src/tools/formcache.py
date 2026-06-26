import json
import os
import asyncio
from datetime import datetime
from typing import Dict, Any
# 定义缓存文件路径
CACHE_FILE_PATH = "cache_info.json"


class Form_People_info:
    def __init__(self):
        self.dict = self.load_cache()

    def load_cache(self) -> Dict[str, Any]:
        """从文件加载缓存数据"""
        try:
            if os.path.exists(CACHE_FILE_PATH):
                with open(CACHE_FILE_PATH, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载缓存文件失败: {e}")
        return {}
    
    def save_cache(self, cache_data: Dict[str, Any]) -> None:
        """保存缓存数据到文件"""
        try:
            # 添加时间戳
            cache_data['last_updated'] = datetime.now().isoformat()
            
            with open(CACHE_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存缓存文件失败: {e}")
    def is_km_updated(self) -> bool:
        return self.dict.get("km_updated", True)
    
    def people_info(self) -> str:
        return self.dict.get("people_info", "None")
    
    def set_km_updated(self) -> None:
        """手动更新知识库缓存"""
        self.dict["km_updated"] = True
        self.save_cache(self.dict)

    def set_people_info(self, people_info) -> None:
        """手动更新知识库缓存"""
        self.dict["people_info"] = people_info
        self.dict["km_updated"] = False
        self.save_cache(self.dict)

