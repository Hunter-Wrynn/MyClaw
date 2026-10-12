#!/usr/bin/env python3
"""Generate a verified weekly paper report with Codex native web search."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = ZoneInfo(os.environ.get("MYCLAW_TIMEZONE", "Asia/Shanghai"))
DEFAULT_MODEL = os.environ.get("MYCLAW_CODEX_MODEL", "gpt-5.6-sol")
DEFAULT_TIMEOUT_SECONDS = 2340
DEFAULT_REPAIR_ATTEMPTS = 2
WORKDIR = os.environ.get("MYCLAW_WORKSPACE", str(Path(__file__).resolve().parents[3]))
CODEX_FALLBACK_PATH = str(Path.home() / ".local" / "bin" / "codex")
FAILURE_ARTIFACT_DIR = os.path.join(
    WORKDIR,
    ".artifacts",
    "weekly-domain-paper-review",
)


class ReportValidationError(RuntimeError):
    """Raised when a generated report does not satisfy the output contract."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("report validation failed: " + "; ".join(errors))


@dataclass(frozen=True)
class Preset:
    topic: str
    keywords: tuple[str, ...]
    overview_dimensions: tuple[str, ...]
    focus: str
    group_connections: str


PRESETS = {
    "monday-routing": Preset(
        topic="Model Reuse / Model Routing / Model Selection",
        keywords=(
            "model reuse",
            "model selection",
            "LLM routing",
            "VLM routing",
            "model zoo",
            "cost-aware inference",
            "mixture of models",
            "router benchmark",
        ),
        overview_dimensions=(
            "model reuse",
            "model selection",
            "LLM/VLM routing",
            "cost-aware inference",
            "mixture of models",
            "router evaluation",
            "组内重点关注",
        ),
        focus=(
            "重点关注具有明确方法贡献的模型选择、模型路由、模型复用、动态推理成本控制、"
            "Mixture of Models、LLM/VLM router 与 router evaluation 工作；优先考虑跨模型、"
            "跨任务、跨领域泛化，以及公开代码、权重、数据或完整实验。"
        ),
        group_connections=(
            "model reuse、model routing、model selection、LLM/VLM、"
            "成本—质量权衡和组内研究方向"
        ),
    ),
    "tuesday-structured-data": Preset(
        topic="Tabular / Time Series / Structured Data Foundation Models",
        keywords=(
            "tabular learning",
            "tabular foundation model",
            "TabPFN",
            "structured data foundation model",
            "time series foundation model",
            "zero-shot forecasting",
            "causal discovery",
            "tabular representation learning",
            "recommendation LLM",
        ),
        overview_dimensions=(
            "Tabular Foundation Models",
            "TabPFN 及扩展",
            "Time Series Foundation Models",
            "Structured Data",
            "Causal Discovery",
            "Recommendation LLM",
            "组内重点关注",
        ),
        focus=(
            "重点关注表格基础模型与 TabPFN 扩展、表格预训练和上下文学习、时序基础模型的"
            "零样本/少样本与跨领域预测、异构 schema 与缺失数据建模，以及 LLM 在表格推理、"
            "因果发现和推荐中的通用方法贡献。传统单数据集分类、回归或预测方法仅在具有明确的"
            "预训练、跨数据集迁移、上下文学习或模型复用贡献时纳入。"
        ),
        group_connections=(
            "tabular/time-series foundation models、structured data、model reuse、"
            "model routing、LLM/MLLM、causal discovery、recommendation 和组内研究方向"
        ),
    ),
    "wednesday-adaptation": Preset(
        topic=(
            "Continual Learning / Test-Time Adaptation / Meta-Learning / "
            "Few-shot & Efficient Adaptation"
        ),
        keywords=(
            "continual learning",
            "test-time adaptation",
            "continual test-time adaptation",
            "domain shift",
            "catastrophic forgetting",
            "meta-learning",
            "few-shot learning",
            "parameter-efficient adaptation",
        ),
        overview_dimensions=(
            "Continual Learning",
            "TTA / CTTA",
            "Domain Shift",
            "Catastrophic Forgetting",
            "Meta-Learning / Few-shot Learning",
            "Parameter-Efficient Adaptation",
            "组内重点关注",
        ),
        focus=(
            "重点关注持续学习、测试时适配与持续测试时适配中的稳定性—可塑性、域偏移与"
            "灾难性遗忘，元学习和少样本泛化，以及参数高效适配。优先选择跨数据集、跨域、"
            "跨任务或跨模型验证的方法；排除仅针对单一数据集做常规微调且缺少通用适配贡献的工作。"
        ),
        group_connections=(
            "continual learning、test-time adaptation、meta/few-shot learning、"
            "efficient adaptation、model reuse/routing、domain shift 和组内研究方向"
        ),
    ),
    "thursday-posttraining": Preset(
        topic=(
            "LLM Post-training / RLVR / Reward-Value Model / Verifier / "
            "Test-time Scaling"
        ),
        keywords=(
            "RLVR",
            "GRO",
            "GRPO",
            "DAPO",
            "PPO",
            "DPO",
            "reward model",
            "process reward model",
            "verifier",
            "value model",
            "test-time scaling",
            "sampling budget",
            "policy optimization",
        ),
        overview_dimensions=(
            "LLM Post-training / RLVR",
            "GRO / GRPO 与 Policy Optimization",
            "Reward / Value Model",
            "Process Reward Model / Verifier",
            "Test-time Scaling / Sampling Budget",
            "泛化与训练效率",
            "组内重点关注",
        ),
        focus=(
            "重点关注 LLM 后训练、可验证奖励强化学习、GRO/GRPO/DAPO/PPO/DPO 类策略优化、"
            "reward/value/process reward model、verifier，以及测试时扩展与采样预算分配。"
            "优先选择训练稳定性、奖励可靠性、跨任务泛化或推理成本方面有明确方法贡献的工作；"
            "排除只有规模扩张或单项应用结果、缺少方法创新的工作。"
        ),
        group_connections=(
            "LLM post-training、RLVR、reward/value model、verifier、test-time scaling、"
            "model reuse/routing、成本—性能权衡和组内研究方向"
        ),
    ),
    "friday-mllm": Preset(
        topic=(
            "Multimodal LLM / Vision-Language Model / "
            "MLLM Evaluation & Adaptation"
        ),
        keywords=(
            "multimodal large language model",
            "MLLM",
            "vision-language model",
            "visual instruction tuning",
            "cross-modal alignment",
            "multimodal benchmark",
            "MLLM evaluation",
            "OCR",
            "DocVQA",
            "segmentation",
            "pixel-level",
        ),
        overview_dimensions=(
            "Multimodal LLM / VLM",
            "Visual Instruction Tuning / Cross-modal Alignment",
            "MLLM Evaluation",
            "OCR / DocVQA",
            "Segmentation / Pixel-level Understanding",
            "适配与推理效率",
            "组内重点关注",
        ),
        focus=(
            "重点关注多模态大模型和视觉语言模型的新架构、视觉指令微调与跨模态对齐、"
            "可靠评测与高效适配，以及 OCR、DocVQA、分割和像素级理解中的通用方法贡献。"
            "纯 benchmark 或数据集只有在同时提出实质性评测方法时才纳入；排除缺少方法创新的"
            "单一视觉应用结果。"
        ),
        group_connections=(
            "MLLM/VLM、multimodal evaluation、OCR/DocVQA、segmentation、"
            "efficient adaptation、model reuse/routing 和组内研究方向"
        ),
    ),
}


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; use YYYY-MM-DD"
        ) from exc


