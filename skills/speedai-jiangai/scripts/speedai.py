#!/usr/bin/env python3
"""SpeedAI 开放 API 客户端（speedai-jiangai 技能自带，只用 Python 标准库）。

用法:
  python3 speedai.py humanize [FILE] [--mode MODE] [--platform P] [--lang L] [--no-deep] [--out PATH] [--tex]
        MODE: deai（降 AIGC，默认）| rewrite（降重）| deai_rewrite（降重+降 AIGC）| polish（润色）
        每段改写后自动核对数字、公式、引用和 LaTeX 命令，对不上的段落保留原文并列在 kept_original
        （--no-check 关闭）；--out 把结果写到文件（整篇文件建议用）
        LaTeX（.tex 文件或 --tex）：只改写正文段落，导言区、公式、表格、图、标题、注释原样保留
  python3 speedai.py detect   [FILE] [--platform P] [--tex]  # 分段 AIGC 检测，P：zhiwang（默认）| weipu | turnitin
  python3 speedai.py job JOB_ID                         # 查询仍在处理中的任务
  python3 speedai.py balance                            # 账号与剩余积分
  python3 speedai.py document FILE.docx [--mode MODE] [--platform P] [--no-deep] [--report REPORT] [--estimate] [--out PATH]
        整篇 Word 降 AIGC / 降重 / 润色，保留格式；--estimate 只估价不扣费；完成后下载到 --out
        默认深度降重（rewrite / deai_rewrite，同网页），--no-deep 关闭；--report 附官方检测报告只改标红段落
        （仅 deai / rewrite；维普、维普期刊用 .html，其他平台用 .pdf）
  python3 speedai.py document-status DOC_ID [--out PATH]  # 查文档进度，完成时下载
  python3 speedai.py document-start DOC_ID [--out PATH]   # 估价后开始，或充值后继续，并等待完成
  python3 speedai.py report FILE.docx [--platform P] [--title T] [--author A] [--out PATH]
        整篇文档 AIGC 检测报告（PDF，每天 5 篇免费，之后按字数），完成后下载到 --out
  python3 speedai.py recharge-plans                     # 充值套餐与价格
  python3 speedai.py recharge PLAN [--points N] [--pay wechat|alipay] [--wait]
        创建充值订单（PLAN 如 basic，自定义用 custom 加 --points），输出 pay_url 给用户扫码；
        只在用户确认套餐和金额后调用；--wait 等到支付完成或过期
  python3 speedai.py recharge-status ORDER_ID [--wait]  # 查询充值订单

文本从 FILE 或标准输入读取；超过单次上限（1,000 字）时按段落自动切块、依次处理后拼回。

连接账号（推荐 login，不用复制 Key）：
  python3 speedai.py login                              # 打开浏览器登录 speedai.com 并点「允许」；立即返回登录链接
  python3 speedai.py login --wait [SECONDS]             # 等用户点完「允许」（默认最多 120 秒，可重复运行）
  python3 speedai.py login --foreground                 # 同一个进程里等待回调（后台进程会被结束的环境用这个）
  python3 speedai.py logout                             # 退出登录并撤销授权
  python3 speedai.py set-key                            # 备选：保存 API Key（从标准输入读取，不回显；保存前先验证）

凭证依次从环境变量 SPEEDAI_API_KEY、~/.speedai/credentials.json（login / set-key 写入，仅本人可读）读取；
登录令牌过期会自动刷新。SPEEDAI_API_BASE 可覆盖接口地址。
结果以 JSON 输出到标准输出；出错时写到标准错误并以非 0 退出。
"""
import base64
import http.client
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("SPEEDAI_API_BASE", "https://api.speedai.com").rstrip("/")
UA = "speedai-jiangai-skill/1.4"
MAX_CHARS = int(os.environ.get("SPEEDAI_MAX_CHARS", "1000"))
PLATFORMS = {"zhiwang", "weipu", "weipu_qikan", "wanfang", "gezida", "daya", "turnitin", "gptzero"}
MODES = {"deai", "rewrite", "deai_rewrite", "polish"}
DETECT_PLATFORMS = {"zhiwang", "weipu", "turnitin"}
MAX_REPORT_BYTES = 10 * 1024 * 1024


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


SPEEDAI_DIR = os.path.join(os.path.expanduser("~"), ".speedai")
CRED_PATH = os.path.join(SPEEDAI_DIR, "credentials.json")
LOGIN_STATE_PATH = os.path.join(SPEEDAI_DIR, "login.json")
# 官方客户端元数据文档（OAuth CIMD），托管在 speedai.com；不可用时退回动态注册（client_id 缓存在凭证文件里）
OAUTH_CLIENT_ID = os.environ.get("SPEEDAI_OAUTH_CLIENT_ID", "https://speedai.com/skill/oauth-client.json")
OAUTH_CLIENT_NAME = "SpeedAI 降AI率与AIGC检测技能"
LOGIN_HINT = ("还没有连接 SpeedAI 账号。请运行 `python3 speedai.py login`：会打开浏览器，"
              "用户登录 speedai.com 后点「允许」即可（不用复制 Key）；然后运行 `python3 speedai.py login --wait`。")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_private(path, data):
    """原子写入仅本人可读的 JSON 文件"""
    os.makedirs(SPEEDAI_DIR, mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)
    try:
        os.chmod(SPEEDAI_DIR, 0o700)
        os.chmod(path, 0o600)
    except OSError:
        pass


