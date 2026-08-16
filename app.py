# -*- coding: utf-8 -*-
"""

"""
import base64
import calendar as _cal
import html
import io
import json
import os
import re
import shutil
import time
import urllib.parse
from datetime import date, datetime
from pathlib import Path

import requests

import pandas as pd
import streamlit as st

import parser as pr
import qn
import registry as rg
from cn_date_range import cn_date_range
from clickable_table import clickable_table
from filter_bar import filter_bar

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = os.path.join(BASE_DIR, "data")
PHOTO_ROOT = os.path.join(DATA_DIR, "photos")
NOTES_DIR = os.path.join(DATA_DIR, "notes")
OPTIONS_PATH = os.path.join(DATA_DIR, "options.json")

os.makedirs(PHOTO_ROOT, exist_ok=True)
os.makedirs(NOTES_DIR, exist_ok=True)

IMG_TYPES = ["jpg", "jpeg", "png", "bmp", "webp"]
_IMG_CACHE = {}
PAGE_SIZE = 30  # 默认每页行数（可在管理选项自定义）


def _cal_shift(dy, dm):
    y, m = st.session_state.cal_ym
    nm = m + dm
    ny = y + (nm - 1) // 12
    nm = (nm - 1) % 12 + 1
    if dy:
        ny += dy
    st.session_state.cal_ym = (ny, nm)


def _render_calendar(date_set):
    today = date.today()
    if "cal_ym" not in st.session_state:
        st.session_state.cal_ym = (today.year, today.month)
    y, m = st.session_state.cal_ym
    # 头部：◀ 年月 ▶（统一小箭头，垂直居中）
    top = st.columns([1, 4, 1])
    with top[0]:
        st.button("◀", key=f"cp_{y}_{m}", on_click=_cal_shift, args=(0, -1))
    with top[1]:
        st.markdown(f'<div class="side-cal-head" style="justify-content:center;"><span class="ym">{y}年{m}月</span></div>', unsafe_allow_html=True)
    with top[2]:
        st.button("▶", key=f"cn_{y}_{m}", on_click=_cal_shift, args=(0, 1))

    heads = "".join(
        f"<td style='color:#9aa3b5;font-size:11px;font-weight:600;text-align:center;padding:2px 0;'>{w}</td>"
        for w in ["一", "二", "三", "四", "五", "六", "日"])
    body = ""
    for week in _cal.Calendar(firstweekday=0).monthdatescalendar(y, m):
        row = ""
        for d in week:
            if d.month != m:
                row += "<td></td>"
            else:
                ds = d.isoformat()
                _bg = _col = _fw = ""
                if ds in date_set:
                    _bg = "background:#dbeafe;"  # 低饱和品牌蓝，视觉柔和
                    _col = "color:#1d4ed8;"
                    _fw = "font-weight:600;"
                elif ds == today.isoformat():
                    _col = "color:#2563eb;"
                    _fw = "font-weight:700;"
                else:
                    _col = "color:#b6bcc9;"
                row += (f"<td style='{_bg}{_col}{_fw}border-radius:6px;font-size:12px;text-align:center;"
                        f"height:22px;line-height:22px;padding:0;'>{d.day}</td>")
        body += f"<tr>{row}</tr>"
    st.markdown(
        "<style>"
        "table.side-cal{width:100%;border-collapse:collapse;table-layout:fixed;}"
        "table.side-cal td{width:14.28%;text-align:center;padding:0;white-space:nowrap;}"
        "</style>"
        f"<table class='side-cal'><tr>{heads}</tr>{body}</table>",
        unsafe_allow_html=True)


def _pick_date(ds):
    st.session_state.range = (date.fromisoformat(ds), date.fromisoformat(ds))
    st.session_state.page = 1


# ---------- 七牛云配置（从 Streamlit Secrets / 环境变量读取，绝不写死在代码） ----------
QN_ENABLED = True


def _cfg(key, default=""):
    """优先读取 Streamlit Secrets，其次环境变量，最后默认值。云端部署必须配置 Secrets。"""
    try:
        v = st.secrets.get(key)
        if v:
            return v
    except Exception:
        pass
    return os.environ.get(key, default)


QN_AK = _cfg("QN_AK", "")
QN_SK = _cfg("QN_SK", "")
QN_BUCKET = _cfg("QN_BUCKET", "")
QN_DOMAIN = _cfg("QN_DOMAIN", "")
QN_LEDGER_KEY = "ledger/台账.csv"  # 台账在七牛云的最新版本路径
QN_LEDGER_HIST_DIR = "ledger/history"  # 台账历史版本目录（七牛云）
QN_OPTIONS_KEY = "ledger/options.json"  # 选项配置（含访客密码）在七牛云的路径
ADMIN_PASSWORD = _cfg("ADMIN_PASSWORD", "888888")  # 云端务必通过 Secrets 配置，勿用默认值
VISITOR_PASSWORD = _cfg("VISITOR_PASSWORD", "666666")  # 云端务必通过 Secrets 配置

# 七牛状态：库是否安装 / 密钥是否配置 / 是否完全可用（两条件都满足）
QINIU_LIB = False
try:
    import qiniu  # noqa
    QINIU_LIB = True
except ImportError:
    QINIU_LIB = False
QINIU_CONFIGURED = bool(QN_AK and QN_SK and QN_BUCKET and QN_DOMAIN)
QINIU_AVAILABLE = QINIU_LIB and QINIU_CONFIGURED
QINIU_HINT = (
    "" if QINIU_AVAILABLE
    else ("⚠ 未配置七牛密钥，请在 Streamlit Settings→Secrets 填写 QN_AK/QN_SK 等" if QINIU_CONFIGURED is False and QINIU_LIB
          else ("⚠ 未安装 qiniu 库（requirements.txt 已含，请确认安装）" if QINIU_CONFIGURED else "⚠ 未安装 qiniu 库且未配置密钥"))
)


