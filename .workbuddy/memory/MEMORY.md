# 项目长期备忘：WowAssist（乌龟服插件管理器，v3.12 起改名）

## 目标与用户
- **服务器背景（2026-10-26 用户阐明）**：乌龟服（TurtleWoW）**已停服**；**水豚乐园 apac.capycraft.io = 原乌龟服亚服**（停服后亚服接收欧服账号，合并改名重新运营）。WowAssist 为水豚乐园而做，客户端仍是乌龟服 1.18 基线。**文案注意**：介绍/宣传勿写"乌龟服管理器"（仿佛还在运营），应写"为水豚乐园打造/基于乌龟服 1.18 客户端"；产品介绍待用户斟酌后定稿再统一改 ui.html/文档。
- 自研乌龟服插件管理器，替代带**序列号锁**的原版黑猫助手(拒绝破解)。用户零编程，交付=双击即用 exe（PyInstaller onefile + pywebview + bottle 8766 + ui.html 单页）。**用户指定 GLM-5.3-Flash**。

## 核心模型：持久化安装（v3.11 起，勿回退到会话覆盖层）
- **v3.12 全面改名**：产品名 WowAssist / 源码目录 `wow-assist/` / 产物 `wowassist-v<版本>.exe` / 数据目录 `AppData\wowassist\` / 资源包 `wowassist_*.zip`；旧数据目录由 `_migrate_legacy_runtime()` 启动时自动 rename 迁移。
- 退出/X关窗/清理还原**不再自动删缓存**；已装的模组/插件/字体与下载缓存都**保留**在客户端与 AppData，下次打开显示「已安装」直接复用。
- **幂等配置**：点「配置组件」先检测每类资源——未下载先下载、已下载不重复下载、未安装才安装、已安装显示「已安装(跳过)」。判定基于 `install_state` 签名(.ok 内容+模组勾选/插件版本) + 磁盘 `_kind_on_disk` 硬校验。
- **WowAbak 全量备份（v3.13）**：总备份夹=游戏根 **WowAbak/**（模组/插件/字体各一子夹，时间戳归档）；安装前目标区域**原有内容一律先备份**（不再只同名冲突）；**清理还原=直删已装组件不备份**（revert_overlay backup=False；客户端原 Fonts 仍恢复）。旧「插件备份」夹不再写入但保留不动。
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
- **一键上传脚本（已固化）**：`wow-assist/上传蓝奏云.py` —— 读 `APP_VERSION`→定位最新 `wowassist-v*.exe`→网页登录→进文件夹→上传→校验（完成判据=刷新后列表真实出现文件名，不再依赖易误判的『100%』文案）。参数：`--file/--folder/--prune(默认关闭)/--no-prune/--skip-upload/--state/--dry-run`（`--prune` 默认 False：用户 2026-10-31 裁定保留所有历史版本 exe，不再删老版本）。凭据走环境变量 **`LZ_USER` + `LZ_PW`**（⚠️ **变量名含 PASS 会被环境过滤成 None**，务必用 `LZ_PW`；脚本也兼容 `LZ_KEY/LZ_SECRET`）。登录态缓存 `temp/lz_state.json`（可删=强制重新登录）。
- **`打包exe.bat` 已串联上传**：打包清理 dist/build 后，若存在 `LZ_USER`+`LZ_PW` 则自动上传到「wow-assist」（`--no-prune`，保留历史版本；exe 永不传 wow-resources 铁律）；未设置则打印提示并跳过。
- **`验证分发链接.py`**：无登录打开分享链接+提取码，列出文件并检查 exe 是否存在/是否重复并存。
- **`上传资源包.py`（v3.12 新增）**：批量上传资源包 zip + 上传清单到分发文件夹，并删除旧命名（`魔兽助手_*.zip`）文件。参数 `--src/--folder/--keep-old/--only-clean`。
- **`replace_v322.py`（2026-10-31 新增）**：**定向覆盖同名版本**用——复用 `上传蓝奏云.py` 的浏览器原语，只删「同名旧 v3.22.exe」与「旧 release_manifest.txt」后重传，**不动其它历史版本 exe（如 v3.21）**。`--prune` 会误删历史版本，故同版本重传必须用本脚本而非 `上传蓝奏云.py --prune`。
- **`build_font_pack.py` / `upload_font_pack.py`（2026-10-31 新增）**：字体包单独重建/替换上传。build_font_pack 从 `.wbdata/resources/Fonts/`(已是思源黑体) 重建 `wowassist_字体.zip`(Fonts/ 前缀) 到 `D:/WorkBuddy/发布/蓝奏云资源包/`；upload_font_pack 进蓝奏云「wow-resources」删旧包(同名并存)再传新包并校验副本数=1。二者仅动字体卷，不碰模组/插件包。
- ⚠️ **上传成功判定铁律**：不能用「DOM 里出现文件名」（webuploader 待上传队列本来就有文件名，会误判）——必须等 `100%`/上传完成提示后**刷新列表**核对文件真的在。此坑曾导致漏传 3 个文件。
- **蓝奏云 Web 操作要点（踩坑记录）**：浏览器**直连**（沙盒代理对该站 `ERR_PROXY_CONNECTION_FAILED`）；用系统 Edge，Playwright 须传 **Windows 路径** `C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`（写 `/c/...` 会解析成 `\c\...` 找不到）；登录页要先访问 `www.lanzou.com` 再点「登录」进 `up.woozooo.com/account.php?action=login`（直接跳 accounts 页会因缺 formhash 失败）；文件管理在 `mydisk.php` 的 **iframe**（url 含 `item=files`）内操作；文件夹行 = `div.f_tb`（id 形如 `f326653283`），`a.f_selb` 弹菜单（下载/删除文件），**`a.f_sela` 才是分享/属性面板**（外链分享地址/自定义外链/密码设置/修改资料/短网址），面板里短网址/自定义外链的 AJAX 常年"获取中..."读不到值，**别用自动点击去取分享链接，易误触删除**。
- **蓝奏云同名文件不覆盖、会并存**：每次上传同名 exe 会多出一份。**用户 2026-10-31 裁定：上传 exe 后不再删除老版本（保留所有历史版本供回退）** → `上传蓝奏云.py` 的 `--prune` 默认改为 **False**，`打包exe.bat` 用 `--no-prune`；仅 `release_manifest.txt` 仍由 `fix_release_manifest.py` 保持唯一副本（清单不能多份并存，否则客户端读哪个不确定）。`--prune` 仍可作临时选项，但默认关闭。
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
- **⭐ 云备份已上线（2026-10-26 23:15）**：Gitee 私有仓库 **https://gitee.com/stcbro/wow-assist**（账号 `stcbro`，私有）。master 全历史已推送；远程 URL 内嵌私人令牌存于 `.git/config`（push 免凭据；令牌可吊销重发，重发后 `git remote set-url origin https://stcbro:<新令牌>@gitee.com/stcbro/wow-assist.git`）。**每次实质改动后应 git push 同步**。新电脑接续 = clone 该仓 + 按交接文档 §9 装依赖/改路径。
- **凭据安全**：文档/记忆/历史提交中的蓝奏云账号密码明文已全部脱敏（git filter-repo 擦除过历史）；今后凭据一律只走环境变量或登录态缓存，不写入 git 追踪文件。
- **项目已 `git init`**（仓库在 `D:/WorkBuddy/wow-assist`，此前完全无版本控制）。`.gitignore` 排除 `.wbdata/`(528MB 本地资源镜像)/`temp/`/`dist`/`build`/`*.exe`/`*.spec`；源码+脚本+UI+**`.workbuddy/memory`** 全部入库。首次提交 `b4306c5`（v3.11 交接基线）。
- **`开发交接文档.md`（项目根）= 换电脑/换账号接续的权威说明书**：目录地图、环境重建（含依赖版本+本机特有路径清单）、四层架构、37 个 API 端点表、UI 规范、发版流水线、蓝奏云资产真相、**24 条踩坑清单**、接续 checklist、回归验证方法、未完成事项、关键行号速查。
- **`wowassist-交接包-20261026.zip`（项目根）**：换机直接带走=源码+脚本+exe+AI记忆+文档。重新生成用 `python 生成交接包.py`。
- ⚠️ 新电脑第一件事：拷整个项目根目录（**含 `.workbuddy/memory`**），并 `git clone`/拷贝 `.git`。