class cred_lock:
    """跨进程锁：刷新令牌会轮换，旧令牌重放会吊销整组授权，所以同一时间只允许一个进程刷新"""

    def __enter__(self):
        os.makedirs(SPEEDAI_DIR, mode=0o700, exist_ok=True)
        self.f = open(CRED_PATH + ".lock", "a+")
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:  # Windows
            import msvcrt
            self.f.seek(0)
            while True:
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.2)
        return self

    def __exit__(self, *exc):
        try:
            try:
                import fcntl
                fcntl.flock(self.f, fcntl.LOCK_UN)
            except ImportError:
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self.f.close()


def http_json(url, data=None, form=False, timeout=30):
    """OAuth 端点用的小请求：返回 (状态码, JSON)；网络错误返回 (0, {})"""
    headers = {"User-Agent": UA, "Accept": "application/json"}
    body = None
    if data is not None:
        if form:
            from urllib.parse import urlencode
            body = urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        return 0, {}


def refresh_oauth(stale_access=None):
    """刷新登录令牌；别的进程已经刷新过就直接用新的。失败返回 None。"""
    with cred_lock():
        cred = read_json(CRED_PATH)
        oauth = cred.get("oauth") or {}
        if not oauth.get("refresh_token"):
            return None
        if oauth.get("access_token") != stale_access and oauth.get("expires_at", 0) > time.time() + 60:
            return oauth["access_token"]
        status, tok = http_json(BASE + "/oauth/token", {
            "grant_type": "refresh_token", "refresh_token": oauth["refresh_token"],
            "client_id": oauth.get("client_id", ""),
        }, form=True)
        if status != 200 or not tok.get("access_token"):
            if status in (400, 401):  # 刷新令牌失效（授权被断开或已过期）：清掉，提示重新登录
                cred.pop("oauth", None)
                write_private(CRED_PATH, cred)
            return None
        oauth.update(access_token=tok["access_token"], refresh_token=tok.get("refresh_token") or oauth["refresh_token"],
                     expires_at=int(time.time()) + int(tok.get("expires_in") or 3600))
        cred["oauth"] = oauth
        write_private(CRED_PATH, cred)
        return oauth["access_token"]


def load_key():
    """返回 (凭证, 类型)：类型 env / api_key / oauth；没有时 ("", "")"""
    key = os.environ.get("SPEEDAI_API_KEY", "").strip()
    if key:
        return key, "env"
    cred = read_json(CRED_PATH)
    oauth = cred.get("oauth") or {}
    if oauth.get("access_token"):
        if oauth.get("expires_at", 0) > time.time() + 60:
            return oauth["access_token"], "oauth"
        token = refresh_oauth(oauth["access_token"])
        if token:
            return token, "oauth"
    key = str(cred.get("api_key") or "").strip()
    return (key, "api_key") if key else ("", "")


def call(method, path, body=None, key=None):
    kind = "given"
    if not key:
        key, kind = load_key()
    if not key:
        fail(LOGIN_HINT, 2)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    retried = False
    for attempt in range(4):
        req = urllib.request.Request(BASE + "/open/v1" + path, data=data, method=method)
        req.add_header("Authorization", "Bearer " + key)
        req.add_header("User-Agent", UA)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}")
            except ValueError:
                detail = {}
            if e.code == 401 and kind == "oauth" and not retried:
                retried = True
                key = refresh_oauth(key)
                if key:
                    continue
                fail("SpeedAI 登录已失效。" + LOGIN_HINT, 2)
            if e.code == 429 and attempt < 3:
                time.sleep(int(e.headers.get("Retry-After") or 10))
                continue
            fail(json.dumps({"status": e.code, "error": detail.get("error", detail)}, ensure_ascii=False))
        except urllib.error.URLError as e:
            fail(f"无法连接 {BASE}：{e.reason}。如果在沙箱里运行，请允许访问该地址。")
        except (ConnectionError, http.client.HTTPException) as e:
            if attempt < 3:
                time.sleep(2)
                continue
            fail(f"连接 {BASE} 时被中断：{e}。请稍后重试。")
    fail("请求过于频繁，请稍后再试。")


def split_text(text, limit=MAX_CHARS):
    """按段落切块，每块不超过 limit 字；过长的段落再按句子切。返回 [(块, 块后的分隔符)]。"""
    pieces = []
    for para in re.split(r"(\n+)", text):
        if not para:
            continue
        if para.startswith("\n"):
            pieces.append(para)
            continue
        while len(para) > limit:
            window = para[:limit]
            cut = max(window.rfind(c) for c in "。！？；.!?;")
            cut = cut + 1 if cut >= limit // 3 else limit
            pieces.append(para[:cut])
            para = para[cut:]
        if para:
            pieces.append(para)
    chunks, cur = [], ""
    for p in pieces:
        if len(cur) + len(p) > limit and cur.strip():
            chunks.append(cur)
            cur = ""
        cur += p
    if cur.strip():
        chunks.append(cur)
    return chunks


