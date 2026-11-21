---
name: speedai-jiangai
display_name: SpeedAI 降AI率与AIGC检测
display_name_en: SpeedAI AI Rate Reducer & AIGC Detector
description: 论文降 AI 率（降 AIGC 率）、降重、润色和 AIGC 检测（知网 / 维普 / 万方 / 格子达等），支持整篇 Word 文档和 AIGC 检测报告（PDF）。当用户提到降 AI、降 AIGC、AI 率太高、AIGC 检测没过、降重、查重率高、查 AI 率、去 AI 味、润色论文、出检测报告时使用。可调用 SpeedAI 连接器（MCP 工具），或用自带脚本登录 speedai.com 账号后调用 SpeedAI 开放 API，都不可用时按内置清单人工修改。
description_zh: 用 SpeedAI 给论文降 AI 率（降 AIGC）、降重、润色，并检测 AI 率
description_en: Lower AIGC scores, reduce similarity, polish and check the AI rate of Chinese theses with SpeedAI
examples_zh:
  - "把这段话降一下知网 AIGC 率"
  - "检测这段文字的 AI 率，按维普的标准"
  - "把这篇 Word 论文按知网口径降 AIGC"
examples_en:
  - "Lower the CNKI AIGC score of this paragraph"
  - "Check the AI rate of this text using the VIP standard"
  - "Lower the AIGC score of this Word thesis"
version: 1.3.0
author: SpeedAI
---

# SpeedAI 论文降 AIGC

帮用户降低论文的 AIGC 率（AI 生成痕迹）和重复率，用 SpeedAI 的检测器核对前后变化，并保证观点、数据和引用不被改动。

## 选择调用方式（按顺序）

1. **已连接 SpeedAI 连接器 / MCP**（能看到 `humanize_text`、`detect_aigc`、`humanize_document`、`detect_document` 等工具）：直接调用工具。整篇文档用 `humanize_document` → `get_document`（先 `start: false` 估价，用户同意后 `start_document`），检测报告用 `detect_document` → `get_detect_report`。有的应用会给工具名加连接器前缀（如 `mcp_…_detect_aigc`），名字过长时只在工具说明里写原名（`original tool: …`），按原名识别即可。在科搭 Codar 里，本插件自带连接器，直接使用当前登录的 SpeedAI 账号，不需要 API Key；看不到这些工具或提示登录失效时，请用户重新登录科搭的 SpeedAI 账号，不要让用户去创建 API Key。
   在 **WorkBuddy** 里看不到这些工具时，最省事的是请用户添加 SpeedAI 连接器（自带本技能，登录授权即可，不用 Key）。直接对用户说：「点这个链接添加 SpeedAI：https://www.workbuddy.cn/share/asset?shareCode=GUE2mABosfKRhFNfoBOagO&sig=T1IHcGVwpR33Qd4J ，在弹出的页面登录 speedai.com 并点『允许』，好了告诉我。」也可以走下面第 2 种方式。
2. **用本技能自带的脚本**（只用 Python 标准库，输出 JSON；需要能运行命令）。第一次使用、或脚本提示「还没有连接 SpeedAI 账号」时，先帮用户登录（不用复制 Key）：
   1. 运行 `python3 scripts/speedai.py login`。它会打开浏览器里的 speedai.com 授权页并立即返回；把输出里的 `say_to_user` 原样告诉用户（浏览器没打开时里面带链接），例如「我打开了 SpeedAI 的登录页，登录 speedai.com 后点『允许』就好」。
   2. 用户说好了（或你判断用户已操作）后运行 `python3 scripts/speedai.py login --wait`，看到 `"logged_in": true` 就继续原来的任务；返回 `"waiting": true` 表示用户还没点完，把 `login_url` 发给用户再等。
   3. 提示「后台登录进程已结束」时，改用 `python3 scripts/speedai.py login --foreground`（会一直等到用户点完「允许」，最多 10 分钟，请给这条命令足够的超时时间）。
   登录一次长期有效（过期自动续期）；不用向用户解释 OAuth、令牌这些概念。用户更想用 API Key 时：请用户在 https://speedai.com/open/console/keys 创建 Key，并在自己的终端运行 `python3 scripts/speedai.py set-key` 粘贴保存（也支持环境变量 `SPEEDAI_API_KEY`）。
   ```bash
   python3 scripts/speedai.py login                                             # 登录 speedai.com（第一次用时）
   python3 scripts/speedai.py detect   --platform zhiwang < 段落.txt   # 分段 AIGC 检测
   python3 scripts/speedai.py humanize --mode deai --platform zhiwang < 段落.txt   # 降 AIGC
   python3 scripts/speedai.py humanize --mode rewrite --platform weipu < 段落.txt  # 降重
   python3 scripts/speedai.py balance                                           # 剩余积分
   python3 scripts/speedai.py document 论文.docx --platform zhiwang --estimate   # 整篇文档：先估价
   python3 scripts/speedai.py document-start DOC_ID --out 论文-降AIGC.docx       # 确认后开始并下载结果
   python3 scripts/speedai.py document 论文.docx --platform zhiwang --report 知网报告.pdf  # 附官方检测报告，只改标红段落
   python3 scripts/speedai.py report 论文.docx --platform zhiwang --title 论文标题 --author 姓名  # AIGC 检测报告 PDF
   python3 scripts/speedai.py recharge-plans                                     # 充值套餐与价格
   python3 scripts/speedai.py recharge basic --pay wechat                        # 用户确认后创建充值订单，输出 pay_url
   python3 scripts/speedai.py recharge-status ORDER_ID --wait                    # 等待支付到账
   ```
   超过 1,000 字的文本，脚本会按段落自动切块、依次处理后拼回。Word 文档保留格式、参考文献和表格，标题和参考文献等自动跳过不扣费；积分不足会暂停，充值后用 `document-start` 继续。
