# -*- coding: utf-8 -*-
"""
旧版送货Excel 导入模块（兼容 WPS DISPIMG 单元格内嵌图片）。
用法：
    import import_legacy as il
    result = il.import_legacy_excel(xlsx_path, DATA_DIR)
"""
import os, re, zipfile, json
from datetime import datetime, timedelta
from xml.etree import ElementTree as ET
import pandas as pd
import registry as rg

NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def _parse_shared(z):
    root = ET.fromstring(z.read('xl/sharedStrings.xml'))
    arr = []
    for si in root.findall('m:si', NS):
        txt = ''.join(t.text or '' for t in si.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t'))
        arr.append(txt)
    return arr


def _col_to_idx(ref):
    col = ''.join(c for c in ref if c.isalpha())
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - 64)
    return idx - 1


def _serial_to_date(v):
    try:
        return (datetime(1899, 12, 30) + timedelta(days=float(v))).strftime('%Y-%m-%d')
    except Exception:
        return str(v or '')


def _parse_rows(z, ss):
    root = ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
    rows = []
    for row in root.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
        rnum = int(row.get('r'))
        if rnum == 1:
            continue
        cells = {}
        for c in row:
            if not c.tag.endswith('}c'):
                continue
            ci = _col_to_idx(c.get('r'))
            t = c.get('t')
            vnode = c.find('m:v', NS)
            fnode = c.find('m:f', NS)
            if fnode is not None and t == 'str':
                cells[ci] = fnode.text
            elif vnode is not None:
                vtxt = vnode.text
                if t == 's':
                    cells[ci] = ss[int(vtxt)] if vtxt is not None else None
                else:
                    cells[ci] = vtxt
        if any(cells.values()):
            rows.append([cells.get(i) for i in range(10)])
    return rows


def _build_img_map(z):
    ci = z.read('xl/cellimages.xml').decode('utf-8')
    pairs = re.findall(r'<etc:cellImage>.*?<xdr:cNvPr[^>]*name="([^"]+)"[^>]*/>.*?<a:blip r:embed="([^"]+)"/>', ci, re.S)
    rels = z.read('xl/_rels/cellimages.xml.rels').decode('utf-8')
    rel_map = dict(re.findall(r'<Relationship Id="([^"]+)"[^>]*Target="([^"]+)"/>', rels))
    return {i: rel_map.get(r) for i, r in pairs}


def _derive_main_no(no):
    s = str(no or '').strip()
    m = re.match(r'^(.*?)-\d{2,4}$', s)
    return m.group(1) if m else s


def import_legacy_excel(src, DATA_DIR):
    """从旧Excel导入数据并保存照片。返回 dict 统计。"""
    PHOTO_ROOT = os.path.join(DATA_DIR, 'photos')
    z = zipfile.ZipFile(src)
    img_map = _build_img_map(z)
    rows_data = _parse_rows(z, _parse_shared(z))

    sub2imgid = {}
    for r in rows_data:
        no = r[9]
        disp = r[8] or ''
        m = re.search(r'DISPIMG\("([^"]+)"', disp)
        if no and m:
            sub2imgid.setdefault(no, m.group(1))

    # 保存图片
    saved = {}
    for sub, imgid in sub2imgid.items():
        media = img_map.get(imgid)
        if not media:
            continue
        mn = _derive_main_no(sub)
        folder = os.path.join(PHOTO_ROOT, mn, '送货单照片', sub)
        os.makedirs(folder, exist_ok=True)
        ext = os.path.splitext(media)[1] or '.jpg'
        dest = os.path.join(folder, '送货单底单' + ext)
        with open(dest, 'wb') as f:
            f.write(z.read('xl/' + media))
        saved.setdefault(sub, []).append(dest)

    # 构建台账行
    rows = []
    for r in rows_data:
        no = r[9]
        if not no:
            continue
        qty = r[5]
        try:
            qty_num = float(qty) if qty not in (None, '') else None
        except Exception:
            qty_num = None
        verify = rg.compute_verify(qty_num, r[7])
        rows.append({
            "订单主号": _derive_main_no(no),
            "客户名称": r[0],
            "送货时间": _serial_to_date(r[1]),
            "产品材料": r[2],
            "产品名称": str(r[3] or '').strip(),
            "产品规格": str(r[4] or '').strip(),
            "数量": qty_num,
            "单位": r[6],
            "包装明细": r[7],
            "送货单号": no,
            "送货单照片": ",".join(saved.get(no, [])),
            "实物照片": "",
            "明细与数量效验": verify,
        })
    new_df = pd.DataFrame(rows, columns=rg.LEDGER_COLUMNS)
    return new_df, saved