def wait_job(status, job):
    deadline = time.time() + 900
    while status == 202 or job.get("status") in ("pending", "running"):
        if time.time() > deadline:
            fail(json.dumps({"error": "timeout", "job_id": job.get("job_id")}, ensure_ascii=False))
        time.sleep(4)
        status, job = call("GET", f"/jobs/{job['job_id']}")
    if job.get("status") == "error":
        fail(json.dumps({"job_id": job.get("job_id"), "error": job.get("error")}, ensure_ascii=False))
    return job


def take_opt(rest, name, default=None, flag=False):
    if name not in rest:
        return default, rest
    i = rest.index(name)
    if flag:
        return True, rest[:i] + rest[i + 1:]
    if i + 1 >= len(rest):
        fail(f"{name} 需要一个值")
    return rest[i + 1], rest[:i] + rest[i + 2:]


def read_text(rest):
    if rest:
        with open(rest[0], encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


# ---------------------------------------------------------------- LaTeX：只把正文段落交给接口
# 这些环境里是正文，照常处理；其他环境（公式、表格、图、代码、参考文献……）原样保留
TEX_PROSE_ENVS = {"document", "abstract", "itemize", "enumerate", "description", "quote", "quotation",
                  "CJK", "CJK*", "spacing", "flushleft", "flushright", "minipage"}
# 以这些命令开头的行原样保留（标题、标签、图表、排版命令不改写）
TEX_KEEP_CMDS = {"section", "subsection", "subsubsection", "chapter", "part", "paragraph", "subparagraph",
                 "caption", "label", "title", "author", "date", "maketitle", "tableofcontents", "listoffigures",
                 "listoftables", "bibliography", "bibliographystyle", "printbibliography", "appendix",
                 "newpage", "clearpage", "cleardoublepage", "pagebreak", "vspace", "hspace", "vskip", "hskip",
                 "centering", "includegraphics", "input", "include", "keywords", "newcommand",
                 "renewcommand", "setlength", "addcontentsline", "pagestyle", "thispagestyle", "bigskip",
                 "medskip", "smallskip", "noindent", "par", "linebreak", "footnotesize", "small", "large",
                 "Large", "normalsize", "begin", "end", "item"}
_TEX_BEGIN = re.compile(r"\\begin\{([^}]+)\}")
_TEX_END = re.compile(r"\\end\{([^}]+)\}")
_TEX_LEAD_CMD = re.compile(r"^\s*\\([A-Za-z]+)\*?")


def looks_like_tex(text, path=None):
    if path and path.lower().endswith((".tex", ".ltx")):
        return True
    return bool(re.search(r"\\(documentclass|begin\{document\}|section\*?\{|cite[pt]?\{)", text))


def tex_segments(text):
    """把 LaTeX 源码切成 [(is_prose, 文本)]，拼起来与原文逐字相同。正文以外的内容一律 is_prose=False。"""
    lines = text.splitlines(keepends=True)
    segs = []

    def add(prose, line):
        if segs and segs[-1][0] == prose:
            segs[-1][1] += line
        else:
            segs.append([prose, line])

    has_doc = "\\begin{document}" in text
    in_body = not has_doc
    keep_env, keep_depth, display = None, 0, False
    for line in lines:
        bare = line.strip()
        if not in_body:
            add(False, line)
            if "\\begin{document}" in line:
                in_body = True
            continue
        if "\\end{document}" in line:
            add(False, line)
            in_body = False
            continue
        if keep_env:
            add(False, line)
            keep_depth += len([m for m in _TEX_BEGIN.findall(line) if m == keep_env])
            keep_depth -= len([m for m in _TEX_END.findall(line) if m == keep_env])
            if keep_depth <= 0:
                keep_env = None
            continue
        if display:
            add(False, line)
            if "\\]" in line or "$$" in line:
                display = False
            continue
        m = _TEX_BEGIN.search(line)
        if m and m.group(1) not in TEX_PROSE_ENVS:
            add(False, line)
            name = m.group(1)
            keep_depth = len([x for x in _TEX_BEGIN.findall(line) if x == name]) - \
                len([x for x in _TEX_END.findall(line) if x == name])
            keep_env = name if keep_depth > 0 else None
            continue
        if bare.startswith("\\[") or bare == "$$" or (bare.startswith("$$") and bare.count("$$") == 1):
            add(False, line)
            display = not (bare.startswith("\\[") and "\\]" in bare)
            continue
        if not bare:
            add(bool(segs) and segs[-1][0], line)  # 正文之间的空行留在正文里，相邻段落合并成一次请求
            continue
        if bare.startswith("%"):
            add(False, line)
            continue
        lead = _TEX_LEAD_CMD.match(line)
        if lead and lead.group(1) in TEX_KEEP_CMDS:
            # \item 后面跟正文时照常改写正文，只保留 \item 本身
            rest_text = re.sub(r"^\s*\\item(\[[^\]]*\])?\s*", "", line) if lead.group(1) == "item" else ""
            if rest_text.strip():
                add(False, line[: len(line) - len(rest_text)])
                add(True, rest_text)
            else:
                add(False, line)
            continue
        add(True, line)
    return [(prose, t) for prose, t in segs]


# ---------------------------------------------------------------- 改写结果核对
_NUM = re.compile(r"(?<![A-Za-z_])\d+(?:[.,]\d+)*")
_MATH = re.compile(r"\$[^$\n]+\$|\\\(.+?\\\)")
_TEX_REF = re.compile(r"\\(?:cite[a-z]*|[a-z]*ref|label|url|href|eqref|ref)\*?(?:\[[^\]]*\])*\{[^}]*\}")
_TEX_CMD = re.compile(r"\\([A-Za-z]+)")
_TEX_ESC = re.compile(r"\\[%&#_$]")


def _facts(text, tex):
    from collections import Counter
    c = Counter()
    for m in _MATH.findall(text):
        c["公式 " + re.sub(r"\s+", "", m)] += 1
    t = _MATH.sub(" ", text)
    for m in _TEX_REF.findall(t):
        c["引用 " + re.sub(r"\s+", "", m)] += 1
    t = _TEX_REF.sub(" ", t)
    for m in _NUM.findall(t):
        c["数字 " + m.replace(",", "")] += 1
    if tex:
        for m in _TEX_CMD.findall(t):
            c["命令 \\" + m] += 1
        for m in _TEX_ESC.findall(t):
            c["转义 " + m] += 1
        c["花括号"] = t.count("{") - t.count("}")
    return c


def check_rewrite(before, after, tex):
    """改写前后核对数字、公式、引用、LaTeX 命令。返回问题说明（空字符串表示没问题）。"""
    if not after.strip():
        return "接口返回为空"
    a, b = _facts(before, tex), _facts(after, tex)
    lost = sorted((a - b).elements())
    added = sorted((b - a).elements())
    probs = []
    if lost:
        probs.append("丢失 " + "、".join(dict.fromkeys(lost))[:200])
    if added:
        probs.append("多出 " + "、".join(dict.fromkeys(added))[:200])
    n0, n1 = len(before.strip()), len(after.strip())
    if n0 >= 80 and n1 < n0 * 0.5:
        probs.append(f"长度从 {n0} 缩到 {n1}，可能删了内容")
    return "；".join(probs)


def _split_parts(text, blank_only):
    sep = r"\n\s*\n" if blank_only else r"\n"
    return [p for p in re.split(sep, text) if p.strip()]


def guarded(before, after, tex):
    """
    逐段核对：先按行、再按空行把改写前后对齐，段数一致时只把有问题的段落换回原文；
    都对不上时整块核对。返回 (结果文本, [问题])
    """
    for blank_only in (False, True):
        b_parts, a_parts = _split_parts(before, blank_only), _split_parts(after, blank_only)
        if len(b_parts) != len(a_parts) or len(b_parts) < 2:
            continue
        out, pos, issues = before, 0, []
        for bp, ap in zip(b_parts, a_parts):
            i = out.index(bp, pos)
            prob = check_rewrite(bp, ap, tex)
            if prob:
                issues.append({"original": bp.strip()[:120], "reason": prob})
                pos = i + len(bp)
            else:
                ap = bp[: len(bp) - len(bp.lstrip())] + ap.strip() + bp[len(bp.rstrip()):]
                out = out[:i] + ap + out[i + len(bp):]
                pos = i + len(ap)
        return out, issues
    prob = check_rewrite(before, after, tex)
    if prob:
        return before, [{"original": before.strip()[:120], "reason": prob}]
    return after, []


def humanize(rest):
    mode, rest = take_opt(rest, "--mode", "deai")
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    lang, rest = take_opt(rest, "--lang")
    out_path, rest = take_opt(rest, "--out")
    force_tex, rest = take_opt(rest, "--tex", False, flag=True)
    no_check, rest = take_opt(rest, "--no-check", False, flag=True)
    no_deep, rest = take_opt(rest, "--no-deep", False, flag=True)
    _, rest = take_opt(rest, "--deep", False, flag=True)  # 旧参数，默认已开启
    deep = not no_deep
    if mode not in MODES:
        fail(f"--mode 只能是 {', '.join(sorted(MODES))}")
    if platform not in PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(PLATFORMS))}")
    raw = read_text(rest)
    if not raw.strip():
        fail("文本为空")
    tex = force_tex or looks_like_tex(raw, rest[0] if rest else None)
    segments = tex_segments(raw) if tex else [(True, raw.strip())]
    out, jobs, cost, left, kept, sent = [], [], 0, None, [], 0
    for prose, seg in segments:
        if not prose or not seg.strip():
            out.append(seg)
            continue
        for chunk in split_text(seg):
            body_text = chunk.strip("\n")
            if not body_text.strip():
                out.append(chunk)
                continue
            body = {"text": body_text, "mode": mode, "platform": platform, "deep": bool(deep)}
            if lang:
                body["lang"] = lang
            job = wait_job(*call("POST", "/humanize", body))
            result = job.get("text") or ""
            if no_check:
                issues = []
            else:
                result, issues = guarded(body_text, result, tex)
            kept.extend(issues)
            lead = chunk[: len(chunk) - len(chunk.lstrip("\n"))]
            tail = chunk[len(chunk.rstrip("\n")):]
            out.append(lead + result + tail)
            sent += len(body_text)
            jobs.append(job.get("job_id"))
            cost += int(job.get("cost") or 0)
            left = job.get("points_left", left)
    text = "".join(out) if tex else "".join(out).strip()
    res = {"mode": mode, "platform": platform, "format": "latex" if tex else "text", "chars_sent": sent,
           "chunks": len(jobs), "job_ids": jobs, "cost": cost, "points_left": left,
           "checked": not no_check, "kept_original": kept}
    if kept:
        res["note"] = (f"有 {len(kept)} 段改写后数字、公式、引用或 LaTeX 命令对不上，已保留原文（见 kept_original）。"
                       "可以只把这几段手动改写，或单独再处理一次。")
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        res["out"] = os.path.abspath(out_path)
    else:
        res["text"] = text
    print(json.dumps(res, ensure_ascii=False, indent=2))