def previous_complete_week(today: dt.date) -> tuple[dt.date, dt.date]:
    current_monday = today - dt.timedelta(days=today.weekday())
    end = current_monday - dt.timedelta(days=1)
    return end - dt.timedelta(days=6), end


def build_prompt(preset: Preset, start: dt.date, end: dt.date) -> str:
    keyword_text = "；".join(preset.keywords)
    dimensions = "、".join(preset.overview_dimensions)
    title = f"# 专题论文周报：{preset.topic}"
    date_line = f"> 统计区间：{start.isoformat()} 至 {end.isoformat()}（含首尾日期）"

    return f"""你是一名严谨的研究论文分析员。请使用 Codex 内置的原生 web_search 完成检索、打开来源并核验信息，最后生成适合组内阅读的中文专题论文周报。

工具边界：
- 只使用 Codex 原生 web_search 进行联网检索和页面阅读。
- 不要调用 shell、Python、curl、wget、浏览器自动化、agent-browser、截图、图片、Canvas、文件写入或外部消息工具。
- 不要向飞书或任何外部会话发送内容；调用方只会读取你的最终 Markdown。
- 搜索结果标题和摘要片段只能用于发现候选，不能作为论文方法与实验结论的唯一依据。

统计范围与专题：
- 统计区间严格为 {start.isoformat()} 至 {end.isoformat()}，包含首尾日期。
- 专题：{preset.topic}
- 重点检索关键词：{keyword_text}
- {preset.focus}

检索与筛选方法：
1. 系统检索 arXiv、OpenReview、ACL Anthology、会议或 workshop 官方页面、官方技术报告和官方项目页面。组合使用主题词、同义词与日期，而不是只做一次宽泛查询。
2. 建立候选集合并按标题、arXiv ID 或 DOI 去重。每一篇最终入选论文都必须打开并核验原始页面；优先链接 arXiv abstract、OpenReview forum、ACL Anthology、会议官网或官方项目页。
3. 核验标题、作者、首次发布时间、最近更新时间、来源、摘要、主要方法，以及代码或项目地址。代码地址只能采用论文原始页、官方项目页或作者官方仓库所明确给出的地址。
4. 只纳入具有明确方法贡献且与专题强相关的论文。排除纯 benchmark、纯数据集、综述、单一应用结果且缺少方法创新的论文；不要为了达到数量而纳入弱相关论文。
5. 优先统计区间内首次发布或有重要更新的论文。范围外论文只有在统计周内有重要更新或对本期有直接影响时才可少量补充，并必须同时标注首次发布时间、最近更新时间与范围说明；不得把旧论文写成新论文。
6. 区分“作者结论”“分析判断”和“不确定信息”。无法在原始来源核验的细节就明确写“未核验”或“未找到官方地址”，绝不猜测。
7. 在检索过程中自行维护候选数和入选数；第六节只能报告实际检查过的去重候选数，不要估算或编造。

最终输出要求：
- 只输出纯文本 Markdown，不要前言、后记、工具日志、搜索过程、引用编号清单、截图、图片、附件或代码围栏。
- 全文尽量简洁，建议不超过 16000 个中文字符。
- 第一行必须完全等于：
{title}
- 第二个非空行必须完全等于：
{date_line}

严格按以下六节输出：

## 一、本期专题概览

写 5–8 个 Markdown 分点。每点以加粗维度标签开头，最多 1–2 句；只总结已核验论文支持的趋势，覆盖 {dimensions}。如果某一细分方向本周没有高质量新作，应如实说明。

## 二、精选论文

质量允许时选择 8–12 篇；不足时如实减少，不得凑数。每篇用三级标题，并包含以下字段：
- **作者**：
- **首次发布时间**：
- **最近更新时间**：
- **来源**：
- **链接**：
- **代码或项目地址**：
- **一句话总结**：
- **核心方法**：
- **任务类型**：
- **模型范式**：
- **数据与实验设置**：
- **与我们组方向的关系**：
- **值得关注的问题**：

对于范围外补充，另加：
- **范围说明**：

## 三、重点论文精读推荐

必须从第二节入选论文中选择恰好 3 篇，使用“### 1. 标题”“### 2. 标题”“### 3. 标题”三个三级标题。每篇写一个紧凑段落，说明阅读价值、关键问题、方法、跨模型/任务/领域泛化证据、相对已有方法的优势与局限，以及对组内相关工作的启发。重点联系：{preset.group_connections}。

## 四、关键词趋势

列出 10–15 个 Markdown 分点。每个关键词用加粗格式开头，并用一句简短中文说明近期受到关注的原因；必须基于本次核验结果，可以结合过去三个月的直接相关趋势。

## 五、组内讨论问题

严格给出 5 个编号问题，使用“1.”至“5.”，重点联系：{preset.group_connections}。

## 六、检索说明

说明统计区间、实际检索的来源类型、实际检查过的去重候选数、最终入选数、是否采用范围外补充，以及覆盖限制或不确定性。不要列出未经核验的候选附录。
"""


