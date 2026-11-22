import json
import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mizan.llm import LLMReply, Usage  # noqa: E402
from mizan.store import MemoryStore  # noqa: E402


class FakeLLM:
    """Scripted stand-in for the OpenAI-compatible client (no network)."""
    model = "fake"
    price_in = 0.3
    price_out = 2.5

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, tools=None, json_mode=False, **kw):
        self.calls.append({"messages": messages, "tools": tools})
        r = self.replies.pop(0)
        if isinstance(r, dict) and "tool_calls" in r:
            raw = {"role": "assistant", "content": "", "tool_calls": [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": t["name"], "arguments": json.dumps(t["arguments"])}}
                for i, t in enumerate(r["tool_calls"])]}
            calls = [{"id": f"c{i}", "name": t["name"], "arguments": t["arguments"]}
                     for i, t in enumerate(r["tool_calls"])]
            return LLMReply(content="", tool_calls=calls, usage=Usage(100, 20, 1, 0.01), raw_message=raw)
        content = r if isinstance(r, str) else json.dumps(r)
        return LLMReply(content=content, usage=Usage(100, 20, 1, 0.01),
                        raw_message={"role": "assistant", "content": content})

    def structured(self, messages, schema, retries=2, max_tokens=2000):
        from mizan.llm import extract_json
        r = self.chat(messages, json_mode=True)
        return schema.model_validate(extract_json(r.content)), r.usage, None


def make_pdf(path: Path, pages: list[str]) -> Path:
    doc = pymupdf.open()
    for text in pages:
        pg = doc.new_page()
        y = 72
        for line in text.splitlines():
            pg.insert_text((72, y), line, fontsize=10)
            y += 14
    doc.save(str(path))
    return path


SAMPLE_PAGES = [
    "Habib Demo Bank Limited\nAnnual Report 2025\nChairman's review\nThe bank had a strong year with growth in deposits.",
    "Habib Demo Bank Limited\nUnconsolidated Statement of Profit or Loss\nFor the year ended December 31, 2025\n"
    "Rupees in '000\n2025 2024\nTotal income 120,500 100,000\nProfit before taxation 60,000 45,000\n"
    "Profit after taxation 30,000 24,000\nBasic earnings per share 2.75 2.20",
    "Habib Demo Bank Limited\nUnconsolidated Statement of Financial Position\nAs at December 31, 2025\n"
    "Rupees in '000\nTotal assets 900,000 800,000\nTotal liabilities 820,000 735,000\nTotal equity 80,000 65,000",
]


@pytest.fixture
def sample_pdf(tmp_path):
    return make_pdf(tmp_path / "demo.pdf", SAMPLE_PAGES)


@pytest.fixture
def store(sample_pdf):
    from mizan.ingest.pipeline import ingest_pdf
    s = MemoryStore()
    ingest_pdf(s, sample_pdf, "HDB_FY2025", "Habib Demo Bank", "HDB", "annual", "FY2025")
    return s