def detect(rest):
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    force_tex, rest = take_opt(rest, "--tex", False, flag=True)
    if platform not in DETECT_PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(DETECT_PLATFORMS))}")
    raw = read_text(rest)
    if not raw.strip():
        fail("文本为空")
    tex = force_tex or looks_like_tex(raw, rest[0] if rest else None)
    text = "\n\n".join(s.strip() for prose, s in tex_segments(raw) if prose and s.strip()) if tex else raw.strip()
    paragraphs, cost, left, weighted, total = [], 0, None, 0.0, 0
    for chunk in split_text(text):
        body_text = chunk.strip("\n")
        if not body_text.strip():
            continue
        _, res = call("POST", "/detect", {"text": body_text, "platform": platform})
        for p in res.get("paragraphs") or []:
            p = dict(p, index=len(paragraphs))
            paragraphs.append(p)
            n = len(p.get("text") or "")
            weighted += float(p.get("ai_rate") or 0) * n
            total += n
        cost += int(res.get("cost") or 0)
        left = res.get("points_left", left)
    print(json.dumps({"platform": platform, "format": "latex" if tex else "text",
                      "ai_rate": round(weighted / total, 4) if total else 0,
                      "paragraphs": paragraphs, "cost": cost, "points_left": left},
                     ensure_ascii=False, indent=2))


