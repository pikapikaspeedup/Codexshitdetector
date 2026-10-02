# Codex Shit Detector

Detect whether Codex was silently downgraded, degrading code quality and wasting your time on avoidable fixes.

This detector only scores two slugs: `gpt-6-astra` and `gpt-6.1-sol`. Other models are left out. The picker can still show those names while the first packet of the turn is downgraded. A downgraded opening is the turn that goes on to write the bugs you then spend the day cleaning up.

## What a downgrade looks like

Codex stores each user turn in a local session log. The first model packet is the one that matters:

- `reasoning_output_tokens` is 0: the turn opened clean.
- `reasoning_output_tokens` is greater than 0: the turn opened downgraded.
- If usage was never flushed, a reasoning item stored before the first reply counts as downgraded.

Later packets in the same turn are ignored. Child turns are ignored. Only `gpt-6-astra` and `gpt-6.1-sol` are counted. Pass `--model` to keep just one of them.

A project that had any downgraded turn is listed as a warning. Treat the code written in those turns as likely to contain bugs.

## Run

Python 3. No extra packages. Dates use your machine's local timezone and include both ends. The default window is the last 7 days, for `gpt-6-astra` and `gpt-6.1-sol` only.

```bash
python3 detect.py
python3 detect.py --model gpt-6-astra
python3 detect.py --model gpt-6.1-sol
python3 detect.py --since 2026-09-01 --until 2026-09-07
```

Sessions are read from `~/.codex` (`sessions` and `archived_sessions`). Point `CODEX_HOME` somewhere else if your logs live outside the default directory.

The report is counts: totals, by model, by day, then the project warning. It does not print session ids or message text. Project paths are your local working directories.

---

# Codex 降智检测

检测 Codex 是否在静默降智。降智会把代码质量拉低，让你把时间耗在本来可以避开的修复上。

只检测两个 slug：`gpt-6-astra` 和 `gpt-6.1-sol`。其他模型先不判。选择器上可以仍显示这两个名字，第一包却已经降智。降智的开场，就是随后把 Bug 写进项目、再让你花时间去收拾的那些回合。

## 降智长什么样

Codex 把用户回合记在本机会话日志里。只看第一包：

- `reasoning_output_tokens` 为 0：这一回合开场正常。
- `reasoning_output_tokens` 大于 0：这一回合开场降智。
- 用量没写入时，开口之前已经有推理条目，也算降智。

同一回合后面的包不算。子回合不算。只统计 `gpt-6-astra` 和 `gpt-6.1-sol`。用 `--model` 可以只留其中一个。

任何一个降智回合所在的项目都会进预警。这些回合里写下的代码，按这个口径视为可能已经带上 Bug。

## 运行

只需要 Python 3。日期用本机时区，含首尾两天。默认是最近 7 天，只检测 `gpt-6-astra` 和 `gpt-6.1-sol`。

```bash
python3 detect.py
python3 detect.py --model gpt-6-astra
python3 detect.py --model gpt-6.1-sol
python3 detect.py --since 2026-09-01 --until 2026-09-07
```

默认读取 `~/.codex` 下的 `sessions` 和 `archived_sessions`。日志不在默认目录时，设置 `CODEX_HOME`。

报告只有合计、按模型、按日，以及项目预警。不输出会话 id，不输出消息原文。项目路径是你本机的工作区。
