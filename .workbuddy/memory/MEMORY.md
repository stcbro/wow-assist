# 项目长期备忘：魔兽助手（乌龟服插件管理器）

## 目标与用户
- 自研乌龟服插件管理器，替代带**序列号锁**的原版黑猫助手(拒绝破解)。用户零编程，交付=双击即用 exe（PyInstaller onefile + pywebview + bottle 8766 + ui.html 单页）。**用户指定 GLM-5.3-Flash**。

## 核心模型：持久化安装（v3.11 起，勿回退到会话覆盖层）
- 退出/X关窗/清理还原**不再自动删缓存**；已装的模组/插件/字体与下载缓存都**保留**在客户端与 AppData，下次打开显示「已安装」直接复用。
- **幂等配置**：点「配置组件」先检测每类资源——未下载先下载、已下载不重复下载、未安装才安装、已安装显示「已安装(跳过)」。判定基于 `install_state` 签名(.ok 内容+模组勾选/插件版本) + 磁盘 `_kind_on_disk` 硬校验。
- **冲突备份**：安装模组/插件/字体前，把游戏目录里**同名/冲突文件先 `_move_to_backup` 到「插件备份/<tag>_时间戳」**再覆盖；不再直接删除用户原文件。函数：`_safe_install_file/_safe_install_tree/_move_to_backup/_backup_dir_for`。
- **缓存留盘 + 30 天 GC**：下载缓存存 `AppData\魔兽助手\resources\`，关闭 exe 不删、可复用；`cache_gc()` 按 `cache_lastused` + `keep_days`(默认30) 删超期缓存（启动后台跑一次）。设置走 `/api/cache_config`→config.cache{auto_clean,keep_days}。
- **手动清理还原**：`清理还原`=结束游戏→`revert_overlay`(备份式移除)→清 install_state；不删缓存，原文件进「插件备份」。
- 启动不再自愈还原（移除 `_restore_all_overlays` 调用）；`_teardown` 为 no-op（只写退出日志）。
- **运行时全在 `AppData\魔兽助手\`**（config/缓存/temp/downloads/run.log/还原.log）；exe 所在目录=游戏根，零污染。
- **便携**：exe 同目录有 WoW.exe+Interface 自动识别游戏根；`_to_root/_to_addons` 归一任意层路径；`/api/targets` 返完整 exe 路径+版本号(乌龟服显 1.18)。

## 模组加载：内置注入器（v3.10，勿回退）
- **游戏根目录自始至终不再释放 VanillaFixes.exe** —— 已用内置注入器取代（用户最终目标，已达成）。
- 真相：VanillaFixes.exe 唯一价值是早期注入 `VfPatcher.dll`+`nampower.dll`；其余 7 个模组 DLL 由**游戏自带 twloader.dll**(TurtleLoader) 读 dlls.txt 加载。铁证=`游戏根/Logs/twloader.log`（7 个 `Loaded:`、仅那两个 `Already loaded`）。VfPatcher=MinHook+加载器，内含 dlls.txt 与"需 1.6.1-1.12.1 客户端"校验。
- 实现：`launch_game` 同步 CreateProcessW 启动 WoW.exe(cwd=游戏根)→后台 `_inject_after_launch(pid,[VfPatcher,nampower])`：等 kernel32 出现→LoadLibraryW 地址=32位kernel32基址+RVA(解析 SysWOW64\kernel32.dll；本机基址 0x76370000、RVA 0x1f640)→CreateRemoteThread 注入。界面 0.09s 即返回。
- 坑：①**挂起态注入必失败**(模块表空、LoadLibraryW 返 0 且 GLE=0)，须等 kernel32；②成败只看**目标进程模块表**，退出码不可靠；③VirtualAllocEx 返回值按无符号处理；④失败不阻断——twloader 兜底；⑤进程退出即结束。日志落 run.log `[模组]` 行。
- 装模组/本地导入不再拷贝该 exe；老残留自动清理；打包已移除对应 `--add-data`。

## 分发
- **分发链接真相（2026-10-26 核实）**：`https://sycc.lanzoum.com/b01i5y3r7c` + 提取码 `9p81` 指向的分享是文件夹 **「乌龟服资源包20261025」**（`fol14138872`），内含 插件包part1~4.zip / 字体.zip / 模组包.zip / 上传清单.txt。**「魔兽助手」文件夹（`fol14144103`）是另一个未对外分享的目录**——两者不是同一个，别再混。
- **exe 现在放在两个位置**：「乌龟服资源包20261025」（=有对外链接，新电脑直接用原链接下）与「魔兽助手」（干净专区，仅内部）。两处都只有一份 `魔兽助手 v3.11.exe`。
- `get_direct_link` 返 `(state,link)` 勿按 (url,err) 解包；反爬(iframe CDN/websign=2/acw_sc__v2)已处理；抓取 3 次重试，失败原因落 run.log `[蓝奏云]` 行。**manifest.json 未上传**。
- **一键上传脚本（已固化）**：`插件助手/上传蓝奏云.py` —— 读 `APP_VERSION`→定位最新 `魔兽助手 v*.exe`→网页登录→进文件夹→上传→校验→`--prune` 清理同名副本与旧版本。参数：`--file/--folder/--prune/--skip-upload/--state/--dry-run`。凭据走环境变量 **`LZ_USER` + `LZ_PW`**（⚠️ **变量名含 PASS 会被环境过滤成 None**，务必用 `LZ_PW`；脚本也兼容 `LZ_KEY/LZ_SECRET`）。登录态缓存 `temp/lz_state.json`（可删=强制重新登录）。
- **`打包exe.bat` 已串联上传**：打包清理 dist/build 后，若存在 `LZ_USER`+`LZ_PW` 则自动上传到「魔兽助手」和「乌龟服资源包20261025」两个文件夹（各带 `--prune`）；未设置则打印提示并跳过。
- **`验证分发链接.py`**：无登录打开分享链接+提取码，列出文件并检查 exe 是否存在/是否重复并存。
- **蓝奏云 Web 操作要点（踩坑记录）**：浏览器**直连**（沙盒代理对该站 `ERR_PROXY_CONNECTION_FAILED`）；用系统 Edge，Playwright 须传 **Windows 路径** `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`（写 `/c/...` 会解析成 `\c\...` 找不到）；登录页要先访问 `www.lanzou.com` 再点「登录」进 `up.woozooo.com/account.php?action=login`（直接跳 accounts 页会因缺 formhash 失败）；文件管理在 `mydisk.php` 的 **iframe**（url 含 `item=files`）内操作；文件夹行 = `div.f_tb`（id 形如 `f326653283`），`a.f_selb` 弹菜单（下载/删除文件），**`a.f_sela` 才是分享/属性面板**（外链分享地址/自定义外链/密码设置/修改资料/短网址），面板里短网址/自定义外链的 AJAX 常年"获取中..."读不到值，**别用自动点击去取分享链接，易误触删除**。
- **蓝奏云同名文件不覆盖、会并存**：每次上传同名 exe 都会多出一份，**必须 `--prune`**（保留 DOM 顺序第一个=最新，删其余）。且**上传后列表是异步刷新的**，清理前须强制刷新列表，否则读到旧列表会漏删。
- **WorkBuddy 内置云不可用于公开分发**（需登录/无公开URL/签名1h）。备选腾讯云COS。
- **内置「自定义直链源」(v3.9)**：config.direct.urls 存任意直链，按文件名归类，优先级 直链>蓝奏云>手动。坑：中文 URL 须 quote path 否则 UnicodeEncodeError。