DOC_POLL_SECONDS = float(os.environ.get("SPEEDAI_POLL_SECONDS", "15"))
DOC_TIMEOUT = 3600
MAX_DOCX_BYTES = 10 * 1024 * 1024


def read_docx(path):
    if not path.lower().endswith(".docx"):
        fail("只支持 .docx 文件")
    try:
        size = os.path.getsize(path)
    except OSError:
        fail(f"找不到文件：{path}")
    if size > MAX_DOCX_BYTES:
        fail("文件超过 10 MB")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii"), os.path.basename(path)


def download(url, out):
    """下载 download_url（COS 临时链接，1 小时有效，无需 Key）到 out。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=150) as resp:
            data = resp.read()
    except urllib.error.URLError as e:
        fail(f"下载失败：{getattr(e, 'reason', e)}")
    os.makedirs(os.path.dirname(os.path.abspath(out)) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(data)
    return os.path.abspath(out)


def default_out(name, suffix, ext):
    stem = os.path.splitext(os.path.basename(name or "speedai"))[0]
    return f"{stem}-{suffix}{ext}"


def follow_document(doc, out):
    """轮询文档直到完成 / 暂停 / 出错；完成时下载。"""
    deadline = time.time() + DOC_TIMEOUT
    while doc.get("status") == "processing":
        if time.time() > deadline:
            fail(json.dumps({"error": "timeout", "document": doc}, ensure_ascii=False))
        time.sleep(DOC_POLL_SECONDS)
        _, doc = call("GET", f"/documents/{doc['id']}")
    result = {"document": doc}
    if doc.get("status") == "completed" and doc.get("download_url"):
        result["saved_to"] = download(doc["download_url"], out or default_out(doc.get("file_name"), "speedai", ".docx"))
    elif doc.get("status") == "completed":
        result["hint"] = f"已完成，但暂时拿不到下载链接。稍后运行：speedai.py document-status {doc['id']} --out 文件名.docx"
    elif doc.get("status") == "paused":
        result["hint"] = f"积分不足已暂停。充值后运行：speedai.py document-start {doc['id']}"
    elif doc.get("status") == "error":
        fail(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False, indent=2))


def read_report(path):
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".pdf", ".html", ".htm"):
        fail("--report 只支持 .pdf（知网等）或 .html / .htm（维普、维普期刊）")
    try:
        size = os.path.getsize(path)
    except OSError:
        fail(f"找不到报告文件：{path}")
    if size > MAX_REPORT_BYTES:
        fail("报告文件超过 10 MB")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii"), os.path.basename(path)


def document(rest):
    mode, rest = take_opt(rest, "--mode", "deai")
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    out, rest = take_opt(rest, "--out")
    estimate, rest = take_opt(rest, "--estimate", False, flag=True)
    no_deep, rest = take_opt(rest, "--no-deep", False, flag=True)
    _, rest = take_opt(rest, "--deep", False, flag=True)  # 旧参数，默认已开启
    deep = not no_deep
    report_path, rest = take_opt(rest, "--report")
    if mode not in MODES:
        fail(f"--mode 只能是 {', '.join(sorted(MODES))}")
    if platform not in PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(PLATFORMS))}")
    if not rest:
        fail("用法：speedai.py document FILE.docx")
    b64, name = read_docx(rest[0])
    body = {"file_base64": b64, "file_name": name, "mode": mode, "platform": platform,
            "deep": bool(deep), "start": not estimate}
    if report_path:
        if mode not in ("deai", "rewrite"):
            fail("--report 只支持 --mode deai 或 rewrite")
        body["report_base64"], body["report_name"] = read_report(report_path)
    _, doc = call("POST", "/documents", body)
    if estimate:
        print(json.dumps({"document": doc, "hint": f"确认后运行：speedai.py document-start {doc['id']}"},
                         ensure_ascii=False, indent=2))
        return
    follow_document(doc, out or default_out(name, "speedai", ".docx"))


def document_status(rest, start=False):
    out, rest = take_opt(rest, "--out")
    if not rest:
        fail("需要 DOC_ID")
    if start:
        _, doc = call("POST", f"/documents/{rest[0]}/start", {})
        follow_document(doc, out)
        return
    _, doc = call("GET", f"/documents/{rest[0]}")
    result = {"document": doc}
    if doc.get("status") == "completed" and doc.get("download_url") and out:
        result["saved_to"] = download(doc["download_url"], out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def report(rest):
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    title, rest = take_opt(rest, "--title")
    author, rest = take_opt(rest, "--author")
    out, rest = take_opt(rest, "--out")
    if platform not in DETECT_PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(DETECT_PLATFORMS))}")
    for label, value in (("--title", title), ("--author", author)):
        if value and len(value.strip()) > 20:
            fail(f"{label} 不能超过 20 字")
    if not rest:
        fail("用法：speedai.py report FILE.docx")
    b64, name = read_docx(rest[0])
    body = {"file_base64": b64, "file_name": name, "platform": platform}
    if title:
        body["title"] = title.strip()
    if author:
        body["author"] = author.strip()
    _, rep = call("POST", "/detect/report", body)
    deadline = time.time() + DOC_TIMEOUT
    while rep.get("status") == "processing":
        if time.time() > deadline:
            fail(json.dumps({"error": "timeout", "report": rep}, ensure_ascii=False))
        time.sleep(DOC_POLL_SECONDS)
        _, rep = call("GET", f"/detect/report/{rep['id']}")
    if rep.get("status") != "completed":
        fail(json.dumps({"report": rep}, ensure_ascii=False))
    result = {"report": rep}
    if rep.get("download_url"):
        result["saved_to"] = download(rep["download_url"], out or default_out(name, "检测结果", ".pdf"))
    print(json.dumps(result, ensure_ascii=False, indent=2))


PAY_TYPES = {"wechat", "alipay"}


def wait_order(order):
    """轮询充值订单直到不再是 pending（最多约 15 分钟）。"""
    for _ in range(300):
        if order.get("status") != "pending":
            return order
        time.sleep(3)
        order = call("GET", f"/recharge/orders/{order['id']}")[1]
    return order


def print_order(order):
    # 二维码内容很长且 AI 无法展示，只给用户 pay_url；pay_url 页面自带二维码
    view = {k: v for k, v in order.items() if k != "qr_code"}
    print(json.dumps(view, ensure_ascii=False, indent=2))
    if order.get("status") == "pending" and order.get("pay_url"):
        print(f"请把这个链接发给用户，用{'支付宝' if order.get('payment_type') == 'alipay' else '微信'}扫码支付："
              f"{order['pay_url']}（{order.get('expires_at') or '几分钟'}前有效）", file=sys.stderr)


def recharge(rest):
    if not rest or rest[0].startswith("--"):
        fail("用法：speedai.py recharge PLAN [--points N] [--pay wechat|alipay] [--wait]，套餐用 recharge-plans 查看")
    plan = rest[0]
    rest = rest[1:]
    points, rest = take_opt(rest, "--points")
    pay, rest = take_opt(rest, "--pay", "wechat")
    wait, rest = take_opt(rest, "--wait", flag=True)
    if rest:
        fail(f"无法识别的参数：{' '.join(rest)}")
    if pay not in PAY_TYPES:
        fail("--pay 只能是 wechat 或 alipay")
    body = {"plan": plan, "payment_type": pay}
    if points is not None:
        if not str(points).isdigit():
            fail("--points 必须是正整数")
        body["points"] = int(points)
    order = call("POST", "/recharge/orders", body)[1]
    print_order(order)
    if wait:
        print_order(wait_order(order))


def recharge_status(rest):
    if not rest or rest[0].startswith("--"):
        fail("用法：speedai.py recharge-status ORDER_ID [--wait]")
    order_id = rest[0]
    wait, _ = take_opt(rest[1:], "--wait", flag=True)
    order = call("GET", f"/recharge/orders/{order_id}")[1]
    print_order(wait_order(order) if wait else order)


def set_key(rest):
    """备选：保存 API Key。先用它查一次账号确认有效，再写入仅本人可读的凭证文件（会替换掉登录状态）。"""
    if rest:
        fail("用法：speedai.py set-key（Key 从标准输入读取，不要写在命令行参数里）")
    if sys.stdin.isatty():
        import getpass
        key = getpass.getpass("粘贴 SpeedAI API Key（sa_live_ 开头，输入不显示）：").strip()
    else:
        key = sys.stdin.readline().strip()
    if not re.fullmatch(r"sa_live_[A-Za-z0-9_-]{16,128}", key):
        fail("Key 格式不对：应以 sa_live_ 开头。请在 https://speedai.com/open/console/keys 复制完整的 Key。")
    account = call("GET", "/account", key=key)[1]
    with cred_lock():
        write_private(CRED_PATH, {"api_key": key})
    print(json.dumps({"saved": CRED_PATH, "account": account}, ensure_ascii=False, indent=2))


# ---------------------------------------------------------------- 浏览器登录（OAuth 2.1 授权码 + PKCE，本机回调）
LOGIN_TIMEOUT = 600

SUCCESS_PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SpeedAI 已连接</title><body style="font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0;color:#111318">
<div style="text-align:center"><div style="font-size:44px">&#10003;</div><h1 style="font-size:22px">SpeedAI 账号已连接</h1>
<p style="color:#566172">可以关闭这个页面，回到 AI 助手继续。</p></div></body></html>"""
FAIL_PAGE = """<!doctype html><html lang="zh"><meta charset="utf-8"><title>SpeedAI 未连接</title>
<body style="font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:90vh;margin:0">
<div style="text-align:center"><h1 style="font-size:22px">没有完成连接</h1><p style="color:#566172">{msg}</p></div></body></html>"""


