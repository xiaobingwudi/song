# 发货单登记系统

基于 **Streamlit** 的送货单登记管理系统（后台管理系统布局：左侧导航 + 主内容区）。以「订单主号」为单位管理送货单与照片，**台账、选项、照片全部存储在七牛云**，代码可部署到 **Streamlit Community Cloud** 在线使用。

## 核心概念：订单主号

完整送货单号为「主号 + 分号」，如 `SG-260813-0001`：
- **订单主号** = `SG-260813`（业务单元）
- **分号** = `0001`（同一主号货多打印不下时拆成多张分单）

## 功能

- **送货单查询**（默认页）
  - 日历版日期选择：有送货记录的日期高亮，点击查看当天
  - 日期区间搜索、产品材料/客户筛选
  - 结果表格按**送货时间从近到远**排序，含分页、导出 Excel
  - **当月统计**（本月各产品材料分类统计，不受筛选影响）与**明细小计**
- **上传送货单**：上传送货单 Excel，送货单照片按分单上传、实物照片按主号上传
- **数据管理**：查找、编辑、批量替换、删除台账记录；**订单照片管理**（查看/上传/重新上传/删除送货单与实物照片）
- **旧数据导入**：导入旧版含单元格图片的送货 Excel 并合并
- **管理选项**：维护客户/材料选项、访客密码、每页行数

## 目录结构

```
发货单登记系统/
├── app.py               # Streamlit 主程序
├── parser.py            # 送货单 Excel 解析
├── registry.py          # 台账/照片/选项管理
├── qn.py                # 七牛云上传/下载/删除/列出
├── import_legacy.py     # 旧版 Excel（WPS 单元格图片）导入
├── requirements.txt     # 依赖
├── .streamlit/
│   ├── config.toml           # 主题配置
│   └── secrets.toml.example  # 密钥模板（复制为 secrets.toml 填写）
└── data/                # 本地缓存（不入库，数据以七牛云为准）
```

## 本地运行

```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # 填入你的七牛密钥与密码
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

## 云端部署到 Streamlit Community Cloud（免费）

### 1. 数据放七牛云

系统所有数据（台账 `ledger/台账.csv`、选项 `ledger/options.json`、照片 `photos/...`）都会自动上传到七牛云，并作为权威数据源。云端每次启动会自动从七牛云拉取台账、选项和照片到本地缓存。

### 2. 代码放 GitHub

1. 新建一个 **GitHub 仓库**（公开或私有均可）。
2. 把项目文件推送到仓库（**不要**提交 `data/` 目录、`.streamlit/secrets.toml`、`__pycache__`，`.gitignore` 已自动忽略它们）。
3. 推送后，在 GitHub 仓库里应能看到：`app.py`、`parser.py`、`registry.py`、`qn.py`、`import_legacy.py`、`requirements.txt`、`.streamlit/config.toml`、`.streamlit/secrets.toml.example` 等。

### 3. 部署到 Streamlit Cloud

1. 用 GitHub 账号登录 [Streamlit Community Cloud](https://streamlit.io/cloud)。
2. 点 **New app** → 选择你的仓库、分支，Main file path 填 `app.py`，点 Deploy。
3. 部署后打开应用的 **Settings → Secrets**，粘贴以下内容（用你的真实值替换占位符）：

```toml
QN_AK = "你的七牛AccessKey"
QN_SK = "你的七牛SecretKey"
QN_BUCKET = "mryisheng"
QN_DOMAIN = "cdn.bilijinwang.cn"
ADMIN_PASSWORD = "你的管理员密码"
VISITOR_PASSWORD = "你的访客密码"
```

> **重要**：七牛密钥和登录密码通过 **Streamlit Secrets** 管理，**不要**把它们写进代码或提交到 GitHub（公开仓库会泄露）。代码里读取顺序为：`st.secrets` → 环境变量 → 默认值；未配置密钥时七牛功能自动禁用。

4. 保存 Secrets 后，应用自动重启，即可在线访问（`https://你的应用名.streamlit.app`）。

### 多设备 / 无状态说明

Streamlit Community Cloud 的本地磁盘是无状态的（休眠或重启后清空）。系统已做适配：
- 启动时若本地无照片，自动从七牛云下载全部照片。
- 所有新增/修改/删除的照片会自动与七牛云双向同步。
- 台账与选项始终以七牛云为准。

## 使用流程

1. **上传送货单**：上传送货单 Excel → 按订单主号预览 → 送货单照片按分单、实物照片按主号上传 → 确认导入（照片自动传七牛云）。
2. **查询**：默认「送货单查询」页，可查看当月统计与明细小计、点行联动照片。
3. **数据管理**：查找/编辑/替换/删除记录，或管理订单的送货单与实物照片。
