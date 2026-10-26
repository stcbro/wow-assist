# 蓝奏云直链解析器（学习项目）

用纯 Python 标准库实现的蓝奏云直链解析工具，**零第三方依赖**。
算法学习自开源项目 [KCNLanzouDirectLink](https://github.com/JDDKCN/KCNLanzouDirectLink)（AGPL-3.0），为本项目的 Python 学习性重实现。若要分发本工具，请同样遵循 AGPL-3.0。

## 快速开始

```bash
# 图形界面（自动打开浏览器）
python lanzou_gui.py

# 命令行
python cli.py https://xxx.lanzouw.com/xxxxx
python cli.py https://xxx.lanzouw.com/xxxxx 访问密码

# 反爬算法离线自测
python test_solver.py
```

下载的文件保存在 `downloads/` 目录。

## 解析原理（学习重点）

整个软件的"魔法"其实只有四步：

### 1️⃣ 请求分享页 → 撞上阿里云盾

蓝奏云的分享页挂在阿里云 ESA（云盾）后面。首次请求会返回一个 JS 挑战页，
特征是 HTML 开头 + `var arg1='...'`。浏览器会执行这段 JS 算出一个
`acw_sc__v2` Cookie 再重新请求；我们的做法是**把这个算法搬到 Python 里直接算**。

### 2️⃣ acw_sc__v2 的计算（`AntiCrawler.solve`）

挑战页 JS 里藏着三样东西：

| 要素 | 提取方式 |
|---|---|
| `arg1` | 40 位十六进制串（正则 `=\s*['"]([0-9a-f]{40})['"]`） |
| `posList` | 形如 `[0x17, 0x7, ...]` 的**位置重排表**（值从 1 开始） |
| `mask` | 一个 Base64 变体编码的**异或掩码**（阿里云自有字典：小写在前大写在后，解码前要翻转大小写！） |

计算过程：
```
① 位置重排:  arg2[i] = arg1[ posList[i] - 1 ]
② 逐字节异或: out[i] = arg2 的第i字节 XOR mask 的第i字节 （hex 串按 2 字符 = 1 字节）
③ 拼成 Cookie: acw_sc__v2 = 结果
```
把 Cookie 塞进会话再请求，盾就通过了。本项目在 `test_solver.py` 里用模拟页面做了离线验证。

### 3️⃣ 从页面提取下载签名

蓝奏云页面有新旧两版，需要兼容：

- **新版（iframe 型）**：主页面内嵌 iframe，iframe 里有
  `wp_sign = '...'` 和 `ajaxm.php?file=xxx` 路径
- **旧版（传统型）**：直接有 `var vkjxld = '...'` + `var hyggid = '...'`，两段拼接即中间链接
- **跳转型**：`<div class="mh"><a href="...">` 指向真实下载页

### 4️⃣ AJAX 换取直链 + 跟随 302

带着签名 POST `ajaxm.php`（`action=downprocess`），返回 JSON：
```json
{ "zt": 1, "dom": "https://xxx", "url": "?xxxxxxxxxx" }
```
拼出中间链接 `dom + /file/ + url`，再 GET 它但**不跟随重定向**，
响应的 `Location` 头就是最终直链。

### 其他细节（都是实战踩出来的）

- **加密分享**：先从页面提取 `data:{sign:...}`，POST 时多带一个 `p=密码`
- **广告下崽器页**：蓝奏云偶尔返回推广页（特征词"使用全能电脑助手下载"等），检测到就重试
- **域名变体**：lanzoue / lanzouw / lanzoui / lanzoub ... 用正则 `lanzo[a-z0-9-]*` 一网打尽
- **前端风控 Cookie**：POST 前需带上 `pc_ad1=1`、`codelen=1`

## 文件结构

```
LanzouTool/
├── lanzou_core.py    # 核心库：反爬求解 + 页面解析 + AJAX + 302 跟踪
├── lanzou_gui.py     # 浏览器 GUI（标准库 http.server，内嵌前端页面）
├── cli.py            # 命令行入口
├── test_solver.py    # acw_sc__v2 算法离线验证
└── downloads/        # 批量下载的文件保存位置
```

## 与"黑猫助手"的关系

黑猫助手本质上是 `KCNLanzouDirectLink` 这个开源库 + 一层 GUI/批量逻辑，
再用 BitMono 混淆后打包。你现在拥有的这份 Python 实现，覆盖了它最核心的解析能力，
而且代码完全可读、可自行修改——这就是"学习它"的最好结果。