def oauth_client(redirect_uri):
    """优先用官方元数据文档 client_id；后端拉不到时退回动态注册（结果缓存）"""
    status, body = http_json(BASE + "/oauth/token", {
        "grant_type": "refresh_token", "refresh_token": "sa_ort_probe", "client_id": OAUTH_CLIENT_ID}, form=True)
    if status and body.get("error") != "invalid_client":
        return OAUTH_CLIENT_ID
    cached = read_json(CRED_PATH).get("registered_client_id")
    if cached:
        return cached
    status, reg = http_json(BASE + "/oauth/register", {
        "client_name": OAUTH_CLIENT_NAME, "client_uri": "https://speedai.com/open",
        "redirect_uris": ["http://127.0.0.1/callback"], "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "scope": "speedai"})
    if status != 201 or not reg.get("client_id"):
        fail(f"无法连接 SpeedAI 登录服务（{BASE}）。请检查网络后重试，或改用 API Key：speedai.py set-key。")
    with cred_lock():
        cred = read_json(CRED_PATH)
        cred["registered_client_id"] = reg["client_id"]
        write_private(CRED_PATH, cred)
    return reg["client_id"]


def save_login_state(**fields):
    state = read_json(LOGIN_STATE_PATH)
    state.update(fields)
    write_private(LOGIN_STATE_PATH, state)


def serve_login(timeout=LOGIN_TIMEOUT):
    """监听本机回调、换取令牌并保存。进度写到 ~/.speedai/login.json。返回 True 表示成功。"""
    import hashlib
    import secrets
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from urllib.parse import parse_qs, urlencode, urlsplit

    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(24)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            ok = q.get("state") == state and q.get("code")
            if ok:
                result["code"] = q["code"]
            elif q.get("state") == state:
                result["error"] = "denied" if q.get("error") == "access_denied" else (q.get("error") or "no_code")
            page = SUCCESS_PAGE if ok else FAIL_PAGE.format(
                msg="你没有点「允许」。需要时回到 AI 助手重新登录即可。" if result.get("error") == "denied"
                else "登录链接已失效，请回到 AI 助手重新登录。")
            data = page.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    server.timeout = 1
    redirect_uri = f"http://127.0.0.1:{server.server_port}/callback"
    client_id = oauth_client(redirect_uri)
    url = BASE + "/oauth/authorize?" + urlencode({
        "response_type": "code", "client_id": client_id, "redirect_uri": redirect_uri, "scope": "speedai",
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    save_login_state(status="waiting", url=url, pid=os.getpid(), started=int(time.time()),
                     expires=int(time.time()) + timeout, error=None)
    deadline = time.time() + timeout
    try:
        while not result and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        save_login_state(status="expired")
        return False
    if result.get("error"):
        save_login_state(status="error", error=result["error"])
        return False
    status, tok = http_json(BASE + "/oauth/token", {
        "grant_type": "authorization_code", "code": result["code"], "redirect_uri": redirect_uri,
        "client_id": client_id, "code_verifier": verifier}, form=True)
    if status != 200 or not tok.get("access_token"):
        save_login_state(status="error", error=tok.get("error_description") or tok.get("error") or f"HTTP {status}")
        return False
    with cred_lock():
        cred = read_json(CRED_PATH)
        cred.pop("api_key", None)
        cred["oauth"] = {"client_id": client_id, "access_token": tok["access_token"],
                         "refresh_token": tok.get("refresh_token"),
                         "expires_at": int(time.time()) + int(tok.get("expires_in") or 3600)}
        write_private(CRED_PATH, cred)
    save_login_state(status="done", error=None)
    return True


def login_state_alive(state):
    pid = state.get("pid")
    if not pid or state.get("status") != "waiting" or state.get("expires", 0) < time.time():
        return False
    if os.name == "nt":
        return True  # Windows 上不便探测进程，按过期时间判断
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError):
        return False


def open_browser(url):
    try:
        import webbrowser
        return bool(webbrowser.open(url))
    except Exception:
        return False


def account_or_none():
    key, _ = load_key()
    if not key:
        return None
    try:
        return call("GET", "/account")[1]
    except SystemExit:
        return None


def login(rest):
    wait, rest = take_opt(rest, "--wait", flag=True)
    foreground, rest = take_opt(rest, "--foreground", False, flag=True)
    serve, rest = take_opt(rest, "--serve", False, flag=True)
    no_browser, rest = take_opt(rest, "--no-browser", False, flag=True)
    if serve:  # 内部：后台监听进程
        serve_login()
        return
    if wait:
        seconds = int(rest[0]) if rest and rest[0].isdigit() else 120
        deadline = time.time() + seconds
        while True:
            state = read_json(LOGIN_STATE_PATH)
            if state.get("status") == "done":
                print(json.dumps({"logged_in": True, "account": account_or_none()}, ensure_ascii=False, indent=2))
                return
            if state.get("status") == "error":
                fail("没有完成登录（" + ("用户没有点「允许」" if state.get("error") == "denied" else str(state.get("error"))) +
                     "）。需要时重新运行 `speedai.py login`。", 3)
            if not login_state_alive(state):
                fail("登录链接已失效或后台登录进程已结束。请重新运行 `speedai.py login`；"
                     "如果反复出现，改用 `speedai.py login --foreground`。", 3)
            if time.time() >= deadline:
                print(json.dumps({"logged_in": False, "waiting": True, "login_url": state.get("url"),
                                  "hint": "用户还没点「允许」。请把 login_url 发给用户，等用户说好了再运行 speedai.py login --wait"},
                                 ensure_ascii=False, indent=2))
                sys.exit(4)
            time.sleep(2)
    if rest:
        fail(f"无法识别的参数：{' '.join(rest)}")
    account = account_or_none()
    if account and read_json(CRED_PATH).get("oauth"):
        print(json.dumps({"logged_in": True, "already": True, "account": account}, ensure_ascii=False, indent=2))
        return
    try:
        os.remove(LOGIN_STATE_PATH)
    except OSError:
        pass
    if foreground:
        import threading
        t = threading.Thread(target=serve_login, daemon=True)
        t.start()
        for _ in range(100):
            if read_json(LOGIN_STATE_PATH).get("url"):
                break
            time.sleep(0.1)
        url = read_json(LOGIN_STATE_PATH).get("url")
        if url:
            opened = (not no_browser) and open_browser(url)
            print(("已打开浏览器。" if opened else "请打开这个链接：") + "登录 speedai.com 后点「允许」：\n" + url,
                  file=sys.stderr, flush=True)
        t.join()
        state = read_json(LOGIN_STATE_PATH)
        if state.get("status") != "done":
            fail("没有完成登录（" + str(state.get("error") or "超时") + "）。需要时重新运行 `speedai.py login`。", 3)
        print(json.dumps({"logged_in": True, "account": account_or_none()}, ensure_ascii=False, indent=2))
        return
    import subprocess
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "login", "--serve"], **kwargs)
    url = None
    for _ in range(150):
        url = read_json(LOGIN_STATE_PATH).get("url")
        if url:
            break
        time.sleep(0.1)
    if not url:
        fail("无法启动登录。请改用 `speedai.py login --foreground`，或用 API Key：speedai.py set-key。")
    opened = (not no_browser) and open_browser(url)
    print(json.dumps({
        "login_url": url, "browser_opened": opened, "expires_in": LOGIN_TIMEOUT,
        "say_to_user": ("我打开了 SpeedAI 的登录页，" if opened else "请打开这个链接，") +
                       "登录 speedai.com 后点「允许」就好，不用复制 Key。" + ("" if opened else url),
        "next": "用户点完「允许」后运行：python3 speedai.py login --wait",
    }, ensure_ascii=False, indent=2))


def logout(rest):
    with cred_lock():
        cred = read_json(CRED_PATH)
        oauth = cred.pop("oauth", None)
        had_key = cred.pop("api_key", None) is not None
        write_private(CRED_PATH, cred)
    if oauth and oauth.get("refresh_token"):
        http_json(BASE + "/oauth/revoke", {"token": oauth["refresh_token"], "client_id": oauth.get("client_id", "")},
                  form=True)
    print(json.dumps({"logged_out": bool(oauth or had_key)}, ensure_ascii=False))


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    if cmd == "balance":
        print(json.dumps(call("GET", "/account")[1], ensure_ascii=False, indent=2))
    elif cmd == "job":
        if not rest:
            fail("用法：speedai.py job JOB_ID")
        print(json.dumps(call("GET", f"/jobs/{rest[0]}")[1], ensure_ascii=False, indent=2))
    elif cmd == "humanize":
        humanize(rest)
    elif cmd == "detect":
        detect(rest)
    elif cmd == "document":
        document(rest)
    elif cmd == "document-status":
        document_status(rest)
    elif cmd == "document-start":
        document_status(rest, start=True)
    elif cmd == "report":
        report(rest)
    elif cmd == "set-key":
        set_key(rest)
    elif cmd == "login":
        login(rest)
    elif cmd == "logout":
        logout(rest)
    elif cmd == "recharge-plans":
        print(json.dumps(call("GET", "/recharge/plans")[1], ensure_ascii=False, indent=2))
    elif cmd == "recharge":
        recharge(rest)
    elif cmd == "recharge-status":
        recharge_status(rest)
    else:
        fail(f"未知命令 {cmd!r}，用 --help 查看用法")


if __name__ == "__main__":
    main(sys.argv[1:])
