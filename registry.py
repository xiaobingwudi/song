# -*- coding: utf-8 -*-
"""
台账生成与存储模块
- 将解析出的送货单明细合并为台账行（按订单主号归组）
- 校验"数量"与"包装明细"是否一致
- 照片按订单主号管理（送货单照片 / 实物照片）
- 台账持久化为 CSV（累积数据）
"""
import json
import os
import re

import pandas as pd

from parser import normalize_date

# 台账列
LEDGER_COLUMNS = [
    "订单主号", "客户名称", "送货时间", "产品材料", "产品名称", "产品规格",
    "数量", "单位", "包装明细", "送货单号",
    "送货单照片", "实物照片", "明细与数量效验",
]

# 照片类型子文件夹
DELIVERY_PHOTO_DIR = "送货单照片"
PHYSICAL_PHOTO_DIR = "实物照片"
IMG_EXT = (".jpg", ".jpeg", ".png", ".bmp", ".webp")


def _list_imgs(d):
    """列出目录下所有图片的完整路径（排序）。"""
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in sorted(os.listdir(d))
            if f.lower().endswith(IMG_EXT)]


def collect_photos(photo_root, main_no):
    """
    按订单主号收集两类照片，返回 (送货单共享照片列表, 实物照片列表)。
    目录约定：photo_root/<订单主号>/送货单照片/  与  /实物照片/
    """
    folder = os.path.join(photo_root, str(main_no))
    if not os.path.isdir(folder):
        return [], []
    delivery = _list_imgs(os.path.join(folder, DELIVERY_PHOTO_DIR))
    physical = _list_imgs(os.path.join(folder, PHYSICAL_PHOTO_DIR))
    return delivery, physical


def collect_delivery_photos(photo_root, main_no, sub_no):
    """
    按订单主号 + 分单号收集送货单照片。
    目录约定：photo_root/<主号>/送货单照片/<分单号>/
    若不存在分单子目录，则回退到主号的送货单照片目录（共享）。
    """
    folder = os.path.join(photo_root, str(main_no), DELIVERY_PHOTO_DIR)
    if sub_no:
        sub = os.path.join(folder, str(sub_no))
        if os.path.isdir(sub):
            return _list_imgs(sub)
    return _list_imgs(folder)


def build_product_name(it):
    """产品名称 = 材料名称 + 颜色 + 备注（无分隔连写，空字段自动跳过）。
    若三字段全空则回退上传表中的“产品名称”列，避免名称为空。"""
    parts = [
        str(it.get("材料名称", "") or "").strip(),
        str(it.get("颜色", "") or "").strip(),
        str(it.get("备注", "") or "").strip(),
    ]
    parts = [p for p in parts if p]
    name = "".join(parts)
    if name:
        return name
    return str(it.get("产品名称", "") or "").strip()


def compute_material(material, package):
    """
    生成"产品材料"标签。
    规则：材料名称 + 包装（去空格）。
    例：合成纸 + 单条 -> 合成纸单条
        95热敏合成纸 + 卷装 -> 95热敏合成纸卷装
        定制合成纸 + 单条 -> 定制合成纸单条
    """
    m = str(material or "").strip()
    p = str(package or "").strip()
    if m and p:
        return f"{m}{p}".replace(" ", "")
    return m or p


def compute_verify(quantity, package_detail):
    """
    校验数量是否与包装明细拆分之和一致。
    包装明细格式：'5*30000'、'1*30000+1*20000'、'10000'、'2*3000+1000'
    一致返回 0（通过），不一致返回差值或错误标记。
    """
    if quantity is None:
        return "缺数量"
    try:
        qty = float(quantity)
    except (TypeError, ValueError):
        return "数量异常"

    pd_text = str(package_detail or "").strip().replace(" ", "")
    if not pd_text:
        return 0  # 无包装明细则不作校验

    parts = re.split(r"[+]", pd_text)
    total = 0.0
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "*" in part:
            a, b = part.split("*", 1)
            try:
                total += float(a) * float(b)
            except ValueError:
                return "包装明细格式异常"
        else:
            try:
                total += float(part)
            except ValueError:
                return "包装明细格式异常"

    if abs(total - qty) < 1e-6:
        return 0
    return f"差异{int(total - qty)}"