_GLOBAL_CSS = """<style>
  /* ============ 全局 ============ */
  .stApp{background:#f0f2f7;font-family:-apple-system,'PingFang SC','Microsoft YaHei',sans-serif;}
  [data-testid="stHeader"]{display:none!important;height:0!important;min-height:0!important;position:absolute!important;}
  [data-testid="stToolbar"]{display:none!important;}
  [data-testid="stDecoration"]{display:none!important;}
  [data-testid="stAppDeployButton"]{display:none!important;}
  [data-testid="stMainMenu"], [data-testid="stMainMenuButton"]{display:none!important;}
  [data-testid="stMain"]{padding-top:0!important;margin-top:0!important;}
  .block-container{padding-top:0!important;padding-bottom:3rem;max-width:100%;}
  [data-testid="stMainBlockContainer"]{padding-top:0!important;margin-top:0!important;}
  h1{font-size:1.6rem;color:#1f2a44;font-weight:700;}
  h2,h3,h4{color:#1f2a44;}
  [data-testid="stCaptionContainer"]{color:#7a8497;}

  /* ============ 按钮：小且紧凑 ============ */
  .stButton>button{border-radius:8px;padding:.26rem .75rem;font-size:.86rem;font-weight:600;border:1px solid #d4d9e3;background:#fff;color:#333c4d;box-shadow:none;transition:all .15s;}
  .stButton>button:hover{border-color:#2563eb;color:#2563eb;background:#f7f9ff;}
  [data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"]{background:#2563eb;border-color:#2563eb;color:#fff;}
  [data-testid="stBaseButton-primary"]:hover, [data-testid="stBaseButton-primaryFormSubmit"]:hover{background:#1d4fd8;color:#fff;}
  [data-testid="stDownloadButton"]>button{border-radius:8px;padding:.26rem .75rem;font-size:.86rem;font-weight:600;border:1px solid #d4d9e3;background:#fff;color:#333c4d;}

  /* ============ 输入控件 ============ */
  .stTextInput input,.stDateInput input,.stNumberInput input{border-radius:8px;border-color:#d4d9e3;font-size:.88rem;}
  .stSelectbox>div>div{border-radius:8px;border-color:#d4d9e3;font-size:.88rem;}
  .stNumberInput button{font-size:.8rem;}
  .stTextInput input:focus,.stDateInput input:focus,.stSelectbox>div>div:focus-within{border-color:#2563eb;box-shadow:0 0 0 2px rgba(37,99,235,.12);}
  label[data-testid="stWidgetLabel"]{font-size:.82rem;color:#5b6577;}

  /* ============ 卡片容器 ============ */
  [data-testid="stVerticalBlockBorderWrapper"]{background:#fff;border:1px solid #e7eaf1!important;border-radius:14px;box-shadow:0 1px 4px rgba(16,24,40,.05);}

  /* ============ 侧边栏 ============ */
  [data-testid="stSidebar"]{background:#ffffff;border-right:1px solid #e6e9f0;width:232px!important;}
  /* 隐藏展开时的折叠箭头，但保留收起后的展开按钮，确保侧边栏始终可恢复 */
  [data-testid="stSidebarCollapseButton"]{display:none!important;}
  [data-testid="stSidebar"]{display:block!important;}
  [data-testid="stSidebarCollapsedControl"]{padding:6px;border-radius:8px;background:#fff;border:1px solid #e2e6ef;}
  [data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding:1rem .9rem;}
  [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p{color:#5b6577;}
  /* 导航 radio 胶囊 */
  [data-testid="stSidebar"] .stRadio>div[role="radiogroup"]{gap:.18rem;flex-direction:column;}
  [data-testid="stSidebar"] .stRadio label>div:first-child{display:none;}
  [data-testid="stSidebar"] .stRadio label{padding:.5rem .75rem;border-radius:9px;width:100%;margin:0;cursor:pointer;}
  [data-testid="stSidebar"] .stRadio label:hover{background:#f1f4fb;}
  [data-testid="stSidebar"] .stRadio label:has(input:checked){background:#eef3ff;color:#2563eb;font-weight:600;}
  /* 日历按钮（侧边栏）紧凑圆角 */
  [data-testid="stSidebar"] [data-testid="stBaseButton-secondary"]{width:100%;justify-content:center;padding:.5rem .75rem;border-radius:8px;font-size:.86rem;font-weight:500;}
  [data-testid="stSidebar"] [data-testid="stBaseButton-primary"]{width:100%;justify-content:center;padding:.5rem .75rem;border-radius:8px;font-size:.86rem;font-weight:600;}

  /* 筛选标签：统一协调 */
  .flt-label{font-size:.84rem;font-weight:600;color:#333c4d;white-space:nowrap;letter-spacing:.2px;}

  /* ============ 自定义组件 ============ */
  .sect-tag{display:inline-block;background:#eef3ff;color:#2563eb;font-size:.72rem;font-weight:600;padding:.18rem .5rem;border-radius:6px;letter-spacing:.4px;}
  .page-head{display:flex;align-items:center;gap:.6rem;margin-bottom:.2rem;}
  .page-head h1{margin:0;}
  .page-sub{color:#7a8497;font-size:.88rem;margin-bottom:1rem;}
  .stat{background:#fff;border:1px solid #e7eaf1;border-radius:14px;padding:1rem 1.1rem;box-shadow:0 1px 4px rgba(16,24,40,.05);display:flex;flex-direction:column;}
  .stat .row{display:flex;align-items:center;justify-content:space-between;}
  .stat .ico{font-size:1.5rem;}
  .stat .num{font-size:1.7rem;font-weight:700;color:#1f2a44;line-height:1.05;margin-top:.4rem;}
  .stat .lab{font-size:.8rem;color:#7a8497;margin-top:.35rem;}
  /* ============ 侧边栏（统一品牌蓝 / 对齐 / 间距规范） ============ */
  [data-testid="stSidebar"]{background:#f7f8fb;}
  [data-testid="stSidebar"] [data-testid="stSidebarContent"]{padding:.9rem .75rem;}
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"]{padding-top:0;}
  /* 品牌区 */
  .side-brand{display:flex;align-items:center;gap:.7rem;padding:0 .1rem .85rem;border-bottom:1px solid #eceef4;margin:0 0 .8rem;}
  .side-brand .logo{width:38px;height:38px;border-radius:10px;background:linear-gradient(135deg,#2563eb,#3b82f6);display:flex;align-items:center;justify-content:center;color:#fff;font-size:1.12rem;flex:none;box-shadow:0 2px 6px rgba(37,99,235,.22);}
  .side-brand .t{font-weight:700;font-size:1rem;color:#1f2a44;line-height:1.15;}
  .side-brand .s{font-size:.7rem;color:#8a93a6;margin-top:2px;}
  /* 状态卡片 */
  .side-status{background:#fff;border:1px solid #eceef4;border-radius:12px;padding:.7rem .8rem;margin:0 0 .85rem;box-shadow:0 1px 3px rgba(16,24,40,.04);}
  .side-status .badges{display:flex;align-items:center;gap:.4rem;flex-wrap:wrap;}
  .side-badge{display:inline-flex;align-items:center;height:22px;padding:0 .55rem;border-radius:6px;font-size:.72rem;font-weight:600;white-space:nowrap;}
  .side-badge-admin{background:#eef3ff;color:#2563eb;}
  .side-badge-visitor{background:#f1f3f6;color:#6b7280;}
  .side-badge-qn{background:#eef3ff;color:#2563eb;}
  .side-badge-qn-warn{background:#fff4e5;color:#d97706;}
  .side-sync{font-size:.73rem;color:#5b6577;margin-top:.5rem;padding-top:.45rem;border-top:1px dashed #eef0f5;display:flex;align-items:center;gap:.3rem;}
  /* 分组标题 */
  .side-sec-title{font-size:.7rem;font-weight:700;color:#a2abbd;letter-spacing:.08em;padding:0 .2rem .4rem;}
  /* 导航按钮 */
  [data-testid="stSidebar"] .stButton > button{width:100%;justify-content:flex-start;background:#fff;border:1px solid #eceef4;border-radius:9px;color:#334155;padding:.46rem .8rem;font-size:.86rem;font-weight:500;box-shadow:none;margin-bottom:.32rem;}
  [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"]{background:#fff;border:1px solid #eceef4;color:#334155;}
  [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-secondary"]:hover{background:#eef3ff;border-color:#c9d9ff;color:#2563eb;}
  [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]{background:#2563eb !important;border-color:#2563eb !important;color:#fff !important;box-shadow:0 2px 8px rgba(37,99,235,.25)!important;}
  [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"]:hover{background:#1d4fd8 !important;color:#fff !important;}
  [data-testid="stSidebar"] .stButton > button p{font-size:.86rem;font-weight:500;}
  [data-testid="stSidebar"] .stButton > button[data-testid="stBaseButton-primary"] p{font-weight:600;}
  /* 日历卡片 */
  .side-cal-card{background:#fff;border:1px solid #eceef4;border-radius:12px;padding:.75rem .7rem .8rem;box-shadow:0 1px 3px rgba(16,24,40,.04);}
  .side-cal-title{font-size:.85rem;font-weight:700;color:#1f2a44;display:flex;align-items:center;gap:.35rem;}
  .side-cal-hint{font-size:.69rem;color:#9aa3b5;margin:.15rem 0 .5rem;}
  .side-cal-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:.4rem;}
  .side-cal-head .ym{font-size:.84rem;font-weight:600;color:#1f2a44;}
  .side-cal-arrow{width:24px;height:24px;border-radius:6px;background:#f1f3f7;border:none;color:#556;font-size:.72rem;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;padding:0;}
  .side-cal-arrow:hover{background:#e2e8f2;color:#2563eb;}
  /* 退出按钮 */
  [data-testid="stSidebar"] .stButton > button.side-exit{background:#fff;border:1px solid #f4c7c7;color:#dc2626;}
  [data-testid="stSidebar"] .stButton > button.side-exit:hover{background:#fef2f2;border-color:#fca5a5;color:#b91c1c;}
  .side-foot{margin-top:.85rem;padding-top:.75rem;border-top:1px solid #eceef4;font-size:.68rem;color:#b3bccd;text-align:center;line-height:1.5;}
  /* 侧边栏内边框容器（日历卡片）里的箭头按钮缩小 */
  [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button{padding:.15rem .3rem;font-size:.72rem;margin-bottom:0;min-height:0;}
  [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"] .stButton > button:hover{background:#e2e8f2;color:#2563eb;border-color:#c9d9ff;}
  /* 退出按钮：与导航统一为白色卡片，弱化强调（避免误伤选中按钮） */
  .login-card{max-width:380px;margin:6vh auto 0;background:#fff;border:1px solid #e7eaf1;border-radius:18px;padding:2.2rem 2rem;box-shadow:0 12px 40px rgba(16,24,40,.08);text-align:center;}
  .login-card .logo{width:56px;height:56px;border-radius:16px;background:linear-gradient(135deg,#2563eb,#3b82f6);display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:1.7rem;box-shadow:0 4px 12px rgba(37,99,235,.3);}
  .login-card h2{margin:.9rem 0 .2rem;color:#1f2a44;font-size:1.3rem;}
  .login-card .tip{color:#7a8497;font-size:.84rem;margin-bottom:1.4rem;}
  .login-hint{margin-top:1.1rem;font-size:.8rem;color:#9aa3b2;background:#f7f8fb;border-radius:8px;padding:.6rem .8rem;text-align:left;line-height:1.7;}
  form[data-testid="stForm"]{background:#fff;border:1px solid #e7eaf1;border-radius:18px;padding:1.9rem 1.6rem;box-shadow:0 12px 40px rgba(16,24,40,.08);}
  /* 表格：行距约 0.6cm，紧凑 */
  [data-testid="stDataFrame"] [data-testid="stDataFrameCell"]{font-size:.78rem;padding-top:1px!important;padding-bottom:1px!important;min-height:23px;}
  [data-testid="stDataFrame"] [data-testid="stDataFrameHeader"] [data-testid="stDataFrameCell"]{font-size:.78rem;padding-top:4px!important;padding-bottom:4px!important;}
  [data-testid="stDataFrame"]{font-size:.78rem;}
</style>"""

def _stat_card(ico, num, lab, key_uniq):
    # 紧凑横向卡片：图标 + 数字 + 标签同一行，高度小且统一
    return (f'<div style="background:#fff;border:1px solid #e7eaf1;border-radius:10px;padding:.3rem .55rem;'
            f'display:flex;align-items:center;gap:.5rem;box-shadow:0 1px 3px rgba(16,24,40,.04);height:100%;box-sizing:border-box;">'
            f'<div style="font-size:1rem;flex:0 0 auto;">{ico}</div>'
            f'<div style="min-width:0;"><div style="font-size:1.02rem;font-weight:700;color:#1f2a44;line-height:1;white-space:nowrap;">{num}</div>'
            f'<div style="font-size:.64rem;color:#7a8497;margin-top:.1rem;white-space:nowrap;">{lab}</div></div></div>')

def _page_head(title, sub):
    # 一行紧凑页头：标题 + 说明同行
    return (f'<div style="display:flex;align-items:baseline;gap:.7rem;margin-bottom:.15rem;">'
            f'<h1 style="margin:0;font-size:1.28rem;color:#1f2a44;">{title}</h1>'
            f'<span style="color:#7a8497;font-size:.8rem;">{sub}</span></div>')

def img_to_data_url(ref):
    if not ref:
        return ""
    ref = str(ref)
    if ref.startswith("http://") or ref.startswith("https://") or ref.startswith("data:"):
        return ref
    if ref in _IMG_CACHE:
        return _IMG_CACHE[ref]
    if not os.path.exists(ref):
        return ""
    try:
        with open(ref, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        ext = os.path.splitext(ref)[1].lower().lstrip(".")
        mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png",
                "bmp": "bmp", "webp": "webp"}.get(ext, "jpeg")
        url = f"data:image/{mime};base64,{b64}"
        _IMG_CACHE[ref] = url
        return url
    except Exception:
        return ""


def save_uploaded(uploaded_list, folder):
    os.makedirs(folder, exist_ok=True)
    saved = []
    for uf in (uploaded_list or []):
        if uf is None:
            continue
        p = os.path.join(folder, uf.name)
        with open(p, "wb") as f:
            f.write(uf.getbuffer())
        saved.append(p)
    return saved


def list_imgs_in(folder):
    if not os.path.isdir(folder):
        return []
    return [os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith(tuple(IMG_TYPES))]


