"""创新算法独立模块（贝叶斯个性化更新 + 高维稀疏检索）。

对应技术手册第六章与第八章 8.4 两项创新：
- :mod:`~innovations.bayes_personalization`：Beta--Bernoulli 个性化记忆更新的可计算实现；
- :mod:`~innovations.sparse_sketch`：稀疏表示 + 随机投影候选召回的可计算实现。

两个模块均为纯计算、无副作用、不依赖主系统（不接入 webchat/记忆引擎链路），
可独立运行与测试。模块内的函数/公式命名与手册符号一致，便于逐项核对。
"""