## 桌面窗口技术要点（定型）
- `_init_dpi_awareness()` 必须 main() 第一行，否则启动弹窗/文件框文字发虚。
- 居中：显式传**逻辑像素**=GetSystemMetrics(物理)/GetDpiForSystem；pywebview 的 CenterScreen 实测无效(落 32,32)。已验证偏差 0px。
- 托盘：STA 线程(Start 前设 STA)+隐藏宿主 Form；**Visible 改动须 `form.BeginInvoke` 调度回托盘线程**(跨线程直改=悬停即消失)；ni/icon 强引用防 GC；ICO 正方形多尺寸；左键恢复、右键只弹【退出】。
- 黑窗：禁 AllocConsole；子进程走 `_run_hidden/_popen_hidden`(CREATE_NO_WINDOW)。
- 打包（插件助手/，`PYTHONPATH=` 清空）：onefile+windowed+`--icon capy.ico`+`--add-data "ui.html;." "capy.ico;."`+`--collect-all webview/pythonnet/clr_loader`+`--hidden-import bottle/proxy_tools`。**版本号机制**：`addon_helper.py` 顶部 `APP_VERSION = "x.y"` 为**单一来源**；`打包exe.bat` 用 `findstr` 提取并 `--name "魔兽助手 v%APPVER%"`，**发版只改 APP_VERSION 即自动带版本号**（如 `魔兽助手 v3.11.exe`）。**打包后清理 dist/ 与 build/**。项目目录保留 `魔兽助手 v<版本>.exe` 历版本（带版本号一目了然，不再限唯一）；游戏根 `D:/game/twmoa_1181` 保持 `魔兽助手.exe` 运行名（去版本号，兼容桌面快捷方式）。蓝奏云上传带版本号文件并删旧无版本号份；部署前 taskkill。

## UI 规范（验收标准）
- ui.html 暗色侧栏单页：首页/服务器/模组/插件/字体/下载/更新日志。980x680 不可调。首页=路径输入+【设置/打开】+【配置组件/启动游戏/清理还原】(清理=5s倒计时遮罩)，两列 home-kv 15px 居中。
- 更新日志明细统一 `.cl-detail`；弹窗用 askConfirm（禁原生 confirm）；PLUGIN_INFO 150 条源自 `插件用途说明.md`。进度：下载→模组→插件→字体。

## 沙盒测试坑（仅 WorkBuddy 环境）
- 跑 python 前 `PYTHONPATH=` 清空；长任务可能被强杀≠生产 bug。`&` 起的 exe 随命令结束被杀，须同一命令内"启动→调用→验证"，测完 taskkill 收尾。
- 沙盒代理(127.0.0.1:54554)对 lanzoum 间歇 502，网络复现不可靠。

## 用户环境与当前状态
- 水豚乐园 `apac.capycraft.io`；客户端 `D:/game/twmoa_1181`(乌龟服1.18；1920x1080 125%缩放)。
- 最新 exe=**v3.11**（12:33 打包，持久化安装模型：幂等配置+冲突备份+缓存留盘30天GC+手动清理还原；游戏目录无 VanillaFixes.exe），已部署两处（项目目录 + `D:/game/twmoa_1181`）；单元+HTTP 冒烟回归通过。**分发已就绪：原分享链接 b01i5y3r7c/9p81 列表首项即 `魔兽助手 v3.11.exe`(16.2M)，已实测验证无重复**（2026-10-26 16:20）。
- 待办：①**用户实测确认模组生效 + 持久化流程真实游戏验证**（沙盒未启真实游戏）；②上传 manifest.json 启用增量更新；③可选迁腾讯云COS；④用户仍未改蓝奏云密码（`***REDACTED***` 在对话里明文过），提醒其修改。