_PHOTO_GRID_HTML = """<style>
  .grid{display:flex;flex-wrap:wrap;gap:10px;}
  .it{width:calc(__W__% - 10px);cursor:pointer;border:1px solid #e6e8eb;border-radius:8px;padding:4px;background:#fff;box-sizing:border-box;}
  .it:hover{box-shadow:0 2px 8px rgba(0,0,0,.15);}
  .it img{width:100%;height:130px;object-fit:cover;border-radius:6px;display:block;}
  .nm{font-size:11px;color:#666;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin-top:3px;}
  #lb{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;z-index:999999;align-items:center;justify-content:center;}
  #lbm{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);width:min(94vw,1300px);height:min(94vh,900px);background:#fff;border-radius:10px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 12px 48px rgba(0,0,0,.45);}
  #lbh{display:flex;align-items:center;justify-content:space-between;padding:8px 12px;background:#f7f8fa;border-bottom:1px solid #e6e8eb;cursor:move;user-select:none;flex:0 0 auto;}
  #lbn{font-size:13px;color:#333;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:55%;}
  .lbt{display:flex;align-items:center;gap:6px;}
  .lbt button{border:1px solid #d5d8dc;background:#fff;border-radius:6px;padding:3px 10px;font-size:13px;cursor:pointer;line-height:1.4;}
  .lbt button:hover{background:#eef1f5;}
  #lz{font-size:12px;color:#666;min-width:44px;text-align:center;}
  #lbw{flex:1;overflow:hidden;position:relative;background:#f2f3f5;display:flex;align-items:center;justify-content:center;}
  #lbi{max-width:100%;max-height:100%;object-fit:contain;transform-origin:center center;cursor:grab;user-select:none;-webkit-user-drag:none;transition:transform .06s ease;}
  #lbw.dragging #lbi{cursor:grabbing;}
  .lbtip{position:absolute;left:12px;bottom:10px;color:#888;font-size:12px;background:rgba(255,255,255,.75);padding:2px 8px;border-radius:4px;}
</style>
<div class="grid">__CARDS__</div>
<div id="lb"><div id="lbm">
  <div id="lbh"><span id="lbn"></span>
    <span class="lbt"><button onclick="lbZoom(-1)">−</button><span id="lz">100%</span><button onclick="lbZoom(1)">+</button><button onclick="lbReset()">复位</button><button onclick="lbClose()">✕</button></span>
  </div>
  <div id="lbw"><img id="lbi" draggable="false"><div class="lbtip">滚轮缩放 · 拖动图片平移 · 拖标题栏移动浮窗</div></div>
</div></div>
<script>
  var LB={x:0,y:0,s:1};
  function lbApply(){
    var i=document.getElementById('lbi');
    i.style.transform='translate('+LB.x+'px,'+LB.y+'px) scale('+LB.s+')';
    document.getElementById('lz').textContent=Math.round(LB.s*100)+'%';
  }
  var DEF_H=__H__;
  function lbFull(){
    if(window.frameElement){
      window.frameElement.style.height='95vh';
      window.frameElement.style.zIndex='999999';
      window.frameElement.style.position='relative';
    }
  }
  function lbRestore(){
    if(window.frameElement){
      window.frameElement.style.height=DEF_H+'px';
      window.frameElement.style.zIndex='';
      window.frameElement.style.position='';
    }
  }
  function openLB(u,n){
    document.getElementById('lbi').src=u;
    document.getElementById('lbn').textContent=n;
    LB={x:0,y:0,s:1};lbApply();
    document.getElementById('lb').style.display='flex';
    lbFull();
  }
  function lbClose(){document.getElementById('lb').style.display='none';lbRestore();}
  function lbZoom(d){LB.s=Math.min(12,Math.max(0.2,LB.s*(d>0?1.25:1/1.25)));lbApply();}
  function lbReset(){LB={x:0,y:0,s:1};lbApply();}
  (function(){
    var hd=document.getElementById('lbh'),m=document.getElementById('lbm'),off={x:0,y:0},sx=0,sy=0,drag=false;
    hd.addEventListener('mousedown',function(e){drag=true;sx=e.clientX;sy=e.clientY;hd.style.cursor='move';e.preventDefault();});
    document.addEventListener('mousemove',function(e){
      if(!drag)return;
      off.x+=e.clientX-sx;off.y+=e.clientY-sy;sx=e.clientX;sy=e.clientY;
      m.style.transform='translate(calc(-50% + '+off.x+'px), calc(-50% + '+off.y+'px))';
    });
    document.addEventListener('mouseup',function(){drag=false;hd.style.cursor='move';});
  })();
  (function(){
    var w=document.getElementById('lbw'),pan=false,px=0,py=0;
    w.addEventListener('wheel',function(e){e.preventDefault();LB.s=Math.min(12,Math.max(0.2,LB.s*(e.deltaY<0?1.15:1/1.15)));lbApply();},{passive:false});
    w.addEventListener('mousedown',function(e){if(e.target.id!=='lbi')return;pan=true;px=e.clientX;py=e.clientY;w.classList.add('dragging');});
    document.addEventListener('mousemove',function(e){if(!pan)return;LB.x+=e.clientX-px;LB.y+=e.clientY-py;px=e.clientX;py=e.clientY;lbApply();});
    document.addEventListener('mouseup',function(){pan=false;w.classList.remove('dragging');});
  })();
</script>"""


def _remote_to_data_url(url):
    """后端代理：拉取七牛 CDN 图片（http）转为 data URL 返回。
    规避 Streamlit Cloud https 页面加载 http 图片被浏览器拦截（mixed content）。
    按需拉取当前查看的一张，带内存缓存，不启动全量下载。"""
    if url in _IMG_CACHE:
        return _IMG_CACHE[url]
    try:
        r = requests.get(url, timeout=12)
        if r.status_code == 200 and r.content:
            b64 = base64.b64encode(r.content).decode()
            mime = r.headers.get("Content-Type", "image/jpeg") or "image/jpeg"
            data = f"data:{mime};base64,{b64}"
            _IMG_CACHE[url] = data
            return data
    except Exception:
        pass
    return None


def _qiniu_photo_srcs(main_no, sub_no=None):
    """从七牛云列出某订单主号下的照片 CDN URL（直连显示，无需下载到本地）。
    返回 (送货单照片URL列表[(url,name)], 实物照片URL列表[(url,name)])。
    仅用于云端无本地照片时直连七牛；本地部署仍用本地文件。"""
    domain = QN_DOMAIN.rstrip("/")
    if not domain.startswith(("http://", "https://")):
        domain = "http://" + domain
    delivery, physical = [], []
    if not (QN_ENABLED and QINIU_AVAILABLE):
        return delivery, physical
    try:
        keys = qn.list_files(f"photos/{main_no}/", QN_AK, QN_SK, QN_BUCKET)
        keys += qn.list_files(f"{main_no}/", QN_AK, QN_SK, QN_BUCKET)  # 旧版无 photos/ 前缀
        for k in keys:
            name = k.split("/")[-1]
            if not name.lower().endswith(rg.IMG_EXT):
                continue
            url = f"{domain}/{urllib.parse.quote(k)}"
            if sub_no and f"/送货单照片/{sub_no}/" in k:
                delivery.append((url, name))
            elif "/实物照片/" in k:
                physical.append((url, name))
        # 送货单：若指定分单无子目录，回退到主号下全部送货单照片
        if sub_no and not delivery:
            for k in keys:
                name = k.split("/")[-1]
                if "/送货单照片/" in k and name.lower().endswith(rg.IMG_EXT):
                    delivery.append((f"{domain}/{urllib.parse.quote(k)}", name))
        return delivery, physical
    except Exception:
        return [], []


def _qiniu_photo_items(main_no):
    """以七牛为权威源列出某订单主号下的全部照片。
    返回 (送货单照片列表[(key,display,name)], 实物照片列表[(key,display,name)])。
    key=七牛对象名（用于删除）；display=可显示源（本地路径或后端代理 data URL）；name=文件名。
    未启用七牛时回退本地扫描。"""
    if not (QN_ENABLED and QINIU_AVAILABLE):
        dl, pp = rg.collect_photos(PHOTO_ROOT, main_no)
        delivery = [(os.path.relpath(p, DATA_DIR).replace(os.sep, "/"), p, os.path.basename(p)) for p in dl]
        physical = [(os.path.relpath(p, DATA_DIR).replace(os.sep, "/"), p, os.path.basename(p)) for p in pp]
        return delivery, physical
    domain = QN_DOMAIN.rstrip("/")
    if not domain.startswith(("http://", "https://")):
        domain = "http://" + domain
    delivery, physical = [], []
    try:
        keys = qn.list_files(f"photos/{main_no}/", QN_AK, QN_SK, QN_BUCKET)
        keys += qn.list_files(f"{main_no}/", QN_AK, QN_SK, QN_BUCKET)  # 旧版无 photos/ 前缀
        for k in keys:
            name = k.split("/")[-1]
            if not name.lower().endswith(rg.IMG_EXT):
                continue
            url = f"{domain}/{urllib.parse.quote(k)}"
            display = _remote_to_data_url(url) or url
            item = (k, display, name)
            if "/实物照片/" in k:
                physical.append(item)
            elif "/送货单照片/" in k:
                delivery.append(item)
        return delivery, physical
    except Exception:
        return [], []


def _delete_photo_item(key, local_path=None):
    """删除照片：同步删除七牛对象 + 本地缓存文件。"""
    if key and QN_ENABLED and QINIU_AVAILABLE:
        try:
            qn.delete_from_qiniu(key, QN_AK, QN_SK, QN_BUCKET)
        except Exception:
            pass
    if local_path and os.path.exists(local_path):
        try:
            os.remove(local_path)
        except Exception:
            pass


def _disp_bytes(disp):
    """把 data URL 显示源转为 bytes（供 st.image 使用）；本地路径返回 None。"""
    if isinstance(disp, str) and disp.startswith("data:") and "," in disp:
        try:
            return base64.b64decode(disp.split(",", 1)[1])
        except Exception:
            return None
    return None


def _show_mgmt_photo(disp, width=170):
    """在数据管理页显示一张照片：data URL 转 bytes，本地路径直接读。"""
    b = _disp_bytes(disp)
    if b is not None:
        st.image(b, width=width)
    elif isinstance(disp, str) and os.path.exists(disp):
        st.image(disp, width=width)


def _qiniu_upload(local_path):
    """上传照片到七牛（key=相对 DATA_DIR 的路径），供上传后即时同步。"""
    if local_path and os.path.exists(local_path) and QN_ENABLED and QINIU_AVAILABLE:
        rel = os.path.relpath(local_path, DATA_DIR).replace(os.sep, "/")
        try:
            qn.upload_to_qiniu(local_path, rel, QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)
        except Exception:
            pass


def show_photo_grid(title, photos, cols=4):
    """图片网格 + 可拖动可缩放浮窗查看。点击缩略图打开浮窗；滚轮缩放、拖动图片平移、拖标题栏移动浮窗。"""
    st.markdown(f"**{title}（{len(photos)} 张）**")
    if not photos:
        st.caption("（暂无照片）")
        return
    items = []
    for p in photos:
        if isinstance(p, (tuple, list)):
            src, name = p[0], p[1]
        else:
            src, name = p, Path(p).name
        if isinstance(src, str) and src.startswith("http"):  # 七牛 CDN URL → 后端代理拉取
            src = _remote_to_data_url(src)
        elif isinstance(src, str) and os.path.exists(src):  # 本地文件 → 转 data URL
            src = img_to_data_url(src)
        if src:
            items.append((src, name))
    if not items:
        st.caption("（暂无照片）")
        return
    cards = ""
    for url, name in items:
        cards += (f'<div class="it" onclick="openLB(\'{url}\',\'{name}\')">'
                  f'<img src="{url}"><div class="nm">{name}</div></div>')
    rows = (len(items) + cols - 1) // cols
    grid_h = rows * 178 + 24
    height = grid_h  # 高度随照片数量自适应，避免大片留白
    w = 100 / cols
    html = _PHOTO_GRID_HTML.replace("__W__", str(w)).replace("__CARDS__", cards).replace("__H__", str(height))
    st.components.v1.html(html, height=height)


