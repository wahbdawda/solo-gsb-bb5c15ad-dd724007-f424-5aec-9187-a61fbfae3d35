"""示例数据（典型 Harris 矩阵式地层）。"""
from __future__ import annotations

SAMPLE_UNITS = [
    ("U1", "生土层", "未经扰动的自然堆积"),
    ("U2", "早期房基面", "新石器时代房址踩踏面"),
    ("U3", "早期垫土层", "与房基面同期垫压"),
    ("U4", "灰坑 H1", "打破房基面的生活垃圾坑"),
    ("U5", "文化层中段", "覆盖早期遗迹的文化堆积"),
    ("U6", "晚期墓葬 M1", "竖穴土坑墓，打破中段文化层"),
    ("U7", "耕土层", "近现代表土"),
]

# (kind, source, target) —— 语义见 kind 字面
SAMPLE_RELATIONS = [
    ("earlier_than", "U1", "U2"),
    ("intersects", "U2", "U3"),
    ("earlier_than", "U2", "U4"),
    ("earlier_than", "U3", "U5"),
    ("earlier_than", "U4", "U5"),
    ("earlier_than", "U5", "U6"),
    ("earlier_than", "U6", "U7"),
]
