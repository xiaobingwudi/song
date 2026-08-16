# -*- coding: utf-8 -*-
"""中文日期范围选择器（Streamlit 自定义组件）。

替代 st.date_input 英文显示的问题，提供中文的年月日与星期显示。
组件接收 min_date / max_date / value（(start,end) 两个 ISO 日期字符串），
返回选中的 (start, end) 元组（ISO 字符串）。
"""
import streamlit.components.v1 as components
import pathlib

_build = str(pathlib.Path(__file__).parent / "frontend")

cn_date_range = components.declare_component(
    "cn_date_range",
    path=_build,
)