def load_options():
    default = {"customers": [], "materials": [], "visitor_password": "666666", "page_size": 30}
    # 优先从七牛云同步选项配置（含访客密码），本地作为缓存
    if QN_ENABLED and QINIU_AVAILABLE:
        try:
            qn.download_from_qiniu(QN_OPTIONS_KEY, OPTIONS_PATH, QN_AK, QN_SK, QN_DOMAIN)
        except Exception:
            pass
    if os.path.exists(OPTIONS_PATH):
        try:
            with open(OPTIONS_PATH, encoding="utf-8") as f:
                data = json.load(f)
            for k, v in default.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return default
    return default


def save_options(opts):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OPTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(opts, f, ensure_ascii=False, indent=2)
    if QN_ENABLED and QINIU_AVAILABLE:
        qn.upload_to_qiniu(OPTIONS_PATH, QN_OPTIONS_KEY, QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)

def get_visitor_password():
    return str(load_options().get("visitor_password", "666666"))

def get_page_size():
    try:
        _ps = int(load_options().get("page_size", 30))
        return _ps if _ps >= 5 else 30
    except Exception:
        return 30


def save_ledger_qn(df):
    """保存台账：更新最新版，并另存一份带时间戳的历史版本（本地 + 七牛云）。"""
    rg.save_ledger(df, DATA_DIR)
    p = rg.ledger_path(DATA_DIR)
    # 另存历史版本（带时间戳）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    hist_local_dir = os.path.join(DATA_DIR, "ledgers", "history")
    os.makedirs(hist_local_dir, exist_ok=True)
    hist_local = os.path.join(hist_local_dir, f"台账_{ts}.csv")
    try:
        shutil.copy(p, hist_local)
    except Exception:
        pass
    if QN_ENABLED and QINIU_AVAILABLE:
        qn.upload_to_qiniu(p, QN_LEDGER_KEY, QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)
        qn.upload_to_qiniu(p, f"{QN_LEDGER_HIST_DIR}/台账_{ts}.csv", QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)


def load_ledger_qn():
    """启动时优先从七牛云拉取台账（若存在），本地作为缓存。"""
    local = rg.ledger_path(DATA_DIR)
    if QN_ENABLED and QINIU_AVAILABLE:
        qn.download_from_qiniu(QN_LEDGER_KEY, local, QN_AK, QN_SK, QN_DOMAIN)
    return rg.load_ledger(DATA_DIR)