## 用户环境与当前状态
- 水豚乐园 `apac.capycraft.io`；客户端 `D:/game/twmoa_1181`(乌龟服1.18；1920x1080 125%缩放)。
- 最新 exe=**v3.23**（2026-11-01 构建，项目目录唯一 exe；隔离验证 app_ver=3.23 PASS；**尚未上传蓝奏云，待用户真机验证**）。v3.22 已在蓝奏云与用户游戏根（用户已手替并测试过）。v3.23 新增：**账号自动填充根治**（见下）、配置组件日志按用户格式精简、启动 toast/进度统一「游戏正在启动……」、ui.html 更新日志补 v3.21 段+v3.20/3.22 日期。⚠️ 打包后 exe 首次启动可能因 onefile 解压+杀毒扫描超 30s，验证脚本给足 60s。
- **⭐ 账号自动填充机制（2026-11-01 逆向确认，勿回退 Imports/-account 方案）**：乌龟服 1.18 客户端（主客户端与参考 cn2 客户端 WoW.exe 二进制完全相同）内置账号记忆 = **WTF/Config.wtf 的 `SET accountName "账号 密码;"`**（分号结尾；仅 "账号" 则只填账号栏；登录成功后客户端自行改写该行）。`Imports/accountName.txt` 只是参考客户端（lexara 版）入口之一，cVar 才是生效层；命令行 -account/-password 对本客户端无效。实现：`_write_account_cvar/_clear_account_cvar`，启动游戏时写入、未记住时清除。⚠️ 密码明文会进游戏 Config.wtf（客户端机制使然）；WowAssist 自身存储仍 Fernet 加密。**发版必须同步写 ui.html 更新日志（用户要求及时跟进）。**
- ⚠️ **自动更新曾彻底卡死（已修复 2026-10-31）**：根因 = 蓝奏云改版后下载直链/签名藏在 `<iframe src="/fn?...">` 内，旧 `lanzou_core._encrypted_once` 只扫主页面 → `get_direct_link` 100% 返 `PostsignNotFound` → v3.20 用户点「立即更新」既取不到 manifest/exe 直链、UI 也无错误提示（误以为"已是最新"）。修复：让 `_encrypted_once` 复用 `_resolve_download_page` 跟随 iframe，并把含 `wp_sign` 的 AJAX marker 经 `_ajax_download(password=密码)` 走通；`_apply_app_update` 所有失败路径写 `_APP_UPDATE['err']` 复位 `downloading`；新增 `_APP_UPDATE['applying']` 守卫（路由层管理），UI 轮询等整个更新操作结束再收尾。**⚠️ 关键：v3.20 自带的 lanzou_core 同样坏，v3.20 无法自我更新到 v3.22——用户必须手动把游戏根 exe 换成 v3.22 后才能用上修复后的自动更新。**
- ✅ **真实游戏端到端验证已由用户完成**（2026-10-26 19:00 确认）。
- ✅ **更新源已上线**：蓝奏云「wow-assist」文件夹分享 `https://sycc.lanzoum.com/b01i5y8pmf` 提取码 `1acw`（同时是 3.18 自动更新源），已上传 `wowassist-v3.22.exe` + `release_manifest.txt`（**保留历史版本 exe，不再 prune**）。`app_update` 默认源已硬编码为该链接/码。⚠️ **蓝奏云静默拒收 `.json`**（客户端 100% 但服务端不落盘）→ 分发清单必须用 `release_manifest.txt`（内容仍是 JSON）；app 读 manifest 优先 `.txt` 兼容 `.json`，且 manifest 不可读时回退扫描 `wowassist-v*.exe` 文件名推断版本（跳过 md5）。
- ⏳ 待用户动作：①**真机验证 v3.23**（手动把游戏根 `D:/game/twmoa_1181/wowassist.exe` 换成 v3.23：测登录界面自动填充 + 配置组件日志新格式 + 「游戏正在启动……」）；②验证通过后上传蓝奏云「wow-assist」文件夹 + 更新 release_manifest.txt；③可选迁腾讯云COS；④蓝奏云凭据一律只走运行时环境变量/缓存登录态（temp/lz_state.json 不含密码），不写入 git 追踪文件、不写入历史对话之外任何地方。
- **版本号**：3.17 跳过；3.18/3.19/3.20/3.21/3.22 均已发（3.21=账号注入初版+字体说明思源黑体+启动文案；3.22=自动更新修复+源码清理）。最新 **v3.23** = 账号自动填充根治（Config.wtf cVar）+ 配置日志精简 + 启动文案统一（待发布）。

