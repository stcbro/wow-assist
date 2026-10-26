# 项目长期备忘：WowAssist（乌龟服插件管理器，v3.12 起改名）

## 目标与用户
- 自研乌龟服插件管理器，替代带**序列号锁**的原版黑猫助手(拒绝破解)。用户零编程，交付=双击即用 exe（PyInstaller onefile + pywebview + bottle 8766 + ui.html 单页）。**用户指定 GLM-5.3-Flash**。

## 核心模型：持久化安装（v3.11 起，勿回退到会话覆盖层）
- **v3.12 全面改名**：产品名 WowAssist / 源码目录 `wow-assist/` / 产物 `wowassist-v<版本>.exe` / 数据目录 `AppData\wowassist\` / 资源包 `wowassist_*.zip`；旧数据目录由 `_migrate_legacy_runtime()` 启动时自动 rename 迁移。
- 退出/X关窗/清理还原**不再自动删缓存**；已装的模组/插件/字体与下载缓存都**保留**在客户端与 AppData，下次打开显示「已安装」直接复用。
- **幂等配置**：点「配置组件」先检测每类资源——未下载先下载、已下载不重复下载、未安装才安装、已安装显示「已安装(跳过)」。判定基于 `install_state` 签名(.ok 内容+模组勾选/插件版本) + 磁盘 `_kind_on_disk` 硬校验。
- **冲突备份**：安装模组/插件/字体前，把游戏目录里**同名/冲突文件先 `_move_to_backup` 到「插件备份/<tag>_时间戳」**再覆盖；不再直接删除用户原文件。函数：`_safe_install_file/_safe_install_tree/_move_to_backup/_backup_dir_for`。
- **缓存留盘 + 30 天 GC**：下载缓存存 `AppData\wowassist\resources\`，关闭 exe 不删、可复用；`cache_gc()` 按 `cache_lastused` + `keep_days`(默认30) 删超期缓存（启动后台跑一次）。设置走 `/api/cache_config`→config.cache{auto_clean,keep_days}。
- **手动清理还原**：`清理还原`=结束游戏→`revert_overlay`(备份式移除)→清 install_state；不删缓存，原文件进「插件备份」。
- 启动不再自愈还原（移除 `_restore_all_overlays` 调用）；`_teardown` 为 no-op（只写退出日志）。
- **运行时全在 `AppData\wowassist\`**（config/缓存/temp/downloads/run.log/还原.log）；exe 所在目录=游戏根，零污染。
- **便携**：exe 同目录有 WoW.exe+Interface 自动识别游戏根；`_to_root/_to_addons` 归一任意层路径；`/api/targets` 返完整 exe 路径+版本号(乌龟服显 1.18)。

## 模组加载：内置注入器（v3.10，勿回退）
- **游戏根目录自始至终不再释放 VanillaFixes.exe** —— 已用内置注入器取代（用户最终目标，已达成）。
- 真相：VanillaFixes.exe 唯一价值是早期注入 `VfPatcher.dll`+`nampower.dll`；其余 7 个模组 DLL 由**游戏自带 twloader.dll**(TurtleLoader) 读 dlls.txt 加载。铁证=`游戏根/Logs/twloader.log`（7 个 `Loaded:`、仅那两个 `Already loaded`）。VfPatcher=MinHook+加载器，内含 dlls.txt 与"需 1.6.1-1.12.1 客户端"校验。
- 实现：`launch_game` 同步 CreateProcessW 启动 WoW.exe(cwd=游戏根)→后台 `_inject_after_launch(pid,[VfPatcher,nampower])`：等 kernel32 出现→LoadLibraryW 地址=32位kernel32基址+RVA(解析 SysWOW64\kernel32.dll；本机基址 0x76370000、RVA 0x1f640)→CreateRemoteThread 注入。界面 0.09s 即返回。
- 坑：①**挂起态注入必失败**(模块表空、LoadLibraryW 返 0 且 GLE=0)，须等 kernel32；②成败只看**目标进程模块表**，退出码不可靠；③VirtualAllocEx 返回值按无符号处理；④失败不阻断——twloader 兜底；⑤进程退出即结束。日志落 run.log `[模组]` 行。
- 装模组/本地导入不再拷贝该 exe；老残留自动清理；打包已移除对应 `--add-data`。

## 分发
- **⭐ 铁律（2026-10-26 用户定，永远生效）：「wow-resources」文件夹永远不传生成物**（exe 等构建产物一律禁止，只放资源包 zip + 上传清单）。exe 只传「wow-assist」文件夹。`上传蓝奏云.py` 已内置硬拦截（对 wow-resources 目标直接退出码 3）。
- **分发链接真相（2026-10-26 22:20 用户纠正后更新）**：`https://sycc.lanzoum.com/b01i5y3r7c` + 提取码 `9p81` 指向的分享文件夹原名「乌龟服资源包20261025」（`fol14138872`），**已被用户在网页改名为「wow-resources」**；内含 `wowassist_插件包_part1~4.zip` / `wowassist_字体.zip` / `wowassist_模组包.zip` / 上传清单.txt，**不含 exe**。**「wow-assist」文件夹（`fol14145295`）是另一个目录**（只放 exe，**待作者在网页手动分享**）——两者不是同一个，别再混。
- **exe 放在两个位置**：「wow-resources」（=对外分享链接指向的**资源包**文件夹，**用户明确决定不放 exe**）与「wow-assist」（exe 专区，待作者在网页生成分享链接后对外）。旧文件夹「魔兽助手」`fol14144103` 已删除。
- `get_direct_link` 返 `(state,link)` 勿按 (url,err) 解包；反爬(iframe CDN/websign=2/acw_sc__v2)已处理；抓取 3 次重试，失败原因落 run.log `[蓝奏云]` 行。**manifest.json 未上传**。
- **一键上传脚本（已固化）**：`wow-assist/上传蓝奏云.py` —— 读 `APP_VERSION`→定位最新 `wowassist-v*.exe`→网页登录→进文件夹→上传→校验→`--prune` 清理同名副本与旧版本。参数：`--file/--folder/--prune/--skip-upload/--state/--dry-run`。凭据走环境变量 **`LZ_USER` + `LZ_PW`**（⚠️ **变量名含 PASS 会被环境过滤成 None**，务必用 `LZ_PW`；脚本也兼容 `LZ_KEY/LZ_SECRET`）。登录态缓存 `temp/lz_state.json`（可删=强制重新登录）。
- **`打包exe.bat` 已串联上传**：打包清理 dist/build 后，若存在 `LZ_USER`+`LZ_PW` 则自动上传到「wow-assist」和「wow-resources」两个文件夹（各带 `--prune`）；未设置则打印提示并跳过。
- **`验证分发链接.py`**：无登录打开分享链接+提取码，列出文件并检查 exe 是否存在/是否重复并存。
- **`上传资源包.py`（v3.12 新增）**：批量上传资源包 zip + 上传清单到分发文件夹，并删除旧命名（`魔兽助手_*.zip`）文件。参数 `--src/--folder/--keep-old/--only-clean`。
- ⚠️ **上传成功判定铁律**：不能用「DOM 里出现文件名」（webuploader 待上传队列本来就有文件名，会误判）——必须等 `100%`/上传完成提示后**刷新列表**核对文件真的在。此坑曾导致漏传 3 个文件。
- **蓝奏云 Web 操作要点（踩坑记录）**：浏览器**直连**（沙盒代理对该站 `ERR_PROXY_CONNECTION_FAILED`）；用系统 Edge，Playwright 须传 **Windows 路径** `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`（写 `/c/...` 会解析成 `\c\...` 找不到）；登录页要先访问 `www.lanzou.com` 再点「登录」进 `up.woozooo.com/account.php?action=login`（直接跳 accounts 页会因缺 formhash 失败）；文件管理在 `mydisk.php` 的 **iframe**（url 含 `item=files`）内操作；文件夹行 = `div.f_tb`（id 形如 `f326653283`），`a.f_selb` 弹菜单（下载/删除文件），**`a.f_sela` 才是分享/属性面板**（外链分享地址/自定义外链/密码设置/修改资料/短网址），面板里短网址/自定义外链的 AJAX 常年"获取中..."读不到值，**别用自动点击去取分享链接，易误触删除**。
- **蓝奏云同名文件不覆盖、会并存**：每次上传同名 exe 都会多出一份，**必须 `--prune`**（保留 DOM 顺序第一个=最新，删其余）。且**上传后列表是异步刷新的**，清理前须强制刷新列表，否则读到旧列表会漏删。
- **WorkBuddy 内置云不可用于公开分发**（需登录/无公开URL/签名1h）。备选腾讯云COS。
- **内置「自定义直链源」(v3.9)**：config.direct.urls 存任意直链，按文件名归类，优先级 直链>蓝奏云>手动。坑：中文 URL 须 quote path 否则 UnicodeEncodeError。