# ---------------- 页面配置 ----------------
st.set_page_config(page_title="发货单登记系统", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# ---------------- 登录（管理员 / 访客） ----------------
if "role" not in st.session_state:
    st.session_state.role = None

if st.session_state.role is None:
    st.html(_GLOBAL_CSS)
    lc, lmid, rc = st.columns([1, 1.5, 1])
    with lmid:
        st.markdown('''
        <div style="text-align:center;margin-top:6vh;">
          <div style="width:58px;height:58px;border-radius:17px;background:linear-gradient(135deg,#2563eb,#3b82f6);display:inline-flex;align-items:center;justify-content:center;color:#fff;font-size:1.8rem;box-shadow:0 4px 14px rgba(37,99,235,.3);">📦</div>
          <h2 style="margin:.9rem 0 .2rem;color:#1f2a44;font-size:1.35rem;">发货单登记系统</h2>
          <p style="color:#7a8497;font-size:.86rem;margin:0 0 1.4rem;">请登录后继续</p>
        </div>
        ''', unsafe_allow_html=True)
        with st.form("login_form"):
            pwd = st.text_input("访问密码", type="password", placeholder="请输入访问密码", label_visibility="collapsed")
            submitted = st.form_submit_button("登 录", type="primary", use_container_width=True)
        if submitted:
            if pwd == ADMIN_PASSWORD:
                st.session_state.role = "admin"
                st.session_state.side_hidden = False
                st.rerun()
            elif pwd == get_visitor_password():
                st.session_state.role = "visitor"
                st.session_state.side_hidden = False
                st.rerun()
            else:
                st.error("密码错误，请重试")
        st.markdown('<div class="login-hint">🔑 管理员密码进入数据管理界面（可上传 / 查询 / 管理）<br>👤 访客密码仅可查看查询系统</div>', unsafe_allow_html=True)
    st.stop()

# ---------------- 照片自动同步七牛云（启动时增量上传） ----------------
QN_UPLOAD_REC = os.path.join(DATA_DIR, "photos_uploaded.json")
QN_UPLOAD_STATUS = os.path.join(DATA_DIR, "photos_upload_status.json")

def _qn_status():
    """读取照片上传状态。"""
    if os.path.exists(QN_UPLOAD_STATUS):
        try:
            with open(QN_UPLOAD_STATUS) as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def _wqn_status(s):
    try:
        with open(QN_UPLOAD_STATUS, "w") as f:
            json.dump(s, f)
    except Exception:
        pass

def sync_photos_to_qiniu():
    """后台线程：本地与七牛云双向同步照片。
    本地新增/缺失 → 上传七牛；本地已删除的照片 → 从七牛同步删除。"""
    try:
        uploaded = set()
        if os.path.exists(QN_UPLOAD_REC):
            try:
                with open(QN_UPLOAD_REC) as f:
                    uploaded = set(json.load(f))
            except Exception:
                uploaded = set()
        # 1. 扫描本地照片
        local = {}
        for root, _dirs, files in os.walk(PHOTO_ROOT):
            for fn in files:
                if fn.lower().endswith(rg.IMG_EXT):
                    lp = os.path.join(root, fn)
                    rel = os.path.relpath(lp, DATA_DIR).replace(os.sep, "/")
                    local[rel] = lp
        # 2. 上传本地新增/缺失的照片到七牛
        todo = [rel for rel in local if rel not in uploaded]
        total = len(todo)
        done = 0
        if total:
            _wqn_status({"phase": "uploading", "total": total, "done": 0})
            for rel in todo:
                url = qn.upload_to_qiniu(local[rel], rel, QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)
                if url:
                    uploaded.add(rel)
                    done += 1
                if done % 10 == 0 or done == total:
                    _wqn_status({"phase": "uploading", "total": total, "done": done})
        # 3. 删除：记录里已上传、但本地已不存在的照片 → 从七牛同步删除
        del_count = 0
        for rel in list(uploaded):
            if rel not in local:
                if qn.delete_from_qiniu(rel, QN_AK, QN_SK, QN_BUCKET):
                    uploaded.discard(rel)
                    del_count += 1
        # 4. 保存上传记录
        with open(QN_UPLOAD_REC, "w") as f:
            json.dump(sorted(uploaded), f, ensure_ascii=False)
        _wqn_status({"phase": "done", "total": total, "done": done, "deleted": del_count, "finish": time.time()})
    except Exception:
        _wqn_status({"phase": "error"})

def _local_photo_count():
    """统计本地照片数量。"""
    n = 0
    for _r, _ds, _fs in os.walk(PHOTO_ROOT):
        for _fn in _fs:
            if _fn.lower().endswith(rg.IMG_EXT):
                n += 1
    return n


def _download_photos_from_qiniu():
    """启动时：若本地尚无任何照片（如云端无状态缓存被清空），则从七牛云拉取全部照片到本地。
    本地已有照片（本地部署）时跳过，不影响本地删除后同步清理七牛的逻辑。"""
    if not (QN_ENABLED and QINIU_AVAILABLE):
        return 0
    try:
        if _local_photo_count() > 0:
            return 0
        # 本系统照片在七牛有两类 key：新版 photos/ 前缀；旧版订单主号前缀（SG-xxx/实物照片/）
        keys = qn.list_files("photos/", QN_AK, QN_SK, QN_BUCKET)
        keys += qn.list_files("SG-", QN_AK, QN_SK, QN_BUCKET)
        got = 0
        for k in keys:
            if k.startswith("photos/"):
                lp = os.path.join(DATA_DIR, *k.split("/"))          # data/photos/...
            elif k.startswith("SG-"):
                lp = os.path.join(PHOTO_ROOT, *k.split("/"))        # data/photos/SG-xxx/...
            else:
                continue
            if os.path.exists(lp):
                continue
            if qn.download_from_qiniu(k, lp, QN_AK, QN_SK, QN_DOMAIN):
                got += 1
        # 标记这些 key 为已上传，避免双向同步误判为“本地已删”而清理七牛
        if keys:
            uploaded = set()
            if os.path.exists(QN_UPLOAD_REC):
                try:
                    with open(QN_UPLOAD_REC) as f:
                        uploaded = set(json.load(f))
                except Exception:
                    uploaded = set()
            uploaded.update(keys)
            try:
                with open(QN_UPLOAD_REC, "w") as f:
                    json.dump(sorted(uploaded), f, ensure_ascii=False)
            except Exception:
                pass
        return got
    except Exception:
        return 0


@st.cache_resource(show_spinner=False)
def _start_photo_sync():
    """启动时：后台线程先下载七牛照片到本地，再执行双向同步（不阻塞页面渲染）。"""
    if QN_ENABLED and QINIU_AVAILABLE:
        import threading

        def _job():
            # 照片通过七牛 CDN 直连显示，无需下载到本地；仅保留增量上传同步
            sync_photos_to_qiniu()

        threading.Thread(target=_job, daemon=True).start()
        return True
    return False

# 加载台账（需在侧边栏之前，侧边栏日历会用到）
if "ledger" not in st.session_state or st.session_state.ledger is None:
    st.session_state.ledger = load_ledger_qn()
df_all = st.session_state.ledger

# ---------------- 侧边栏导航（按角色） ----------------
with st.sidebar:
    # ---- 品牌区（图标与文字垂直居中，底部细分隔线） ----
    st.markdown("""<div class="side-brand">
      <div class="logo">📦</div>
      <div class="txt"><div class="t">发货单登记系统</div>
      <div class="s">送货单台账管理</div></div>
    </div>""", unsafe_allow_html=True)
    # ---- 状态卡片（身份 / 存储 / 同步，统一卡片） ----
    _role_html = ('<span class="side-badge side-badge-admin">管理员</span>' if st.session_state.role == "admin"
                  else '<span class="side-badge side-badge-visitor">访客</span>')
    _qn_html = ('<span class="side-badge side-badge-qn">七牛云已启用</span>' if QINIU_AVAILABLE
                else f'<span class="side-badge side-badge-qn-warn">{QINIU_HINT}</span>')
    _sync = ""
    if QN_ENABLED and QINIU_AVAILABLE:
        _start_photo_sync()
        _sst = _qn_status()
        if _sst.get("phase") == "uploading":
            _sync = f'<div class="side-sync"><span>📤</span><span>照片同步 {_sst.get("done", 0)}/{_sst.get("total", 0)} 张</span></div>'
        elif _sst.get("phase") == "done":
            _del = _sst.get("deleted", 0)
            _sync = f'<div class="side-sync"><span>✅</span><span>照片已同步{_sst.get("done", 0)}张' + (f' · 清理{_del}张' if _del else "") + '</span></div>'
        elif _sst.get("phase") == "error":
            _sync = '<div class="side-sync"><span>⚠</span><span>照片同步失败</span></div>'
    st.markdown(f'<div class="side-status"><div class="badges">{_role_html}{_qn_html}</div>{_sync}</div>', unsafe_allow_html=True)
    # ---- 导航（纯文字 + 选中态品牌蓝） ----
    st.markdown('<div class="side-sec-title">功能菜单</div>', unsafe_allow_html=True)
    _menu = (["送货单查询", "上传送货单", "旧数据导入", "数据管理", "管理选项"]
             if st.session_state.role == "admin" else ["送货单查询"])
    if "cur_page" not in st.session_state:
        st.session_state.cur_page = "送货单查询"
    for _m in _menu:
        _active = (_m == st.session_state.get("cur_page"))
        if st.button(_m, use_container_width=True,
                     type=("primary" if _active else "secondary"),
                     key=f"nav_{_m}"):
            st.session_state.cur_page = _m
            st.session_state.pop("admin_ok", None)
            st.rerun()
    # ---- 送货日期日历（卡片式，常驻侧边栏） ----
    if df_all is not None and not df_all.empty:
        with st.container(border=True):
            st.markdown('<div class="side-cal-title">📅 送货日期</div>', unsafe_allow_html=True)
            st.markdown('<div class="side-cal-hint">蓝色 = 有记录，点击切换月份</div>', unsafe_allow_html=True)
            _render_calendar(set(df_all["送货时间"].dropna().unique()))
    # ---- 退出登录 + 页脚 ----
    if st.button("退出登录", use_container_width=True, key="side_exit"):
        st.session_state.role = None
        st.session_state.pop("ledger", None)
        st.rerun()
    st.markdown('<div class="side-foot">发货单登记系统 · v2.0</div>', unsafe_allow_html=True)

    page = st.session_state.get("cur_page", "送货单查询")

st.html(_GLOBAL_CSS)


# ================= 送货单查询 =================
def render_query_page():
    _dl = sorted(df_all["送货时间"].dropna().unique().tolist()) if (df_all is not None and not df_all.empty) else []
    if "range" not in st.session_state and _dl:
        st.session_state.range = [_dl[0], _dl[-1]]
    if "page" not in st.session_state:
        st.session_state.page = 1

    if df_all.empty:
        st.markdown('<div style="background:#fff;border:1px solid #e7eaf1;border-radius:14px;padding:2.6rem;text-align:center;color:#7a8497;">暂无数据，请先在「上传送货单」上传送货单。</div>', unsafe_allow_html=True)
        return

    opts = rg.collect_options(df_all, load_options())

    # ================================================================
    # 筛选栏各区块宽度配置（可直接修改数字）
    #  · 送货日期/产品材料/数量从/数量到/重置/导出Excel：百分比(%)，占筛选栏总宽
    #  · 间距：像素(px)，各区块之间的空白
    #  · 说明：导出Excel 与 重置 同权重、同一行体系，不单独成列
    # ================================================================
    FILTER_WIDTHS = {
        "送货日期": 40,   # %
        "产品材料": 20,   # %
        "数量从": 10,     # %
        "数量到": 10,     # %
        "重置": 10,       # %
        "导出Excel": 10,  # %
        "间距": 2,        # px
    }
    _W = FILTER_WIDTHS

    # ================================================================
    # 布局：表格置顶；筛选栏、统计信息置于表格下方
    #    · 查询结果标题（含当月统计、明细小计）在表格上方
    #    · 筛选栏移到表格下方
    #    · 当月统计基于本月全部数据，不受筛选影响
    # ================================================================
    page_size = get_page_size()

    # ---- 读取当前筛选条件（组件值自动缓存于 session_state["fbar"]） ----
    fret = st.session_state.get("fbar")
    # 依据筛选计算 view，按送货时间从近到远排序
    view = df_all.copy().sort_values("送货时间", ascending=False)
    if fret:
        if fret.get("start") and fret.get("end"):
            view = view[(view["送货时间"] >= str(fret["start"]))
                        & (view["送货时间"] <= str(fret["end"]))]
        if fret.get("materials"):
            view = view[view["产品材料"].isin(fret["materials"])]
        _q = pd.to_numeric(view["数量"], errors="coerce").fillna(0)
        _qmn = fret.get("qty_min"); _qmx = fret.get("qty_max")
        if _qmn and int(_qmn) > 0:
            view = view[_q >= int(_qmn)]
        if _qmx and int(_qmx) > 0:
            view = view[_q <= int(_qmx)]

    # ---- 当月统计：本月全部数据，不受筛选影响 ----
    _cur_ym = datetime.now().strftime("%Y-%m")
    _month_df = df_all[df_all["送货时间"].astype(str).str.startswith(_cur_ym)] if (df_all is not None and not df_all.empty) else df_all
    month_total = pd.to_numeric(_month_df["数量"], errors="coerce").sum()

    total = pd.to_numeric(view["数量"], errors="coerce").sum()

    # ---- 当月统计分类：本月各产品材料统计（不受筛选影响） ----
    _month_ms = (_month_df.assign(_q=pd.to_numeric(_month_df["数量"], errors="coerce").fillna(0))
                 .groupby("产品材料")["_q"].sum().sort_values(ascending=False))
    _month_tags = "".join(
        f'<span style="background:#eef3ff;border:1px solid #d6e2ff;border-radius:20px;padding:.12rem .6rem;font-size:.78rem;color:#1f2a44;white-space:nowrap;">{html.escape(str(m))}　<b style="color:#2563eb;">{v:,.0f}</b></span>'
        for m, v in _month_ms.items())

    # ---- 查询结果标题 + 明细小计（表格上方） ----
    st.markdown(
        f'<div style="display:flex;align-items:baseline;gap:1.1rem;flex-wrap:wrap;margin-bottom:.25rem;">'
        f'<span style="font-size:.95rem;font-weight:700;color:#1f2a44;">查询结果</span>'
        f'<span style="color:#7a8497;font-size:.85rem;">{len(view)} 条</span>'
        f'<span style="font-size:.85rem;color:#5b6577;">明细小计 <b style="color:#16a34a;font-size:.95rem;">{total:,.0f}</b></span>'
        f'</div>', unsafe_allow_html=True)
    # ---- 当月统计（按产品材料分类，本月全部，不受筛选影响） ----
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:.45rem;flex-wrap:wrap;margin:.05rem 0 .25rem;">'
        f'<span style="font-size:.82rem;font-weight:700;color:#2563eb;">📅 当月统计（{_cur_ym} · 按产品材料）　<span style="color:#7a8497;font-weight:600;">合计 {month_total:,.0f}</span></span>'
        f'{_month_tags}'
        f'</div>', unsafe_allow_html=True)

    # ---- 表格（置顶） ----
    with st.container(border=True):
        pages = max(1, (len(view) + page_size - 1) // page_size)
        if st.session_state.page > pages:
            st.session_state.page = pages
        start = (st.session_state.page - 1) * page_size
        page_view = view.iloc[start:start + page_size].reset_index(drop=True)
        _order = ["送货时间", "产品材料", "产品名称", "数量", "单位", "包装明细", "送货单号"]  # 客户名称列不显示
        _cols = [c for c in _order if c in page_view.columns]
        _rows = []
        for _, _r in page_view.iterrows():
            _rows.append({
                "main": str(_r.get("订单主号", "")),
                "sub": str(_r.get("送货单号", "")),
                "cells": [("" if pd.isna(_r[c]) else str(_r[c])) for c in _cols],
            })
        # 可点击斑马纹表格（0.5cm 行高，点击行联动照片）
        _sel = clickable_table(columns=_cols, rows=_rows, default=None, key="tbl_query")
        if _sel and _sel.get("main"):
            st.session_state.photo_main = str(_sel.get("main"))
            st.session_state.photo_sub = str(_sel.get("sub"))
            st.session_state.photo_open = True
        pg1, pg2, pg3 = st.columns([1, 3, 1])
        with pg1:
            st.button("« 上一页", on_click=_prev_page, disabled=(st.session_state.page <= 1))
        with pg2:
            st.markdown(f"<div style='text-align:center;padding-top:.3rem;color:#5b6577;'>第 {st.session_state.page} / {pages} 页</div>", unsafe_allow_html=True)
        with pg3:
            st.button("下一页 »", on_click=_next_page, disabled=(st.session_state.page >= pages))

    # ---- 筛选栏（表格下方） ----
    with st.container(border=True):
        # 组件占满整行；export_b64 为 Python 生成的 xlsx(base64)，组件内自动触发下载
        export_b64 = st.session_state.get("fbar_export_b64")
        new_fret = filter_bar(materials=opts["materials"], widths=_W,
                              export_data=export_b64,
                              value=st.session_state.get("fbar"), key="fbar")
        # 导出Excel：组件内点击触发，Python 生成 xlsx 以 base64 回传自动下载
        if new_fret and new_fret.get("export_requested") and not export_b64:
            try:
                buf = io.BytesIO()
                view.to_excel(buf, index=False)
                st.session_state["fbar_export_b64"] = base64.b64encode(buf.getvalue()).decode()
                st.rerun()
            except Exception:
                st.session_state.pop("fbar_export_b64", None)
        if new_fret and new_fret.get("export_done"):
            st.session_state.pop("fbar_export_b64", None)
        # 说明：Streamlit 组件带 key 时返回值自动存入 session_state["fbar"]，
        # 组件交互触发 rerun 后，上方表格会基于最新筛选条件自动更新。

    # ---- 统计区（表格下方：明细小计按产品材料统计） ----
    def _mat_tags(_df, _color):
        _ms = (_df.assign(_q=pd.to_numeric(_df["数量"], errors="coerce").fillna(0))
                  .groupby("产品材料")["_q"].sum().sort_values(ascending=False))
        _tags = "".join(
            f'<span style="background:#f1f4fb;border:1px solid #e2e6ef;border-radius:20px;padding:.1rem .55rem;font-size:.76rem;color:#1f2a44;white-space:nowrap;">{html.escape(str(m))}　<b style="color:{_color};">{v:,.0f}</b></span>'
            for m, v in _ms.items())
        return _ms.sum(), _tags
    _s2, _tags2 = _mat_tags(view, "#16a34a")
    _empty2 = '<span style="color:#9aa3b5;font-size:.8rem;">当前筛选无明细</span>'
    st.markdown(
        f'<div style="margin-top:.4rem;">'
        f'<div style="font-size:.82rem;font-weight:600;color:#1f2a44;margin:.1rem 0 .2rem;">📋 明细小计（当前筛选结果 · 按产品材料）　<span style="color:#16a34a;font-weight:700;">{_s2:,.0f}</span></div>'
        f'<div style="display:flex;flex-wrap:wrap;gap:.3rem .6rem;">{_tags2 if _tags2 else _empty2}</div>'
        f'</div>', unsafe_allow_html=True)

    # ---- 照片（伸缩 + 点击表格行联动） ----
    if not view.empty:
        st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)
        _pm = st.session_state.get("photo_main")
        _popen = st.session_state.get("photo_open", True)  # 照片区默认展开
        with st.expander("🖼 送货单照片 / 实物照片（点击表格行即可联动图片）", expanded=_popen):
            if _pm and _pm in set(view["订单主号"].astype(str)):
                _subdf = view[view["订单主号"].astype(str) == _pm]
                _sel_sub = st.session_state.get("photo_sub")
                with st.container(border=True):
                    st.markdown(f'<div style="font-size:.9rem;font-weight:600;color:#2563eb;margin-bottom:.3rem;">🧾 订单主号：{_pm}　<span style="color:#7a8497;font-weight:400;font-size:.8rem;">选中分单：{_sel_sub or "-"}</span></div>', unsafe_allow_html=True)
                    st.caption(f"{len(_subdf)} 条明细 · 分单：{', '.join(sorted(set(_subdf['送货单号'].astype(str))))}")
                    # 照片源：云端无本地照片时直连七牛 CDN，本地部署用本地文件
                    if _local_photo_count() > 0:
                        _dp = rg.collect_delivery_photos(PHOTO_ROOT, _pm, _sel_sub) if _sel_sub else []
                        _pp = rg.collect_photos(PHOTO_ROOT, _pm)[1]
                    else:
                        _dp, _pp = _qiniu_photo_srcs(_pm, _sel_sub)
                    # 送货单照片：仅显示选中的分单
                    if _sel_sub:
                        show_photo_grid(f"📄 送货单照片 · 分单 {_sel_sub}", _dp, cols=1)
                    # 实物照片：按订单主号全部显示
                    show_photo_grid(f"📦 实物照片 · {_pm}", _pp, cols=4)
                    if st.button("🗕 收起照片", use_container_width=True):
                        st.session_state.photo_open = False
                        st.session_state.photo_main = None
                        st.session_state.photo_sub = None
                        st.rerun()
            else:
                st.caption("点击表格中任意一行，自动显示对应订单的送货单及实物照片")