## 待办与暂缓项（用户拍板：先不改，记着以后改）
- **exe 图标待换**：当前 `capy.ico`（`打包exe.bat` 的 `--icon capy.ico` 写死引用；`ui.html` 亦引用作 favicon）。用户 2026-10-31 决定先不换，以后改；风格未定（候选：水豚卡通吉祥物 / WA 字母标志 / 水豚+游戏科技感）。换图时若改文件名须同步改 bat 与 ui.html 引用。
- **字体包侵权已替换（2026-10-31 完成）**：原 `wowassist_字体.zip` 内 9 个文件 = 方正粗圆 M03(商业)×7 + 文鼎 LingHei(非商业)×2，分发即侵权。已按用户"按你的建议用思源黑体"用 **思源黑体/Noto Sans SC（SIL OFL，可商用可再分发）** 替换：本地镜像 `.wbdata/resources/Fonts/` 9 个槽位文件全部就地换成思源黑体 Regular(wght 400, TrueType) + 保留 `.ok` 标记；`build_font_pack.py` 重建 `wowassist_字体.zip`(54.2MB, Fonts/ 前缀)；`upload_font_pack.py` 登录蓝奏云「wow-resources」删旧侵权包(37.1MB)并上传新包，校验副本数=1（已上线）。⚠️ 9 槽位皆同思源黑体（含 SKURRI 伤害数字槽，未保留客户端原字体——因暴雪原字体亦不可再分发，统一思源黑体最干净）。exe 本身始终干净。
- **release_manifest.txt 已修正并上线（2026-10-31）**：md5 改为 `fb091c403af7123c9958ef3fc1e7ab2a`、size `17077118`（对应实际部署的 v3.20 exe）；旧 md5 会导致 3.18/3.19 用户自动更新 md5 校验失败被拒。`fix_release_manifest.py` 已删旧副本并上传修正版到蓝奏云「wow-assist」文件夹，校验副本数=1。