def notes_to_ledger(notes, photo_root=""):
    """
    将多张送货单展开为台账 DataFrame，按订单主号归组。
    photo_root: 照片根目录，其下按订单主号文件夹组织。
    """
    rows = []
    for note in notes:
        main_no = note.get("main_no", "") or note.get("delivery_no", "") or ""
        date = normalize_date(note.get("date", ""))
        customer = note.get("customer", "") or ""
        # 实物照片按订单主号；送货单照片按分单号匹配
        sub_no = note.get("delivery_no", "")
        delivery_photos = collect_delivery_photos(photo_root, main_no, sub_no) if photo_root else []
        physical_photos = collect_photos(photo_root, main_no)[1] if photo_root else []

        for it in note["items"]:
            qty = it.get("数量")
            pack = it.get("包装明细")
            verify = compute_verify(qty, pack)
            rows.append({
                "订单主号": main_no,
                "客户名称": customer,
                "送货时间": date,
                "产品材料": compute_material(it.get("材料名称"), it.get("包装")),
                "产品名称": build_product_name(it),
                "产品规格": str(it.get("产品规格", "") or "").strip(),
                "数量": qty,
                "单位": it.get("单位", ""),
                "包装明细": pack,
                "送货单号": note.get("delivery_no", ""),
                "送货单照片": ",".join(delivery_photos) if delivery_photos else "",
                "实物照片": ",".join(physical_photos) if physical_photos else "",
                "明细与数量效验": verify,
            })
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


def merge_into_ledger(existing_df, new_df):
    """
    将新解析的台账并入历史台账。
    规则：以"订单主号"为唯一单位——新导入数据中已存在的主号，整单替换旧记录；
    其余主号原样保留。保留该主号下所有明细行，不做逐行合并去重。
    """
    if existing_df is None or existing_df.empty:
        return new_df.reset_index(drop=True)
    if new_df is None or new_df.empty:
        return existing_df.reset_index(drop=True)
    if "订单主号" not in existing_df.columns or "订单主号" not in new_df.columns:
        return pd.concat([existing_df, new_df], ignore_index=True).reset_index(drop=True)
    new_mains = set(new_df["订单主号"].dropna().unique())
    keep = existing_df[~existing_df["订单主号"].isin(new_mains)]
    combined = pd.concat([keep, new_df], ignore_index=True)
    return combined.reset_index(drop=True)


def options_path(data_dir):
    return os.path.join(data_dir, "options.json")


def load_options(data_dir):
    """读取管理选项（客户、材料等）。"""
    default = {"customers": [], "materials": []}
    p = options_path(data_dir)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            for k in default:
                data.setdefault(k, [])
            return data
        except Exception:
            return default
    return default


def save_options(opts, data_dir):
    p = options_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(opts, f, ensure_ascii=False, indent=2)
    return p


def collect_options(ledger_df, opts):
    """合并台账中出现过的值与自定义选项，去重排序。"""
    customers = set(opts.get("customers", []))
    materials = set(opts.get("materials", []))
    if ledger_df is not None and not ledger_df.empty:
        if "客户名称" in ledger_df.columns:
            customers |= {str(x) for x in ledger_df["客户名称"].dropna().unique()}
        if "产品材料" in ledger_df.columns:
            materials |= {str(x) for x in ledger_df["产品材料"].dropna().unique()}
    return {
        "customers": sorted(customers, key=lambda s: s.strip()),
        "materials": sorted(materials, key=lambda s: s.strip()),
    }


def ledger_path(data_dir):
    return os.path.join(data_dir, "ledgers", "台账.csv")


def load_ledger(data_dir):
    p = ledger_path(data_dir)
    if os.path.exists(p):
        try:
            return pd.read_csv(p, dtype=str).fillna("")
        except Exception:
            return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.DataFrame(columns=LEDGER_COLUMNS)


def save_ledger(df, data_dir):
    p = ledger_path(data_dir)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    df.to_csv(p, index=False, encoding="utf-8-sig")
    return p
