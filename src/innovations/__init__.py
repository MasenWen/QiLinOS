"""创新算法独立模块（贝叶斯个性化更新 + 高维稀疏检索）。

对应技术手册第六章与第八章 8.4 两项创新：
- :mod:`~innovations.bayes_personalization`：Beta--Bernoulli 个性化记忆更新的可计算实现；
- :mod:`~innovations.sparse_sketch`：稀疏表示 + 随机投影候选召回的可计算实现。

两个模块均为纯计算、无副作用，计算本身可独立运行与测试。工程侧在**内存充足时**接入记忆引擎检索链路：
候选扩展（稀疏草图）与先验平滑（贝叶斯混合）见 ``src/memory_engine/optimization.py``，
启用判定与回落见 ``src/memory_engine/resource_gate.py``；内存不足时自动回到既有精确路径。
模块内的函数/公式命名与手册符号一致，便于逐项核对。
"""
