# 项目长期备忘：WowAssist（水豚乐园插件管理器，v3.12 起改名）

## 目标与背景
- 乌龟服已停服；**水豚乐园 apac.capycraft.io = 原乌龟服亚服**。WowAssist 为水豚乐园而做，客户端=乌龟服 1.18（`D:/game/twmoa_1181`）。文案勿写"乌龟服管理器"，写"为水豚乐园打造"。
- 替代带序列号锁的黑猫助手(拒绝破解)。用户零编程，交付=双击即用 exe（PyInstaller onefile + pywebview + bottle 8766 + ui.html 单页）。用户指定 GLM-5.3-Flash。

## 核心模型（v3.11+ 持久化安装，勿回退）
- v3.12 起统一命名：`wow-assist/` 源码、`wowassist-v<版本>.exe`、`AppData\wowassist\` 运行时、`wowassist_*.zip` 资源包；旧目录 `_migrate_legacy_runtime()` 自动迁移。
- **幂等配置**：已下载不重下、已安装跳过（install_state 签名 + 磁盘硬校验）；退出/清理还原**不删缓存**（30 天 GC：cache_lastused+keep_days）。
- **WowAbak/**=游戏根总备份夹；安装前原有内容先备份；清理还原=直删已装组件（客户端原 Fonts 仍恢复）。启动不自愈还原；_teardown 为 no-op。
- 便携：exe 所在目录=游戏根（有 WoW.exe+Interface 即识别）。

## 模组加载：内置注入器（v3.10，勿回退）
- 游戏根**不再释放 VanillaFixes.exe**。真相：只有 VfPatcher.dll+nampower.dll 需早期注入；其余 7 个模组 DLL 由游戏自带 twloader.dll 读 dlls.txt 加载（铁证=Logs/twloader.log）。
- `launch_game` 同步 CreateProcessW 启动→后台注入（等 kernel32 出现→LoadLibraryW→CreateRemoteThread）。坑：挂起态注入必失败；成败只看目标进程模块表；失败不阻断（twloader 兜底）。

## 分发（蓝奏云）⭐铁律
- **「wow-resources」(`fol14138872`，分享 b01i5y3r7c/9p81) 永不传 exe**，只放资源包 zip+清单；**exe 只传「wow-assist」(`fol14145295`，分享 b01i5y8pmf/1acw = 自动更新源)**。`上传蓝奏云.py` 已硬拦截。
- **保留所有历史版本 exe（用户 2026-10-31 裁定，--prune 默认 False）**；仅 release_manifest.txt 须唯一副本（蓝奏云静默拒收 .json，清单用 .txt 内容 JSON；manifest 不可读时 app 回退扫 `wowassist-v*.exe` 文件名）。
- ⚠️ 上传成功判定：必须等 100% 后**刷新列表**核对（DOM 出现文件名≠传完，曾漏传 3 个）。同名文件不覆盖会并存。
- 脚本：`上传蓝奏云.py`（凭据走 env `LZ_USER`+`LZ_PW`，⚠️变量名含 PASS 会被过滤；登录态缓存 temp/lz_state.json）、`replace_v322.py`（同版本定向覆盖模板）、`上传资源包.py`、`build_font_pack.py`/`upload_font_pack.py`（字体卷专用）、`验证分发链接.py`。
- 蓝奏云 Web 操作：浏览器直连（沙盒代理会 502）；Playwright 用 Edge **Windows 路径**；登录先 www.lanzou.com 再进 account.php；文件管理在 mydisk.php 的 iframe 内；**别自动点分享面板取链接（易误触删除）**。`get_folder_files` 返 `(state, files)` 元组。
- **自动更新修复（2026-10-31）**：蓝奏云直链藏在 `<iframe src="/fn?...">`，`_encrypted_once` 已改为跟随 iframe + `_ajax_download(password=密码)`；`_apply_app_update` 失败路径全写 err 复位；`_APP_UPDATE['applying']` 守卫。
- **v3.9 自定义直链源**：config.direct.urls，优先级 直链>蓝奏云>手动；中文 URL 须 quote。

## 桌面窗口/打包（定型）
- `_init_dpi_awareness()` 必须 main() 第一行；居中传逻辑像素（pywebview CenterScreen 无效）；托盘 STA 线程+BeginInvoke 调度 Visible；禁 AllocConsole，子进程 CREATE_NO_WINDOW。
- 打包（`打包exe.bat`）：onefile+windowed+capy.ico+add-data ui.html/capy.ico+collect-all webview/pythonnet/clr_loader。**APP_VERSION（addon_helper.py 顶部）=版本号单一来源**，发版只改它；打包后清 dist/build；游戏根用 `wowassist.exe` 运行名，部署前 taskkill。
- ⚠️ onefile 验证坑：`proc.kill()` 只杀父进程，**子进程存活占 8766 导致假 PASS**——必须 `taskkill /T /F` 杀整棵树再验证；exe 首启可能超 30s（解压+杀毒），验证给足 60s。

## UI 规范
- 暗色侧栏单页：首页/服务器/模组/插件/字体/下载/更新日志。980x680。弹窗用 askConfirm 禁原生 confirm；更新日志 `.cl-detail`；**发版必须同步写 ui.html 更新日志（用户要求及时跟进）**。
- v3.23 定：**日志区最新在最上面**（4 处渲染点倒序）；完成摘要不拼状态尾巴；配置组件日志=模组/插件/字体各一行装入摘要+「写入dlls.txt」；完成时按最终 /api/progress 快照整体重绘（防 250ms 轮询丢尾行）；`_reset_progress` 先把上轮明细滚入 _HIST（清理还原记录不被抹掉）。

## 版本控制
- Gitee 私有仓 **https://gitee.com/stcbro/wow-assist**（令牌内嵌 .git/config，push 免凭据）；**每次实质改动后 git push**。`.gitignore` 排除 .wbdata/temp/dist/build/*.exe/*.spec。
- 凭据永不入 git；蓝奏云密码明文已从历史擦除（filter-repo）。
- 交接产物（开发交接文档等 4 件）已删（4696da3），git 历史可 `git show <提交>:<文件>` 找回。新电脑接续=clone 仓+拷 `.workbuddy/memory`。

## 账号功能（v3.23 已整体移除，勿复活）
- Config.wtf cVar `SET accountName "账号 密码;"` 方案实测失败：该客户端把记忆值整段塞进账号框不拆密码。用户拍板：exe 不做账号保存/填充，玩家登录界面自行输入+勾客户端「记住帐号名」。
- `/api/account_*` 与 Fernet 模块已删；**保留 `_repair_account_cvar`**（启动游戏时把旧写入的污染值还原为纯账号名）。

## 用户环境与当前状态（2026-11-01）
- ✅ **v3.23 已发布**：蓝奏云 wow-assist 文件夹=manifest(v3.23)+v3.23+v3.22（v3.21 已被用户网页删）；端到端验证清单/直链/md5 ALL PASS（md5 af568dba…, size 17039339）；**已部署游戏根** `D:/game/twmoa_1181/wowassist.exe`。
- v3.23 内容：账号功能移除+cvar 修复、配置日志精简、日志显示两修复+最新在上、启动文案「游戏正在启动……」、删服务器页账号板块、更新日志整合（v3.20–3.22 合并段，顺序修正）。
- 版本号：3.17 跳过；3.18–3.22 均已发；**当前=v3.23**。
- ⏳ 待办：可选迁腾讯云COS；蓝奏云凭据只走 env/登录态缓存。
- LanzouTool/（黑猫助手逆向时期产物）已整体删除（2026-11-01 用户拍板，b9b9035），逆向过程记录已从记忆清除；项目根只剩 wow-assist/。

## 待办与暂缓项（用户拍板记着以后改）
- **exe 图标待换**：当前 capy.ico（bat 与 ui.html 均引用，换名须同步）。风格未定（候选：水豚吉祥物/WA 字母标志）。
- **字体包已换思源黑体（2026-10-31 上线）**：9 槽位全=Noto Sans SC Regular（SIL OFL 可商用），含 SKURRI 伤害数字槽；`.wbdata/resources/Fonts/` 已就地替换，勿回退方正/文鼎。
