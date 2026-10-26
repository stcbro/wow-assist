# -*- coding: utf-8 -*-
"""
lanzou_core.py — 蓝奏云直链解析核心库（纯标准库实现）

学习来源：开源项目 KCNLanzouDirectLink (https://github.com/JDDKCN/KCNLanzouDirectLink, AGPL-3.0)
本项目为其算法的 Python 学习性重实现。

解析流程（普通链接）:
  1. GET 分享页（可能命中阿里云盾 acw_sc__v2 反爬 → 计算绕过）
  2. 页面若为 iframe 型 → 抓取 iframe，提取 wp_sign + ajaxm.php 路径
     页面若为传统型 → 提取 vkjxld + hyggid 拼接
  3. POST ajaxm.php (action=downprocess) → JSON {zt, dom, url}
  4. 拼 dom + /file/ + url 得中间链接，GET 不跟随重定向 → Location 即最终直链

加密链接流程:
  1. GET 分享页 → 提取 data:{sign:...} 与 ajaxm 路径
  2. POST ajaxm.php (action=downprocess, p=密码) → 同上
"""
import base64
import http.cookiejar
import json
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 域名白名单：lanzo 开头 + 任意变体（lanzoue/lanzouw/lanzoui/lanzn 等）
DOMAIN_RE = re.compile(r"https?://(?:www\.)?([^/]+\.)?lanzo[a-z0-9\-]*\.[a-z]{2,}", re.I)

# ---------------- 状态码 ----------------
SUCCESS = "Success"
URL_NOT_PROVIDED = "UrlNotProvided"
HTML_NOT_FOUND = "HtmlContentNotFound"
POSTSIGN_NOT_FOUND = "PostsignNotFound"      # 需要密码 / 密码错误 / 页面无签名
INTERMEDIATE_NOT_FOUND = "IntermediateUrlNotFound"
FINAL_URL_NOT_FOUND = "FinalUrlNotFound"
ERROR = "Error"


# ================= 反爬虫（阿里云盾 acw_sc__v2）=================

class AntiCrawler:
    """阿里云盾 ESA 反爬页面的识别与 acw_sc__v2 Cookie 计算"""

    ARG1_RE = re.compile(r"=\s*['\"]([0-9a-fA-F]{40})['\"]")
    POSLIST_RE = re.compile(r"=\s*\[((?:\s*0x[0-9a-fA-F]+\s*,?){5,})\]")
    HEXNUM_RE = re.compile(r"0x[0-9a-fA-F]+")
    STRLIT_RE = re.compile(r"['\"]([a-zA-Z0-9+/=]{30,})['\"]")
    ALIYUN_DICT = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/="

    @classmethod
    def is_anti_crawler_page(cls, content: str) -> bool:
        """特征：HTML 开头 + var arg1= 出现"""
        return bool(content) and content.lstrip().startswith("<") and "var arg1=" in content

    @classmethod
    def solve(cls, html: str):
        """返回 'acw_sc__v2=xxx' 或 None。三步：arg1 → 位置重排 → 与 mask 逐字节 XOR"""
        m = cls.ARG1_RE.search(html)
        if not m:
            return None
        arg1 = m.group(1)

        pos_list = None
        for pm in cls.POSLIST_RE.finditer(html):
            hexes = cls.HEXNUM_RE.findall(pm.group(1))
            if len(hexes) >= 10:
                pos_list = [int(h, 16) for h in hexes]
                break
        if not pos_list:
            return None

        mask = cls._extract_mask(html, exclude={arg1})
        if not mask:
            return None

        # 1) 位置重排（posList 值从 1 开始计数）
        try:
            rearranged = "".join(
                arg1[p - 1] for p in pos_list if 0 < p <= len(arg1)
            )
        except IndexError:
            return None
        if len(rearranged) != len(pos_list):
            return None

        # 2) 逐字节 XOR（mask 应为十六进制串，异常则放弃）
        out = []
        try:
            for i in range(0, min(len(rearranged), len(mask)) - 1, 2):
                a = int(rearranged[i:i + 2], 16)
                b = int(mask[i:i + 2], 16)
                out.append("%02x" % (a ^ b))
        except ValueError:
            return None
        return "acw_sc__v2=" + "".join(out) if out else None

    @classmethod
    def _extract_mask(cls, html: str, exclude=()):
        """从 JS 里的长字符串字面量盲提取 mask。
        阿里云盾用自有 base64 字典（小写在前大写在后），需大小写翻转为标准字典再解码。
        策略：排除 arg1 与自有字典；优先选"解码后为十六进制串"的候选，否则取最长可解码者。"""
        candidates = []
        for sm in cls.STRLIT_RE.finditer(html):
            v = sm.group(1)
            if v == cls.ALIYUN_DICT or v in exclude:
                continue
            if re.fullmatch(r"[0-9a-fA-F]+", v):
                continue  # 纯十六进制串（如 arg1 变体）不是 b64 mask
            candidates.append(v)
        candidates.sort(key=len, reverse=True)

        hex_like, fallback = None, None
        for v in candidates:
            swapped = "".join(
                c.lower() if c.isupper() else c.upper() if c.islower() else c
                for c in v
            )
            swapped += "=" * (-len(swapped) % 4)
            try:
                decoded = base64.b64decode(swapped).decode("utf-8", "strict")
            except Exception:
                continue
            if re.fullmatch(r"[0-9a-fA-F]+", decoded):
                return decoded          # 最优：解码即十六进制
            if fallback is None or len(v) > len(fallback):
                fallback = decoded
        return fallback