3. **都不可用**（没有连接器、也不能运行命令）：按下面的「人工修改清单」改写，并告诉用户可以直接在 https://speedai.com 上传 Word 处理整篇论文。

## 怎么选模式和平台

| 用户的诉求 | `mode` |
|---|---|
| AIGC 率 / AI 率高，要降 AI | `deai` |
| 重复率 / 查重率高，要降重 | `rewrite` |
| 两个都高 | `deai_rewrite`（双倍积分） |
| 只想让语句更通顺 | `polish` |

`platform` 填学校要求的检测平台：`zhiwang`（知网，默认）、`weipu`（维普）、`weipu_qikan`（维普期刊）、`wanfang`（万方）、`gezida`（格子达）、`daya`（大雅）、`turnitin`、`gptzero`。用户没说时先问一句，各平台差异见 `references/platforms.md`。检测（`detect_aigc`、检测报告）只有 `zhiwang`、`weipu`、`turnitin` 三个平台，与网页一致。

降重默认是深度降重（`deep` 默认 true，与网页一致，只对 `rewrite`、`deai_rewrite` 生效，价格不变）；用户想少改一些时传 `deep: false` / 脚本加 `--no-deep`。用户手上有学校检测系统出具的报告时（降 AIGC 用 AIGC 检测报告，降重用查重报告），处理整篇文档可以附上报告（`report_*` / `--report`），只改标红段落，更省积分。

## 积分不足与充值

积分不足时接口会返回还差多少积分。先告诉用户还差多少、本次任务预计要多少积分；用户想充值时列出套餐和价格（`list_recharge_plans` / `recharge-plans`），**等用户明确选定套餐和金额后**再创建订单（`create_recharge_order` / `recharge`），把返回的 `pay_url` 发给用户，用户本人用微信或支付宝扫码付款（页面上可以切换支付方式；创建订单不会扣款）。用户说付好了，查询订单（`get_recharge_order` / `recharge-status`）确认 `paid` 后再继续。用户想换支付方式时，告诉用户在支付页上直接切换微信 / 支付宝即可，不要再创建新订单。只在积分不足或用户主动要求时提充值，用户拒绝后不要再提。

## 工作流程

1. 确认平台和模式；确认文本语言（中文 / 英文）。
2. 有 API 时先 `detect`，记下修改前的 AI 率。
3. 处理文本。单次最多 1,000 字：按段落切分后依次处理（脚本会自动切）。用户给的是整篇 Word 文件时，用文档接口（`humanize_document` 或脚本 `document`），先估价并告诉用户预估积分，同意后再开始。
4. 逐项核对：数字、年份、专有名词、公式、引用标注（如 [1]、（张三，2020））必须与原文一致；术语不能被换成口语。发现被改动的地方，手动改回。
5. 再次 `detect`，告诉用户修改前后的 AI 率，以及你手动调整过的地方。
6. 交付最终文本。不要承诺「一定能过」某个检测系统：不同平台、不同时间的结果会变。

## 人工修改清单（无 API 时使用；有 API 时也用来做最后一遍检查）

AIGC 检测通常会注意这些特征，逐条改掉：

- **套话和万能句**：「综上所述」「值得注意的是」「在……的背景下」「具有重要的理论意义和现实意义」「随着……的快速发展」「起到了至关重要的作用」。换成和本文内容直接相关的表述，或删掉。
- **结构过于工整**：「首先……其次……最后……」、每段都是「总—分—总」、连续三个排比。打破对称，合并或拆分句子。
- **句长太均匀**：有意长短句交替，偶尔用短句收束。
- **抽象概括多、具体信息少**：用用户提供的数据、案例、实验细节替换空泛判断。不要编造任何数据、文献或案例。
- **连接词堆砌**：「此外」「同时」「因此」「然而」频繁出现时删去一半，用语义自然衔接。
- **四字格和书面腔堆叠**：「全方位、多层次、宽领域」这类连串四字词，改成具体说法。
- **被动和名词化**：「被广泛应用」「进行了分析」→「广泛使用」「分析了」。

## 原则

- 只改表达，不改观点、结论和数据。
- 不添加用户没有提供的引用、数据或经历。
- 用户的学校或期刊对 AI 使用有规定时，提醒用户遵守；建议在自己写作的基础上修改，而不是整篇交给 AI 生成。
- 处理会扣用户的 SpeedAI 积分（与网页同价）。一次处理超过约 5,000 字前，先告诉用户并用 `balance` / `get_balance` 查余额；整篇文档先估价。
- 检测报告每个账号每天 5 篇免费，之后按字数计费。