def _reset_page():
    st.session_state.page = 1

def _reset_filter():
    # 重置产品材料和数量，保留送货日期，显示符合日期范围的全部数据
    st.session_state.pop("sel_mat", None)
    st.session_state.pop("qty_min", None)
    st.session_state.pop("qty_max", None)
    st.session_state.page = 1


def _prev_page():
    st.session_state.page = max(1, st.session_state.page - 1)


def _next_page():
    st.session_state.page = st.session_state.page + 1


# ================= 上传送货单 =================
def render_upload_page():
    if st.session_state.get("upload_success_msg"):
        _msg0 = st.session_state["upload_success_msg"]
        st.success(_msg0, icon="✅" if "✅" in _msg0 else "⚠️")
        st.session_state.pop("upload_success_msg", None)
    st.markdown(_page_head("上传送货单", "上传整本送货单 Excel 并关联送货单 / 实物照片，数据自动入库并同步七牛云"), unsafe_allow_html=True)
    st.markdown('''<div style="display:flex;align-items:center;gap:.6rem;margin-bottom:.5rem;">
      <div style="width:34px;height:34px;border-radius:9px;background:#eef3ff;color:#2563eb;display:flex;align-items:center;justify-content:center;font-size:1.05rem;flex:0 0 auto;">①</div>
      <div><div style="font-size:.9rem;font-weight:600;color:#1f2a44;">上传送货单 Excel（可多选）</div>
      <div style="font-size:.78rem;color:#7a8497;">一本对应一个订单主号 · 按住 Ctrl/Shift 可多选或拖拽多个文件</div></div>
    </div>''', unsafe_allow_html=True)
    excel = st.file_uploader("上传送货单 Excel", type=["xlsx", "xls"], accept_multiple_files=True, key="excel_up", label_visibility="collapsed", help="可一次选择多本送货单 Excel 一起上传")

    if excel:
        all_groups = {}
        for f in excel:
            tmp = os.path.join(NOTES_DIR, f"_tmp_{time.time()}_{f.name}")
            with open(tmp, "wb") as fh:
                fh.write(f.getbuffer())
            for n in pr.parse_workbook(tmp, customer_default="慧星"):
                mn = n.get("main_no") or "未识别主号"
                all_groups.setdefault(mn, []).append(n)

        if not all_groups:
            st.warning("未能从上传的文件中解析出送货单，请确认文件格式。")
        else:
            for mn, mnotes in all_groups.items():
                subs = sorted(set(str(n.get("delivery_no", "")) for n in mnotes))
                with st.container(border=True):
                    st.markdown(f'<div style="font-size:.95rem;font-weight:700;color:#1f2a44;">📦 订单主号：<span style="color:#2563eb;">{mn}</span>　<span style="color:#7a8497;font-weight:400;font-size:.82rem;">{len(subs)} 张分单</span></div>', unsafe_allow_html=True)
                    preview = rg.notes_to_ledger(mnotes, PHOTO_ROOT)
                    st.dataframe(preview, use_container_width=True, height=180)
                    st.caption("送货单照片按分单上传，分单之间不混用；实物照片按整个订单主号上传。")

                    st.markdown('<div style="font-size:.86rem;font-weight:600;color:#1f2a44;margin-top:.4rem;">📄 送货单照片（按分单上传）</div>', unsafe_allow_html=True)
                    dc = st.columns(len(subs)) if subs else []
                    d_up_map = {}
                    for i, sub in enumerate(subs):
                        with dc[i]:
                            d_up_map[sub] = st.file_uploader(
                                f"分单 {sub}", type=IMG_TYPES,
                                accept_multiple_files=True, key=f"d_{mn}_{sub}",
                                help="Ctrl/Shift 多选或拖拽")

                    st.markdown(f'<div style="font-size:.86rem;font-weight:600;color:#1f2a44;margin-top:.4rem;">📦 实物照片（订单主号 {mn}，可多张）</div>', unsafe_allow_html=True)
                    p_up = st.file_uploader(
                        f"实物照片（{mn}）", type=IMG_TYPES,
                        accept_multiple_files=True, key=f"p_{mn}",
                        help="Ctrl/Shift 多选或拖拽")

                    _bcol = st.columns([1, 2, 1])
                    with _bcol[1]:
                        _do_import = st.button(f"✓ 确认导入 {mn}", type="primary", key=f"imp_{mn}", use_container_width=True)
                    if _do_import:
                        for sub, ups in d_up_map.items():
                            save_uploaded(ups, os.path.join(PHOTO_ROOT, mn, rg.DELIVERY_PHOTO_DIR, sub))
                        save_uploaded(p_up, os.path.join(PHOTO_ROOT, mn, rg.PHYSICAL_PHOTO_DIR))
                        preview = rg.notes_to_ledger(mnotes, PHOTO_ROOT)
                        up_ok = up_fail = 0
                        if QN_ENABLED and QINIU_AVAILABLE:
                            for sub in subs:
                                sub_dir = os.path.join(PHOTO_ROOT, mn, rg.DELIVERY_PHOTO_DIR, sub)
                                local_paths = list_imgs_in(sub_dir)
                                urls = qn.upload_list_to_qiniu(
                                    local_paths, f"{mn}/{rg.DELIVERY_PHOTO_DIR}/{sub}",
                                    QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)
                                if urls:
                                    preview.loc[preview["送货单号"].astype(str) == sub, "送货单照片"] = ",".join(urls)
                                    up_ok += len(urls)
                                else:
                                    up_fail += len(local_paths)
                            ph_dir = os.path.join(PHOTO_ROOT, mn, rg.PHYSICAL_PHOTO_DIR)
                            local_paths = list_imgs_in(ph_dir)
                            urls = qn.upload_list_to_qiniu(
                                local_paths, f"{mn}/{rg.PHYSICAL_PHOTO_DIR}",
                                QN_AK, QN_SK, QN_BUCKET, QN_DOMAIN)
                            if urls:
                                preview["实物照片"] = ",".join(urls)
                                up_ok += len(urls)
                            else:
                                up_fail += len(local_paths)
                        merged = rg.merge_into_ledger(st.session_state.ledger, preview)
                        st.session_state.ledger = merged
                        save_ledger_qn(merged)
                        _msg = f"订单主号 {mn} 已导入 {len(preview)} 条明细"
                        _all_ok = True
                        if QN_ENABLED and not QINIU_AVAILABLE:
                            _all_ok = False
                            st.session_state["upload_success_msg"] = f"⚠️ {_msg}；{QINIU_HINT or '七牛未启用'}，照片未上传七牛云"
                        elif QN_ENABLED:
                            _all_ok = (up_fail == 0)
                            if _all_ok:
                                st.session_state["upload_success_msg"] = f"✅ 全部上传成功：{_msg}；七牛云成功上传 {up_ok} 张"
                            else:
                                st.session_state["upload_success_msg"] = f"⚠️ 部分照片上传失败：{_msg}；成功 {up_ok} 张，失败 {up_fail} 张，请检查网络后重试"
                        else:
                            st.session_state["upload_success_msg"] = f"✅ {_msg}"
                        # 全部上传成功：自动清空上传内容，返回上传首页，等待下一次上传
                        if _all_ok:
                            for _k in list(st.session_state.keys()):
                                if _k == "excel_up" or _k.startswith("d_") or _k.startswith("p_"):
                                    st.session_state.pop(_k, None)
                        st.rerun()