# ================= 广告下崽器页检测 =================

AD_MARKERS = ("使用全能电脑助手下载", "使用工具进行下载", "install.office123456.com", "d_pclink")


def is_ad_page(html: str) -> bool:
    return any(m in html for m in AD_MARKERS)


# ================= HTTP 会话 =================

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LanzouClient:
    """一个客户端实例持有独立 Cookie，支持并发使用多个实例"""

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.ctx = ssl.create_default_context()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener_noredir = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar), _NoRedirect)
        self.log_lines = []

    # ---------- 基础请求 ----------
    def _headers(self, referer=None, ajax=False):
        h = {
            "User-Agent": UA,
            "Accept": ("application/json, text/javascript, */*"
                       if ajax else
                       "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"),
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        if referer:
            h["Referer"] = referer
        if ajax:
            h["X-Requested-With"] = "XMLHttpRequest"
            h["Sec-Fetch-Dest"] = "empty"
            h["Sec-Fetch-Mode"] = "cors"
            h["Sec-Fetch-Site"] = "same-origin"
        else:
            h["Sec-Fetch-Dest"] = "document"
            h["Sec-Fetch-Mode"] = "navigate"
        return h

    def _log(self, msg):
        self.log_lines.append(msg)

    def _request(self, url, data=None, referer=None, ajax=False):
        """发送请求，自动处理反爬与广告页，返回文本或 None"""
        base_url = url
        for attempt in range(4):
            req = urllib.request.Request(url, data=data, headers=self._headers(referer, ajax))
            try:
                resp = self.opener.open(req, timeout=self.timeout)
                content = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                try:
                    content = e.read().decode("utf-8", "replace")
                except Exception:
                    return None
            except Exception as e:
                self._log(f"[请求异常] {e}")
                return None

            # 反爬：算出 cookie，塞进 jar，等 0.5s 重试
            if AntiCrawler.is_anti_crawler_page(content):
                cookie = AntiCrawler.solve(content)
                if not cookie:
                    self._log("[反爬] acw_sc__v2 计算失败")
                    return None
                self._log(f"[反爬] 计算成功 {cookie[:32]}...，重试")
                host = urllib.parse.urlsplit(base_url)
                self._set_cookie(host.netloc, cookie)
                time.sleep(0.5)
                continue

            # 广告下崽器页面：重试
            if is_ad_page(content) and attempt < 3:
                self._log("[过滤] 检测到广告下崽器页面，重试")
                time.sleep(0.5)
                continue

            return content
        return None

    def _set_cookie(self, netloc, cookie_str):
        name, _, val = cookie_str.partition("=")
        domain = "." + ".".join(netloc.split(".")[-2:])
        c = http.cookiejar.Cookie(0, name, val, None, False, domain, True,
                                  domain.startswith("."), "/", False, False, None, False, None, None, {})
        self.jar.set_cookie(c)

    # ---------- 解析入口 ----------
    def get_direct_link(self, url: str, password: str = "", retries: int = 3):
        """返回 (state, direct_link_or_None)。加密链接建议 retries>=3"""
        if not DOMAIN_RE.match(url):
            return URL_NOT_PROVIDED, None
        if password:
            return self._get_direct_link_encrypted(url, password, retries)
        last = (ERROR, None)
        for _ in range(max(1, retries)):
            state, link = self._get_direct_link_normal(url)
            if state in (SUCCESS, POSTSIGN_NOT_FOUND):
                return state, link
            last = (state, link)
        return last

    # ---------- 普通链接 ----------
    def _get_direct_link_normal(self, url):
        html = self._request(url)
        if html is None:
            return HTML_NOT_FOUND, None

        # 需要密码？
        if 'id="passwddiv"' in html or 'id="pwd"' in html:
            return POSTSIGN_NOT_FOUND, None

        content = self._resolve_download_page(html, url)
        if content is None:
            return INTERMEDIATE_NOT_FOUND, None

        # 提取中间链接
        if content.startswith("AJAX|"):
            intermediate = self._ajax_download(content)
        else:
            intermediate = self._traditional_download(content)
        if not intermediate:
            return INTERMEDIATE_NOT_FOUND, None

        return self._resolve_redirect(intermediate)

    def _resolve_download_page(self, html, url):
        """主页面可能直接可用，也可能需要跟 iframe / 传统跳转页"""
        if "vkjxld" in html and "hyggid" in html:
            return html

        # iframe 型（新版页面）
        m = re.search(r'<iframe.*?src="/([^"]+)"', html, re.I)
        if m:
            iframe_url = urllib.parse.urljoin(url, "/" + m.group(1))
            iframe_html = self._request(iframe_url, referer=url)
            if iframe_html:
                if "wp_sign" in iframe_html:
                    return self._build_ajax_marker(iframe_html, iframe_url)
                if "vkjxld" in iframe_html and "hyggid" in iframe_html:
                    return iframe_html
                return iframe_html

        # 传统跳转页 <div class="nh">...
        m = re.search(r'<div class="mh"><a href="([^"]+)"', html)
        if m:
            tp_url = urllib.parse.urljoin(url, m.group(1))
            tp_html = self._request(tp_url, referer=url)
            if tp_html:
                return tp_html
        return html

    @staticmethod
    def _build_ajax_marker(iframe_html, iframe_url):
        sign = re.search(r"wp_sign\s*=\s*['\"]([^'\"]+)['\"]", iframe_html)
        ajax_path_m = re.search(
            r"(?:https?://[^/\s\"']+)?/?(ajax(?:m|file)\.php\?file=\d+)", iframe_html, re.I)
        if not (sign and ajax_path_m):
            return None
        ajaxdata_m = re.search(r"ajaxdata\s*=\s*['\"]([^'\"]+)['\"]", iframe_html)
        ajaxdata = ajaxdata_m.group(1) if ajaxdata_m else "rewn"
        return f"AJAX|{sign.group(1)}|{ajax_path_m.group(1)}|{ajaxdata}|{iframe_url}"

    def _ajax_download(self, marker):
        """POST ajaxm.php 拿中间链接"""
        _, sign, ajax_path, ajaxdata, referer = marker.split("|")
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(referer))
        ajax_url = ajax_path if ajax_path.startswith("http") else base + "/" + ajax_path.lstrip("/")

        # 前端风控 cookie
        netloc = urllib.parse.urlsplit(referer).netloc
        self._set_cookie(netloc, "pc_ad1=1")
        self._set_cookie(netloc, "codelen=1")

        data = urllib.parse.urlencode({
            "action": "downprocess",
            "websignkey": ajaxdata,
            "signs": ajaxdata,
            "sign": sign,
            "websign": "",
            "kd": "1",
            "ves": "1",
        }).encode()
        body = self._request(ajax_url, data=data, referer=referer, ajax=True)
        if not body or not body.lstrip().startswith("{"):
            self._log(f"[AJAX] 响应异常: {str(body)[:120]}")
            return None
        try:
            j = json.loads(body)
        except ValueError:
            return None
        zt = j.get("zt")
        if int(zt if isinstance(zt, int) else zt or 0) == 1 and j.get("dom") and j.get("url"):
            return j["dom"] + "/file/" + j["url"]
        self._log(f"[AJAX] zt != 1: {body[:120]}")
        return None

    @staticmethod
    def _traditional_download(html):
        a = re.search(r"var\s*vkjxld\s*=\s*['\"]([^'\"]+)['\"]", html, re.I | re.S)
        b = re.search(r"var\s*hyggid\s*=\s*['\"]([^'\"]+)['\"]", html, re.I | re.S)
        return (a.group(1) + b.group(1)) if (a and b) else None

    def _resolve_redirect(self, intermediate_url):
        """GET 中间链接，不跟随重定向 → Location 即最终直链"""
        for i in range(3):
            req = urllib.request.Request(intermediate_url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "X-Requested-With": "mark.via",
            })
            try:
                resp = self.opener_noredir.open(req, timeout=self.timeout)
                content = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as e:
                if e.code in (301, 302):
                    loc = e.headers.get("Location")
                    if not loc:
                        return FINAL_URL_NOT_FOUND, None
                    final = urllib.parse.urljoin(intermediate_url, loc)
                    self._log(f"[直链] {final[:100]}")
                    return SUCCESS, final
                # 200：可能又撞上反爬
                try:
                    content = e.read().decode("utf-8", "replace")
                except Exception:
                    return FINAL_URL_NOT_FOUND, None
                if AntiCrawler.is_anti_crawler_page(content):
                    cookie = AntiCrawler.solve(content)
                    if cookie:
                        self._set_cookie(urllib.parse.urlsplit(intermediate_url).netloc, cookie)
                        time.sleep(0.5)
                        continue
                return FINAL_URL_NOT_FOUND, None
            except Exception as e:
                self._log(f"[重定向异常] {e}")
                return FINAL_URL_NOT_FOUND, None
        return FINAL_URL_NOT_FOUND, None

    # ---------- 加密（带密码）链接 ----------
    def _get_direct_link_encrypted(self, url, password, retries):
        for _ in range(max(1, retries)):
            state, link = self._encrypted_once(url, password)
            if state in (SUCCESS, POSTSIGN_NOT_FOUND):
                return state, link
        return ERROR, None

    def _encrypted_once(self, url, password):
        # 1) 页面（跟传统跳转）
        html = self._request(url)
        if html is None:
            return HTML_NOT_FOUND, None
        m = re.search(r'<div class="mh"><a href="([^"]+)"', html)
        if m:
            html = self._request(urllib.parse.urljoin(url, m.group(1)), referer=url) or html

        # 2) 提取 sign（data:{sign:...}，支持变量引用）
        sign = self._extract_sign(html)
        if not sign:
            return POSTSIGN_NOT_FOUND, None

        # 3) ajax 路径
        ajax_m = re.search(r"(?:https?://[^/\s\"']+)?/?(ajax(?:m|file)\.php\?file=\d+)", html, re.I)
        ajax_path = ajax_m.group(1) if ajax_m else "ajaxm.php"
        base = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
        ajax_url = ajax_path if ajax_path.startswith("http") else base + "/" + ajax_path

        # 4) POST 密码
        data = urllib.parse.urlencode({
            "action": "downprocess", "sign": sign, "kd": "1", "p": password,
        }).encode()
        body = self._request(ajax_url, data=data, referer=url, ajax=True)
        if not body or not body.lstrip().startswith("{"):
            return INTERMEDIATE_NOT_FOUND, None
        try:
            j = json.loads(body)
        except ValueError:
            return INTERMEDIATE_NOT_FOUND, None
        zt = int(j.get("zt") or 0)
        if zt != 1:
            inf = str(j.get("inf", ""))
            self._log(f"[加密] 服务器拒绝: {inf}")
            return (POSTSIGN_NOT_FOUND, None) if ("密码" in inf or "访问" in inf or "错误" in inf) \
                else (INTERMEDIATE_NOT_FOUND, None)

        # 5) 中间链接
        dom, u = j.get("dom"), j.get("url", "")
        if u.startswith("?"):
            inter = f"{dom}/file/{u}"
        elif len(u) > 50 and "/" not in u:
            inter = f"{dom}/file/?{u}"
        else:
            inter = f"{dom}/file/{u}"
        return self._resolve_redirect(inter)

    @staticmethod
    def _extract_sign(html):
        code = re.sub(r"/\*[\s\S]*?\*/", "", html)
        code = re.sub(r"(^|[^:])//.*$", r"\1", code, flags=re.M)
        m = re.search(
            r"^[ \t]*data\s*:\s*\{[^\r\n]*['\"]sign['\"]\s*:\s*(?:(['\"])(.*?)\1|([A-Za-z_\(][\w\)]*))",
            code, re.M | re.I)
        if m:
            if m.group(2):
                return m.group(2)
            var_name = m.group(3)
            vm = re.findall(r"var\s+" + re.escape(var_name) + r"\s*=\s*(['\"])(.*?)\1\s*;",
                            code, re.I)
            if vm:
                return vm[-1][1]
        for vm in re.findall(r"['\"]sign['\"]\s*:\s*['\"]([^'\"]+)['\"]", code, re.I)[::-1]:
            if len(vm) > 10:
                return vm
        return None

    # ---------- 文件信息 ----------
    def get_file_info(self, url, password=""):
        """返回 (state, dict)"""
        if not DOMAIN_RE.match(url):
            return URL_NOT_PROVIDED, None
        if password:
            return self._file_info_encrypted(url, password)
        html = self._request(url)
        if not html:
            return HTML_NOT_FOUND, None
        m = re.search(r'<div class="mh"><a href="([^"]+)"', html)
        if m:
            html = self._request(urllib.parse.urljoin(url, m.group(1)), referer=url) or html
        info = {
            "文件名": self._first(html, [r"var\s+filename\s*=\s*'(.*?)';"]),
            "大小": self._first(html, [r"大小：(.*?)<", r"文件大小：(.*?)<"]),
            "上传时间": self._first(html, [r"上传时间：(.*?)<"]),
            "上传者": self._first(html, [r"分享用户：(.*?)<"]),
            "运行平台": self._first(html, [r"运行系统：(.*?)<"]),
            "描述": self._first(html, [r"文件描述：(.*?)<"]).strip(),
        }
        if any(info.values()):
            return SUCCESS, info
        return ERROR, None

    def _file_info_encrypted(self, url, password):
        html = self._request(url)
        if not html:
            return HTML_NOT_FOUND, None
        info = {
            "文件名": "(输入密码后可见)",
            "大小": self._first(html, [r'<div class="n_filesize">大小：(.*?)</div>']),
            "上传者": self._first(html, [r'<div class="passwddiv-user">获取<span>(.*?)</span>的文件</div>']),
        }
        spans = re.findall(r'<span\s+class="n_file_infos">(.*?)</span>', html)
        if len(spans) >= 2:
            info["上传时间"], info["运行平台"] = spans[0].strip(), spans[1].strip()
        return SUCCESS, info

    @staticmethod
    def _first(html, patterns):
        for p in patterns:
            m = re.search(p, html, re.S)
            if m:
                return m.group(1).strip()
        return ""
