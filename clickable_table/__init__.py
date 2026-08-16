# -*- coding: utf-8 -*-
"""可点击斑马纹表格组件。

替代 st.dataframe（canvas 无法做斑马纹）。支持：
- 斑马纹底色、0.5cm 行高
- 点击行回传选中行的 订单主号 / 送货单号
- 列宽自适应
"""
import streamlit.components.v1 as components
import pathlib

_build = str(pathlib.Path(__file__).parent / "frontend")

clickable_table = components.declare_component(
    "clickable_table",
    path=_build,
)