# ================= 效验异常 =================
# ================= 管理选项 =================
def render_admin_page():
    st.markdown(_page_head("管理选项", "维护查询下拉选项、访客密码等系统配置"), unsafe_allow_html=True)
    if not st.session_state.get("admin_ok", False):
        pwd = st.text_input("请输入管理密码", type="password")
        if st.button("🔓 验证进入管理"):
            if pwd == ADMIN_PASSWORD:
                st.session_state["admin_ok"] = True
                st.rerun()
            else:
                st.error("密码错误，无权进入管理")
    else:
        st.success("✅ 已进入管理模式")
        if st.button("退出管理模式"):
            st.session_state["admin_ok"] = False
            st.rerun()

        st.divider()
        st.markdown("#### 危险操作")
        if st.button("🗑 清空台账（清空全部数据）"):
            st.session_state.pop("ledger", None)
            save_ledger_qn(pd.DataFrame(columns=rg.LEDGER_COLUMNS))
            st.success("台账已清空")
            st.rerun()
        _opts = load_options()

        st.markdown("#### 系统设置")
        _ps = get_page_size()
        _ps_input = st.number_input("每页显示行数", min_value=5, max_value=300, value=int(_ps), step=5, key="page_size_set")
        if st.button("💾 保存每页行数"):
            _opts["page_size"] = int(_ps_input)
            save_options(_opts)
            st.success(f"每页行数已设置为 {int(_ps_input)}")
            st.rerun()
        st.divider()

        st.markdown("#### 客户名称")
        _custs = rg.collect_options(df_all, _opts)["customers"]
        cust_cols = st.columns(4)
        _del_cust = []
        for i, c in enumerate(_custs):
            with cust_cols[i % 4]:
                st.markdown(f"- {c}")
                if st.button(f"删除 {c}", key=f"dc_{c}"):
                    _del_cust.append(c)
        new_cust = st.text_input("新增客户名称", key="nc")
        if st.button("➕ 添加客户"):
            if new_cust.strip() and new_cust.strip() not in _opts["customers"]:
                _opts["customers"].append(new_cust.strip())
                save_options(_opts)
                st.success(f"已添加客户：{new_cust.strip()}")
                st.rerun()
        if _del_cust:
            for c in _del_cust:
                if c in _opts["customers"]:
                    _opts["customers"].remove(c)
            save_options(_opts)
            st.rerun()

        st.divider()
        st.markdown("#### 产品材料")
        _mats = rg.collect_options(df_all, _opts)["materials"]
        mat_cols = st.columns(4)
        _del_mat = []
        for i, m in enumerate(_mats):
            with mat_cols[i % 4]:
                st.markdown(f"- {m}")
                if st.button(f"删除 {m}", key=f"dm_{m}"):
                    _del_mat.append(m)
        new_mat = st.text_input("新增产品材料", key="nm")
        if st.button("➕ 添加材料"):
            if new_mat.strip() and new_mat.strip() not in _opts["materials"]:
                _opts["materials"].append(new_mat.strip())
                save_options(_opts)
                st.success(f"已添加材料：{new_mat.strip()}")
                st.rerun()
        if _del_mat:
            for m in _del_mat:
                if m in _opts["materials"]:
                    _opts["materials"].remove(m)
            save_options(_opts)
            st.rerun()

        st.divider()
        st.markdown("#### 访客密码设置")
        st.caption("自定义访客登录密码（访客仅可查看查询系统）")
        _vp_opts = load_options()
        _cur_vp = _vp_opts.get("visitor_password", "666666")
        _new_vp = st.text_input("设置访客登录密码", value=str(_cur_vp), key="vp_input")
        if st.button("💾 保存访客密码"):
            if _new_vp.strip():
                _vp_opts["visitor_password"] = _new_vp.strip()
                save_options(_vp_opts)
                st.success(f"访客密码已更新：{_new_vp.strip()}")
                st.rerun()


# ================= 数据管理 =================
def _derive_main_no(no):
    """由送货单号派生订单主号：SG-250403-0001 -> SG-250403"""
    s = str(no or "").strip()
    m = re.match(r"^(.*?)-\d{2,4}$", s)
    return m.group(1) if m else s