## 桌面窗口技术要点（定型）
- `_init_dpi_awareness()` 必须 main() 第一行，否则启动弹窗/文件框文字发虚。
- 居中：显式传**逻辑像素**=GetSystemMetrics(物理)/GetDpiForSystem；pywebview 的 CenterScreen 实测无效(落 32,32)。已验证偏差 0px。
- 托盘：STA 线程(Start 前设 STA)+隐藏宿主 Form；**Visible 改动须 `form.BeginInvoke` 调度回托盘线程**(跨线程直改=悬停即消失)；ni/icon 强引用防 GC；ICO 正方形多尺寸；左键恢复、右键只弹【退出】。
- 黑窗：禁 AllocConsole；子进程走 `_run_hidden/_popen_hidden`(CREATE_NO_WINDOW)。
- 打包（`wow-assist/`，`PYTHONPATH=` 清空）：onefile+windowed+`--icon capy.ico`+`--add-data "ui.html;." "capy.ico;."`+`--collect-all webview/pythonnet/clr_loader`+`--hidden-import bottle/proxy_tools`。**版本号机制**：`addon_helper.py` 顶部 `APP_VERSION = "x.y"` 为**单一来源**；`打包exe.bat` 用 `findstr` 提取并 `--name "wowassist-v%APPVER%"`，**发版只改 APP_VERSION 即自动带版本号**（如 `wowassist-v3.12.exe`）。**打包后清理 dist/ 与 build/**。项目目录保留 `wowassist-v<版本>.exe`；游戏根 `D:/game/twmoa_1181` 用 `wowassist.exe` 运行名。蓝奏云上传带版本号文件并删旧无版本号份；部署前 taskkill。

## UI 规范（验收标准）
- ui.html 暗色侧栏单页：首页/服务器/模组/插件/字体/下载/更新日志。980x680 不可调。首页=路径输入+【设置/打开】+【配置组件/启动游戏/清理还原】(清理=5s倒计时遮罩)，两列 home-kv 15px 居中。
- 更新日志明细统一 `.cl-detail`；弹窗用 askConfirm（禁原生 confirm）；PLUGIN_INFO 150 条源自 `插件用途说明.md`。进度：下载→模组→插件→字体。

## 沙盒测试坑（仅 WorkBuddy 环境）
- 跑 python 前 `PYTHONPATH=` 清空；长任务可能被强杀≠生产 bug。`&` 起的 exe 随命令结束被杀，须同一命令内"启动→调用→验证"，测完 taskkill 收尾。
- 沙盒代理(127.0.0.1:54554)对 lanzoum 间歇 502，网络复现不可靠。

## 版本控制与交接（2026-10-26 起）
- **项目已 `git init`**（仓库在 `D:/WorkBuddy/wow-assist`，此前完全无版本控制）。`.gitignore` 排除 `.wbdata/`(528MB 本地资源镜像)/`temp/`/`dist`/`build`/`*.exe`/`*.spec`；源码+脚本+UI+**`.workbuddy/memory`** 全部入库。首次提交 `b4306c5`（v3.11 交接基线）。
- **`开发交接文档.md`（项目根）= 换电脑/换账号接续的权威说明书**：目录地图、环境重建（含依赖版本+本机特有路径清单）、四层架构、37 个 API 端点表、UI 规范、发版流水线、蓝奏云资产真相、**24 条踩坑清单**、接续 checklist、回归验证方法、未完成事项、关键行号速查。
- **`wowassist-交接包-20261026.zip`（项目根）**：换机直接带走=源码+脚本+exe+AI记忆+文档。重新生成用 `python 生成交接包.py`。
- ⚠️ 新电脑第一件事：拷整个项目根目录（**含 `.workbuddy/memory`**），并 `git clone`/拷贝 `.git`。

## 用户环境与当前状态
- 水豚乐园 `apac.capycraft.io`；客户端 `D:/game/twmoa_1181`(乌龟服1.18；1920x1080 125%缩放)。
- 最新 exe=**v3.12**（改名版：WowAssist / wow-assist 目录 / wowassist-v3.12.exe / AppData\wowassist / wowassist_*.zip），已部署两处（源码目录 + `D:/game/twmoa_1181/wowassist.exe`）；HTTP 冒烟通过（两接口 200、数据目录已迁移）。**分发已就绪：原分享链接 b01i5y3r7c/9p81 列表首项即 `wowassist-v3.12.exe`**。
- ✅ **真实游戏端到端验证已由用户完成**（2026-10-26 19:00 确认）。
- 待办：①**「wow-assist」蓝奏云文件夹的对外分享链接待作者在网页手动生成**（拿到链接+提取码后需更新 `addon_helper.py` 默认 folder 配置与文档）；②上传 manifest.json 启用增量更新；③可选迁腾讯云COS；④用户仍未改蓝奏云密码（`***REDACTED***` 在对话里明文过），提醒其修改。