def run_codex(
    prompt: str,
    model: str,
    timeout_seconds: int,
    diagnostics: bool,
    *,
    enable_search: bool = True,
) -> tuple[str, collections.Counter[str], str, float]:
    codex = os.environ.get("MYCLAW_CODEX_BIN") or shutil.which("codex")
    if not codex and os.access(CODEX_FALLBACK_PATH, os.X_OK):
        codex = CODEX_FALLBACK_PATH
    if not codex:
        raise RuntimeError("codex CLI was not found in PATH")

    command = [codex]
    if enable_search:
        command.append("--search")
    command.extend([
        "--ask-for-approval",
        "never",
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "--sandbox",
        "read-only",
        "--model",
        model,
        "--cd",
        WORKDIR,
        "--json",
        "--color",
        "never",
        "-",
    ])
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )

    stdout = ""
    stderr = ""
    supplied_input = False
    deadline = started + timeout_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
            raise RuntimeError(
                f"codex timed out after {timeout_seconds} seconds"
            )
        try:
            stdout, stderr = process.communicate(
                input=None if supplied_input else prompt,
                timeout=min(60, remaining),
            )
            break
        except subprocess.TimeoutExpired:
            supplied_input = True
            if diagnostics:
                elapsed = int(time.monotonic() - started)
                print(
                    f"[weekly-paper-review] Codex search still running: {elapsed}s",
                    file=sys.stderr,
                    flush=True,
                )

    duration = time.monotonic() - started
    if process.returncode != 0:
        tail = stderr.strip()[-4000:] or stdout.strip()[-4000:]
        raise RuntimeError(
            f"codex exited with status {process.returncode}: {tail}"
        )

    event_counts: collections.Counter[str] = collections.Counter()
    final_messages: list[str] = []
    invalid_lines = 0
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            invalid_lines += 1
            continue
        event_type = event.get("type")
        if isinstance(event_type, str):
            event_counts[event_type] += 1
        item = event.get("item")
        if (
            event_type == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            final_messages.append(item["text"].strip())

    if invalid_lines:
        event_counts["invalid_json_lines"] = invalid_lines
    if not final_messages or not final_messages[-1]:
        raise RuntimeError("codex completed without a final agent_message")
    return final_messages[-1], event_counts, stderr, duration


def section(report: str, heading: str, next_heading: str | None) -> str:
    start_marker = f"{heading}\n"
    start = report.find(start_marker)
    if start < 0:
        return ""
    start += len(start_marker)
    if next_heading is None:
        return report[start:]
    end = report.find(f"\n{next_heading}", start)
    return report[start:] if end < 0 else report[start:end]


def validate_report(
    report: str,
    preset: Preset,
    start: dt.date,
    end: dt.date,
) -> dict[str, int]:
    errors: list[str] = []
    title = f"# 专题论文周报：{preset.topic}"
    date_line = f"> 统计区间：{start.isoformat()} 至 {end.isoformat()}（含首尾日期）"
    nonempty = [line.strip() for line in report.splitlines() if line.strip()]

    if not nonempty or nonempty[0] != title:
        errors.append("the first non-empty line is not the required title")
    if len(nonempty) < 2 or nonempty[1] != date_line:
        errors.append("the second non-empty line is not the required date range")

    headings = [
        "## 一、本期专题概览",
        "## 二、精选论文",
        "## 三、重点论文精读推荐",
        "## 四、关键词趋势",
        "## 五、组内讨论问题",
        "## 六、检索说明",
    ]
    positions = [report.find(heading) for heading in headings]
    if any(position < 0 for position in positions):
        errors.append("one or more required section headings are missing")
    elif positions != sorted(positions):
        errors.append("required section headings are out of order")

    overview = section(report, headings[0], headings[1])
    selected = section(report, headings[1], headings[2])
    deep_reads = section(report, headings[2], headings[3])
    keywords = section(report, headings[3], headings[4])
    questions = section(report, headings[4], headings[5])

    overview_count = len(
        re.findall(r"(?m)^-\s+\*\*[^*\n]+\*\*[：:]", overview)
    )
    paper_count = len(re.findall(r"(?m)^###\s+\S", selected))
    deep_read_count = len(
        re.findall(r"(?m)^###\s+[123]\.\s+\S", deep_reads)
    )
    keyword_count = len(
        re.findall(r"(?m)^-\s+\*\*[^*\n]+\*\*[：:]", keywords)
    )
    question_numbers = re.findall(r"(?m)^([1-5])\.\s+\S", questions)

    if not 5 <= overview_count <= 8:
        errors.append(f"overview bullet count is {overview_count}, expected 5–8")
    if not 1 <= paper_count <= 12:
        errors.append(f"selected paper count is {paper_count}, expected 1–12")
    if deep_read_count != 3:
        errors.append(f"deep-read count is {deep_read_count}, expected exactly 3")
    if not 10 <= keyword_count <= 15:
        errors.append(f"keyword count is {keyword_count}, expected 10–15")
    if question_numbers != ["1", "2", "3", "4", "5"]:
        errors.append("discussion questions are not exactly numbered 1 through 5")

    if "```" in report:
        errors.append("the report contains a code fence")
    if re.search(r"!\[[^\]]*\]\(", report):
        errors.append("the report contains a Markdown image")
    if "/root/" in report or "file://" in report:
        errors.append("the report contains a local file path")
    report_bytes = len(report.encode("utf-8"))
    if report_bytes < 5000:
        errors.append(f"the report is too short ({report_bytes} bytes)")
    if report_bytes > 60000:
        errors.append(f"the report is too long ({report_bytes} bytes)")

    if errors:
        raise ReportValidationError(errors)
    return {
        "bytes": report_bytes,
        "overview_bullets": overview_count,
        "selected_papers": paper_count,
        "deep_reads": deep_read_count,
        "keywords": keyword_count,
        "questions": len(question_numbers),
    }


def build_repair_prompt(
    report: str,
    validation_errors: tuple[str, ...],
    preset: Preset,
    start: dt.date,
    end: dt.date,
) -> str:
    title = f"# 专题论文周报：{preset.topic}"
    date_line = (
        f"> 统计区间：{start.isoformat()} 至 {end.isoformat()}（含首尾日期）"
    )
    error_text = "\n".join(f"- {error}" for error in validation_errors)
    return f"""你是一名 Markdown 报告格式修复员。下面的论文周报草稿已经完成了联网检索和来源核验，但没有通过格式校验。请只修复结构、标题、编号、分点数量和必要的简洁性，不要联网，不要新增论文、链接、作者、日期、实验数字或其他事实，不要删除草稿中已有的实质性论文信息。

校验错误：
{error_text}

输出契约：
- 只输出完整的纯文本 Markdown，不要解释、前言、代码围栏或修复说明。
- 第一行必须完全等于：{title}
- 第二个非空行必须完全等于：{date_line}
- 必须严格按顺序使用以下六个二级标题：
  1. ## 一、本期专题概览
  2. ## 二、精选论文
  3. ## 三、重点论文精读推荐
  4. ## 四、关键词趋势
  5. ## 五、组内讨论问题
  6. ## 六、检索说明
- 第一节必须有 5–8 个以“- **标签**：”开头的分点。
- 第二节每篇论文使用“### 论文标题”，保留草稿中的全部字段；论文数量必须为 1–12 篇。
- 第三节必须从第二节选择恰好 3 篇，标题严格为“### 1. 标题”至“### 3. 标题”。
- 第四节必须有 10–15 个以“- **关键词**：”开头的分点。
- 第五节必须严格使用“1.”至“5.”列出 5 个问题。
- 不得包含图片、截图、本地路径或附件。
- 如果草稿使用了含义相同但写法不同的章节标题，请将其规范为上述精确标题并把内容放入对应章节。

待修复草稿开始：
---
{report.strip()}
---
待修复草稿结束。现在只返回修复后的完整 Markdown。"""


def persist_failed_report(
    report: str,
    preset_key: str,
    start: dt.date,
    end: dt.date,
    attempt: int,
    validation_errors: tuple[str, ...],
) -> str:
    os.makedirs(FAILURE_ARTIFACT_DIR, mode=0o700, exist_ok=True)
    timestamp = dt.datetime.now(TIMEZONE).strftime("%Y%m%dT%H%M%S%z")
    stem = (
        f"{preset_key}-{start.isoformat()}-{end.isoformat()}-"
        f"{timestamp}-attempt{attempt}"
    )
    report_path = os.path.join(FAILURE_ARTIFACT_DIR, stem + ".md")
    metadata_path = os.path.join(FAILURE_ARTIFACT_DIR, stem + ".json")
    with open(report_path, "w", encoding="utf-8") as handle:
        handle.write(report.rstrip() + "\n")
    with open(metadata_path, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "preset": preset_key,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "attempt": attempt,
                "validation_errors": list(validation_errors),
                "report_path": report_path,
            },
            handle,
            ensure_ascii=False,
            indent=2,
        )
        handle.write("\n")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a weekly paper report using Codex native web search."
    )
    parser.add_argument("--preset", choices=sorted(PRESETS), required=True)
    parser.add_argument("--start", type=parse_date)
    parser.add_argument("--end", type=parse_date)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
    )
    parser.add_argument(
        "--diagnostics",
        action="store_true",
        help="write progress and validation details to stderr",
    )
    parser.add_argument(
        "--repair-attempts",
        type=int,
        default=DEFAULT_REPAIR_ATTEMPTS,
        help="maximum format-only repair attempts after validation failure",
    )
    parser.add_argument(
        "--print-prompt",
        action="store_true",
        help="print the generated prompt without invoking Codex",
    )
    args = parser.parse_args()

    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be supplied together")
    if args.start is None:
        today = dt.datetime.now(TIMEZONE).date()
        start, end = previous_complete_week(today)
    else:
        start, end = args.start, args.end
    if start > end:
        parser.error("--start must be on or before --end")
    if args.timeout_seconds < 60:
        parser.error("--timeout-seconds must be at least 60")
    if not 0 <= args.repair_attempts <= 3:
        parser.error("--repair-attempts must be between 0 and 3")

    preset = PRESETS[args.preset]
    prompt = build_prompt(preset, start, end)
    if args.print_prompt:
        sys.stdout.write(prompt.rstrip() + "\n")
        return 0

    overall_started = time.monotonic()
    deadline = overall_started + args.timeout_seconds
    combined_event_counts: collections.Counter[str] = collections.Counter()
    combined_stderr: list[str] = []
    try:
        report, event_counts, codex_stderr, _ = run_codex(
            prompt,
            args.model,
            args.timeout_seconds,
            args.diagnostics,
        )
        combined_event_counts.update(event_counts)
        combined_stderr.append(codex_stderr)

        stats: dict[str, int] | None = None
        for attempt in range(args.repair_attempts + 1):
            try:
                stats = validate_report(report, preset, start, end)
                break
            except ReportValidationError as exc:
                artifact_path = persist_failed_report(
                    report,
                    args.preset,
                    start,
                    end,
                    attempt + 1,
                    exc.errors,
                )
                if args.diagnostics:
                    print(
                        "[weekly-paper-review] "
                        f"validation attempt {attempt + 1} failed; "
                        f"saved draft to {artifact_path}; errors={exc.errors}",
                        file=sys.stderr,
                        flush=True,
                    )
                if attempt >= args.repair_attempts:
                    raise
                remaining = int(deadline - time.monotonic())
                if remaining < 60:
                    raise RuntimeError(
                        "insufficient time remaining for a format repair"
                    ) from exc
                repair_prompt = build_repair_prompt(
                    report,
                    exc.errors,
                    preset,
                    start,
                    end,
                )
                report, repair_counts, repair_stderr, _ = run_codex(
                    repair_prompt,
                    args.model,
                    remaining,
                    args.diagnostics,
                    enable_search=False,
                )
                combined_event_counts.update(repair_counts)
                combined_stderr.append(repair_stderr)

        if stats is None:
            raise RuntimeError("report validation did not produce statistics")
    except RuntimeError as exc:
        print(f"weekly paper review failed: {exc}", file=sys.stderr)
        return 1

    if args.diagnostics:
        duration = time.monotonic() - overall_started
        completed_items = combined_event_counts.get("item.completed", 0)
        stderr_lines = sum(
            len([line for line in chunk.splitlines() if line.strip()])
            for chunk in combined_stderr
        )
        print(
            "[weekly-paper-review] "
            f"completed in {duration:.1f}s; "
            f"JSON events={sum(combined_event_counts.values())}; "
            f"completed items={completed_items}; "
            f"captured stderr lines={stderr_lines}; "
            f"report stats={json.dumps(stats, ensure_ascii=False)}",
            file=sys.stderr,
        )

    sys.stdout.write(report.rstrip() + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
