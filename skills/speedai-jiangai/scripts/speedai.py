#!/usr/bin/env python3
"""SpeedAI 开放 API 客户端（speedai-jiangai 技能自带，只用 Python 标准库）。

用法:
  python3 speedai.py humanize [FILE] [--mode MODE] [--platform P] [--lang L] [--no-deep]
        MODE: deai（降 AIGC，默认）| rewrite（降重）| deai_rewrite（降重+降 AIGC）| polish（润色）
  python3 speedai.py detect   [FILE] [--platform P]     # 分段 AIGC 检测，P：zhiwang（默认）| weipu | turnitin
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
  python3 speedai.py set-key                            # 保存 API Key 到本机（~/.speedai/credentials.json，仅本人可读）
        Key 从标准输入读取（终端里会提示粘贴，不回显）；保存前先验证

API Key 依次从环境变量 SPEEDAI_API_KEY、~/.speedai/credentials.json 读取（Key 在 https://speedai.com/open/console/keys 创建）；
SPEEDAI_API_BASE 可覆盖接口地址。
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
UA = "speedai-jiangai-skill/1.2"
MAX_CHARS = int(os.environ.get("SPEEDAI_MAX_CHARS", "1000"))
PLATFORMS = {"zhiwang", "weipu", "weipu_qikan", "wanfang", "gezida", "daya", "turnitin", "gptzero"}
MODES = {"deai", "rewrite", "deai_rewrite", "polish"}
DETECT_PLATFORMS = {"zhiwang", "weipu", "turnitin"}
MAX_REPORT_BYTES = 10 * 1024 * 1024


def fail(msg, code=1):
    print(msg, file=sys.stderr)
    sys.exit(code)


CRED_PATH = os.path.join(os.path.expanduser("~"), ".speedai", "credentials.json")


def load_key():
    key = os.environ.get("SPEEDAI_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(CRED_PATH, encoding="utf-8") as f:
            return str(json.load(f).get("api_key") or "").strip()
    except (OSError, ValueError, AttributeError):
        return ""


def call(method, path, body=None, key=None):
    key = key or load_key()
    if not key:
        fail("还没有连接 SpeedAI 账号。请在 https://speedai.com/open/console/keys 创建 API Key，"
             "然后运行 `python3 speedai.py set-key` 粘贴保存（或设置环境变量 SPEEDAI_API_KEY）。", 2)
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + "/open/v1" + path, data=data, method=method)
    req.add_header("Authorization", "Bearer " + key)
    req.add_header("User-Agent", UA)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=150) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                detail = json.loads(e.read() or b"{}")
            except ValueError:
                detail = {}
            if e.code == 429 and attempt < 2:
                time.sleep(int(e.headers.get("Retry-After") or 10))
                continue
            fail(json.dumps({"status": e.code, "error": detail.get("error", detail)}, ensure_ascii=False))
        except urllib.error.URLError as e:
            fail(f"无法连接 {BASE}：{e.reason}。如果在沙箱里运行，请允许访问该地址。")
        except (ConnectionError, http.client.HTTPException) as e:
            if attempt < 2:
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


def humanize(rest):
    mode, rest = take_opt(rest, "--mode", "deai")
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    lang, rest = take_opt(rest, "--lang")
    no_deep, rest = take_opt(rest, "--no-deep", False, flag=True)
    _, rest = take_opt(rest, "--deep", False, flag=True)  # 旧参数，默认已开启
    deep = not no_deep
    if mode not in MODES:
        fail(f"--mode 只能是 {', '.join(sorted(MODES))}")
    if platform not in PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(PLATFORMS))}")
    text = read_text(rest).strip()
    if not text:
        fail("文本为空")
    out, jobs, cost, left = [], [], 0, None
    for chunk in split_text(text):
        body_text = chunk.strip("\n")
        if not body_text.strip():
            out.append(chunk)
            continue
        body = {"text": body_text, "mode": mode, "platform": platform, "deep": bool(deep)}
        if lang:
            body["lang"] = lang
        job = wait_job(*call("POST", "/humanize", body))
        lead = chunk[: len(chunk) - len(chunk.lstrip("\n"))]
        tail = chunk[len(chunk.rstrip("\n")):]
        out.append(lead + (job.get("text") or "") + tail)
        jobs.append(job.get("job_id"))
        cost += int(job.get("cost") or 0)
        left = job.get("points_left", left)
    print(json.dumps({"mode": mode, "platform": platform, "text": "".join(out).strip(),
                      "chunks": len(jobs), "job_ids": jobs, "cost": cost, "points_left": left},
                     ensure_ascii=False, indent=2))


def detect(rest):
    platform, rest = take_opt(rest, "--platform", "zhiwang")
    if platform not in DETECT_PLATFORMS:
        fail(f"--platform 只能是 {', '.join(sorted(DETECT_PLATFORMS))}")
    text = read_text(rest).strip()
    if not text:
        fail("文本为空")
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
    print(json.dumps({"platform": platform, "ai_rate": round(weighted / total, 4) if total else 0,
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
    """保存 API Key：先用它查一次账号确认有效，再写入仅本人可读的凭证文件。"""
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
    folder = os.path.dirname(CRED_PATH)
    os.makedirs(folder, mode=0o700, exist_ok=True)
    tmp = CRED_PATH + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"api_key": key}, f)
    os.replace(tmp, CRED_PATH)
    try:
        os.chmod(folder, 0o700)
        os.chmod(CRED_PATH, 0o600)
    except OSError:
        pass
    print(json.dumps({"saved": CRED_PATH, "account": account}, ensure_ascii=False, indent=2))


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