def render_data_mgmt_page():
    st.markdown(_page_head("数据管理", "查找、修改、替换、删除台账记录，支持批量处理"), unsafe_allow_html=True)
    st.markdown("""<style>
    /* 全局大幅压缩：隐藏输入框/下拉标签，缩小高度与间距 */
    div[data-testid="stTextInput"]{padding:0!important;margin:0!important;}
    div[data-testid="stTextInput"] label{display:none!important;}
    div[data-testid="stTextInput"]>div{padding:0!important;}
    div[data-testid="stTextInput"] input{background-color:#ffffff!important;padding:2px 7px!important;min-height:26px!important;font-size:.82rem!important;}
    div[data-testid="stSelectbox"] label{display:none!important;}
    div[data-testid="stSelectbox"]>div{padding-top:0!important;}
    div[data-testid="stSelectbox"]>div>div{padding-top:0!important;padding-bottom:0!important;}
    div[data-testid="stSelectbox"] [data-baseweb="select"]>div{padding-top:0!important;padding-bottom:0!important;min-height:26px!important;}
    div[data-testid="stButton"] button{padding:2px 10px!important;font-size:.82rem!important;}
    div[data-testid="stHorizontalBlock"]{gap:.6rem!important;}
    [data-testid="stVerticalBlock"]{gap:.3rem!important;}
    div[data-testid="stCaptionContainer"]{padding:0!important;}
    hr{margin:.35rem 0!important;}
    div[data-testid="stForm"] [data-testid="stVerticalBlock"]{gap:.3rem!important;}
    </style>""", unsafe_allow_html=True)

    def _key(r):
        return (str(r.get("订单主号", "")), str(r.get("送货单号", "")))

    def _norm_date(s):
        s = str(s or "").strip()
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return s

    # 从 session 读取查找输入（即使查找区在下方，也先用于过滤表格）
    _ds = _norm_date(st.session_state.get("dm_ds", ""))
    _de = _norm_date(st.session_state.get("dm_de", ""))

    _df = df_all.copy() if df_all is not None else pd.DataFrame(columns=rg.LEDGER_COLUMNS)
    if _ds:
        _df = _df[_df["送货时间"].astype(str) >= _ds]
    if _de:
        _df = _df[_df["送货时间"].astype(str) <= _de]
    _df = _df.reset_index(drop=True)

    # ============ 表格置顶 ============
    st.caption(f"共匹配 {len(_df)} 条记录")
    if _df.empty:
        st.info("无匹配记录，请调整下方查找条件")
    else:
        _edit_cols = ["订单主号", "客户名称", "送货时间", "产品材料", "产品名称", "产品规格", "数量", "单位", "包装明细", "送货单号"]
        _show = _df[_edit_cols].copy()
        st.markdown("✏️ **修改**：直接在表格改单元格；点某行左侧垃圾桶图标可删除该行。")
        _edited = st.data_editor(_show, num_rows="dynamic", use_container_width=True,
                                 disabled=["订单主号"], hide_index=True, key="dmg_editor")
        if st.button("💾 保存修改", type="primary"):
            try:
                old_map = {_key(r): r for _, r in df_all.iterrows()}
                new_rows = []
                for _, r in _edited.iterrows():
                    old = old_map.get(_key(r), None)
                    _qty = r.get("数量")
                    _verify = rg.compute_verify(_qty, r.get("包装明细"))
                    new_rows.append({
                        "订单主号": _derive_main_no(r.get("送货单号")),
                        "客户名称": r.get("客户名称"),
                        "送货时间": r.get("送货时间"),
                        "产品材料": r.get("产品材料"),
                        "产品名称": r.get("产品名称"),
                        "产品规格": r.get("产品规格"),
                        "数量": _qty,
                        "单位": r.get("单位"),
                        "包装明细": r.get("包装明细"),
                        "送货单号": r.get("送货单号"),
                        "送货单照片": old.get("送货单照片", "") if old is not None else "",
                        "实物照片": old.get("实物照片", "") if old is not None else "",
                        "明细与数量效验": _verify,
                    })
                _key_set = set(_key(r) for _, r in _edited.iterrows())
                keep = df_all[~df_all.apply(lambda r: _key(r) in _key_set, axis=1)]
                combined = pd.concat([keep, pd.DataFrame(new_rows, columns=rg.LEDGER_COLUMNS)], ignore_index=True)
                save_ledger_qn(combined)
                st.session_state.pop("ledger", None)
                st.success(f"✅ 已保存修改，台账共 {len(combined)} 条")
                st.rerun()
            except Exception as e:
                st.error(f"保存失败：{e}")

    # ============ 查找区（表格下方，仅日期筛选） ============
    d1, d2 = st.columns(2)
    d1.text_input("开始日期", key="dm_ds", placeholder="开始日期 20260816", label_visibility="collapsed")
    d2.text_input("结束日期", key="dm_de", placeholder="结束日期 20260816", label_visibility="collapsed")

    if not _df.empty:
        # ============ 批量替换 ============
        with st.expander("🔁 批量替换（仅作用于当前查找结果）", expanded=False):
            with st.form("dm_replace"):
                r1, r2, r3, r4 = st.columns([1, 1, 1, 1])
                _rcol = r1.selectbox("要替换的列", ["产品材料", "产品名称", "产品规格", "客户名称", "单位", "送货时间"], key="dm_rcol")
                _rmatch = r2.text_input("仅替换包含此文字的行（留空=全部）", key="dm_rmatch")
                _rnew = r3.text_input("替换为新值", key="dm_rnew")
                _rgo = r4.form_submit_button("⚡ 执行批量替换")
            if _rgo:
                if not _rnew:
                    st.error("请填写「替换为新值」")
                else:
                    col = _rcol
                    if _rmatch:
                        mask = _df[col].astype(str).str.contains(_rmatch, na=False)
                        affect = set(_key(r) for _, r in _df[mask].iterrows())
                    else:
                        affect = set(_key(r) for _, r in _df.iterrows())
                    l2 = df_all.copy()
                    cnt = 0
                    for i in l2.index:
                        if _key(l2.loc[i]) in affect:
                            v = str(l2.at[i, col])
                            if _rmatch and _rmatch in v:
                                l2.at[i, col] = v.replace(_rmatch, _rnew)
                                cnt += 1
                            elif not _rmatch:
                                l2.at[i, col] = _rnew
                                cnt += 1
                    if cnt == 0:
                        st.warning("没有符合条件可替换的行")
                    else:
                        save_ledger_qn(l2)
                        st.session_state.pop("ledger", None)
                        st.success(f"✅ 已批量替换 {cnt} 条记录")
                        st.rerun()

        # ============ 删除 ============
        with st.expander("🗑 删除", expanded=False):
            with st.form("dm_del"):
                dd1, dd2 = st.columns([2, 1])
                _dno = dd1.text_input("按送货单号删除（多个用英文逗号分隔，留空则删除当前全部匹配记录）", key="dm_dno")
                _dgo = dd2.form_submit_button("🗑 删除并保存")
            if _dgo:
                if _dno.strip():
                    nos = {x.strip() for x in _dno.split(",") if x.strip()}
                    del_keys = {_key(r) for _, r in _df.iterrows() if str(r.get("送货单号", "")) in nos}
                else:
                    del_keys = {_key(r) for _, r in _df.iterrows()}
                if not del_keys:
                    st.warning("没有可删除的记录")
                else:
                    l3 = df_all[~df_all.apply(lambda r: _key(r) in del_keys, axis=1)]
                    save_ledger_qn(l3)
                    st.session_state.pop("ledger", None)
                    st.success(f"✅ 已删除 {len(del_keys)} 条记录，台账剩余 {len(l3)} 条")
                    st.rerun()

        # ============ 订单照片管理（送货单 + 实物照片） ============
        st.markdown("---")
        with st.expander("🖼 订单照片管理（查看 / 上传 / 重新上传 / 删除 送货单与实物照片）", expanded=True):
            st.caption("操作步骤：① 选择或搜索订单 → ② 查看该订单的照片 → ③ 上传新照片 或 删除旧照片。所有改动自动同步七牛云。")

            # ---- 辅助：按订单主号重新收集本地照片并刷新台账照片列 ----
            def _refresh_photo_cols(_mn):
                _dl = []
                for _sub in sorted(set(df_all.loc[df_all["订单主号"].astype(str) == _mn, "送货单号"].astype(str))):
                    _dl += rg.collect_delivery_photos(PHOTO_ROOT, _mn, _sub)
                _pl = rg.collect_photos(PHOTO_ROOT, _mn)[1]
                _dp_rel = ",".join(os.path.relpath(p, DATA_DIR).replace(os.sep, "/") for p in _dl)
                _pp_rel = ",".join(os.path.relpath(p, DATA_DIR).replace(os.sep, "/") for p in _pl)
                _ld = df_all.copy()
                _mask = _ld["订单主号"].astype(str) == _mn
                _ld.loc[_mask, "送货单照片"] = _dp_rel
                _ld.loc[_mask, "实物照片"] = _pp_rel
                save_ledger_qn(_ld)
                st.session_state.pop("ledger", None)

            # ---- ① 选择订单 ----
            _all_mains = sorted(set(df_all["订单主号"].astype(str)), reverse=True)
            _cA, _cB = st.columns([1, 1])
            with _cA:
                _sel_main = st.selectbox("订单主号", _all_mains, key="pm_main",
                                         help="下拉选择订单；也可在右侧输入送货单号快速定位")
            with _cB:
                _search_no = st.text_input("按送货单号定位（如 SG-250403-0001）", key="pm_search",
                                           placeholder="输入送货单号后自动定位")
            _mn = _sel_main
            if _search_no.strip():
                _m2 = _derive_main_no(_search_no)
                if _m2 in set(_all_mains):
                    _mn = _m2
                else:
                    st.warning(f"未找到送货单号对应的订单：{_m2}")

            _dp, _pp = _qiniu_photo_items(_mn)   # 以七牛为权威源列出照片
            _subs = sorted(set(df_all.loc[df_all["订单主号"].astype(str) == _mn, "送货单号"].astype(str)))
            # ---- 订单概览卡片 ----
            st.markdown(
                f'<div style="background:#fff;border:1px solid #e7eaf1;border-radius:12px;padding:.6rem .85rem;margin:.35rem 0;">'
                f'<div style="font-size:.88rem;font-weight:700;color:#1f2a44;">📦 订单 <span style="color:#2563eb;">{_mn}</span></div>'
                f'<div style="font-size:.78rem;color:#5b6577;margin-top:.25rem;">分单 {len(_subs)} 个 · 送货单照片 {len(_dp)} 张 · 实物照片 {len(_pp)} 张</div>'
                f'</div>', unsafe_allow_html=True)

            # ---- ② 送货单照片（按分单，可上传 / 重新上传覆盖 / 删除） ----
            st.markdown("#### 🧾 送货单照片")
            st.caption("每个分单对应一张送货单底单。上传新照片会覆盖该分单原有的送货单照片。")
            for _sub in _subs:
                _dps = [it for it in _dp if f"/送货单照片/{_sub}/" in it[0]]
                st.markdown(f"**分单 {_sub}**")
                if _dps:
                    for _j, (_k, _disp, _nm) in enumerate(_dps):
                        _dc1, _dc2 = st.columns([5, 1])
                        with _dc1:
                            _show_mgmt_photo(_disp, 200)
                            st.caption(_nm)
                        with _dc2:
                            if st.button("🗑 删除", key=f"del_dp_{_sub}_{_j}_{_nm}"):
                                _delete_photo_item(_k, os.path.join(DATA_DIR, *_k.split("/")))
                                _refresh_photo_cols(_mn)
                                st.success(f"已删除送货单照片（分单 {_sub}）")
                                st.rerun()
                else:
                    st.caption("（该分单暂无送货单照片）")
                _up = st.file_uploader(f"上传 / 重新上传送货单照片（分单 {_sub}）",
                                       type=["jpg", "jpeg", "png", "bmp", "webp"],
                                       key=f"up_dp_{_sub}")
                if _up is not None:
                    _folder = os.path.join(PHOTO_ROOT, _mn, rg.DELIVERY_PHOTO_DIR, _sub)
                    os.makedirs(_folder, exist_ok=True)
                    # 重新上传覆盖：先删除该分单现有的送货单照片（七牛 + 本地）
                    for _old in [it for it in _dp if f"/送货单照片/{_sub}/" in it[0]]:
                        _delete_photo_item(_old[0], os.path.join(DATA_DIR, *_old[0].split("/")))
                    _ext = os.path.splitext(_up.name)[1].lower() or ".jpg"
                    if _ext not in rg.IMG_EXT:
                        _ext = ".jpg"
                    _dest = os.path.join(_folder, f"送货单底单{_ext}")
                    with open(_dest, "wb") as _fo:
                        _fo.write(_up.getbuffer())
                    _qiniu_upload(_dest)   # 即时同步到七牛
                    _refresh_photo_cols(_mn)
                    st.success(f"已上传送货单照片到分单 {_sub}")
                    st.rerun()

            # ---- ③ 实物照片（整个订单，可上传多张 / 删除） ----
            st.markdown("#### 📦 实物照片")
            st.caption("实物照片属于整个订单。可上传多张，删除或替换其中任意一张。")
            if _pp:
                _pc = st.columns(4)
                for _i, (_k, _disp, _nm) in enumerate(_pp):
                    with _pc[_i % 4]:
                        _show_mgmt_photo(_disp, 170)
                        st.caption(_nm)
                        if st.button("🗑 删除", key=f"del_pp_{_i}_{_nm}"):
                            _delete_photo_item(_k, os.path.join(DATA_DIR, *_k.split("/")))
                            _refresh_photo_cols(_mn)
                            st.success("已删除一张实物照片")
                            st.rerun()
            else:
                st.caption("（暂无实物照片，请上传）")
            _up_pp = st.file_uploader("上传实物照片（可多张）", type=["jpg", "jpeg", "png", "bmp", "webp"],
                                      accept_multiple_files=True, key="up_pp")
            if _up_pp:
                _folder = os.path.join(PHOTO_ROOT, _mn, rg.PHYSICAL_PHOTO_DIR)
                os.makedirs(_folder, exist_ok=True)
                _n = 0
                for _f in _up_pp:
                    _ext = os.path.splitext(_f.name)[1].lower() or ".jpg"
                    if _ext not in rg.IMG_EXT:
                        _ext = ".jpg"
                    _dest = os.path.join(_folder, f"实物_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{_n+1}{_ext}")
                    with open(_dest, "wb") as _fo:
                        _fo.write(_f.getbuffer())
                    _qiniu_upload(_dest)   # 即时同步到七牛
                    _n += 1
                _refresh_photo_cols(_mn)
                st.success(f"✅ 已上传 {_n} 张实物照片到订单 {_mn}")
                st.rerun()
def render_import_legacy_page():
    st.markdown(_page_head("旧数据导入", "把旧版送货Excel（含单元格图片）导入并合并到台账"), unsafe_allow_html=True)
    st.caption("支持旧版格式：客户名称/送货时间/产品材料/产品名称/产品规格/数量/单位/包装明细/送货单底单(图片)/送货单号。")
    st.caption("送货单底单列需为 WPS 单元格内嵌图片；送货单号列需已填写（如 SG-250403-0001）。")
    up = st.file_uploader("选择旧版 Excel 文件（.xlsx）", type=["xlsx"], key="legacy_up")
    if up is not None:
        try:
            import import_legacy as il
            _tmp = os.path.join(DATA_DIR, "legacy_tmp.xlsx")
            with open(_tmp, "wb") as f:
                f.write(up.getbuffer())
            new_df, _saved = il.import_legacy_excel(_tmp, DATA_DIR)
            _preview = new_df[["订单主号", "送货时间", "产品材料", "数量", "送货单号"]].head(5)
            st.dataframe(_preview, use_container_width=True)
            st.success(f"解析成功：{len(new_df)} 条记录待导入")
            if st.button("✅ 确认导入并合并到台账", type="primary"):
                _cur = rg.load_ledger(DATA_DIR)
                _merged = rg.merge_into_ledger(_cur, new_df)
                rg.save_ledger(_merged, DATA_DIR)
                _o = rg.load_options(DATA_DIR)
                rg.save_options(rg.collect_options(_merged, _o), DATA_DIR)
                st.session_state.pop("ledger", None)
                st.success(f"✅ 导入完成：台账共 {len(_merged)} 条记录，{_merged['订单主号'].nunique()} 个订单")
                st.rerun()
        except Exception as e:
            st.error(f"导入失败：{e}\n\n请确认是旧版送货Excel（含 WPS 单元格图片）。")

if page == "送货单查询":
    render_query_page()
elif page == "上传送货单":
    render_upload_page()
elif page == "旧数据导入":
    render_import_legacy_page()
elif page == "数据管理":
    render_data_mgmt_page()
else:
    render_admin_page()

st.caption("— 数据保存在本地 data/ 目录 —")
    
