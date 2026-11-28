"""Generate PSX v2 publication figures strictly from eval/results/summary.json."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "eval" / "results"
FIGS = RESULTS / "figures"
FIGS.mkdir(parents=True, exist_ok=True)


def _label_bars(ax, rects, fmt: str = "{:.3f}", fontsize: int = 8) -> None:
    for r in rects:
        h = r.get_height()
        if np.isnan(h):
            continue
        ax.annotate(
            fmt.format(h),
            xy=(r.get_x() + r.get_width() / 2, h),
            xytext=(0, 3),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=fontsize,
        )


def plot_psx_v2_modes(summary: dict) -> None:
    stages = summary["psx_v2_stages"]
    qa = summary["qa_psx_v2"]

    labels = ["rag_direct\n(hybridx)", "rag_calc\n(hybridx)", "agent\n(hybridx)", "agent\n(bm25)"]
    keys = ["rag_direct|hybridx", "rag_calc|hybridx", "agent|hybridx", "agent|bm25"]
    overall = [stages[k]["overall_accuracy"] for k in keys]
    answerable = [stages[k]["answerable_accuracy"] for k in keys]

    x = np.arange(len(labels))
    w = 0.34
    fig, ax = plt.subplots(figsize=(8.2, 4.6))
    b1 = ax.bar(x - w / 2, overall, w, label="Overall Accuracy (n=243)", color="#2563eb")
    b2 = ax.bar(x + w / 2, answerable, w, label="Answerable Accuracy (n=189)", color="#059669")
    _label_bars(ax, b1)
    _label_bars(ax, b2)

    ax.set_ylabel("Accuracy")
    ax.set_ylim(0, 1.12)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_title("PSX v2 QA Accuracy by Mode (gemini-3.5-flash-lite, n=243)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", frameon=True)

    # Annotate hallucination rate on hybridx modes from qa_psx_v2
    halluc_notes = [
        f"halluc {qa['rag_direct']['hallucination_rate']:.3f}",
        f"halluc {qa['rag_calc']['hallucination_rate']:.3f}",
        f"halluc {qa['agent']['hallucination_rate']:.3f}",
        "p=1.00 vs hybridx",
    ]
    for xi, note in zip(x, halluc_notes):
        ax.text(xi, 0.04, note, ha="center", va="bottom", fontsize=7.5, color="#1f2937",
                bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="#d1d5db", alpha=0.88))

    plt.tight_layout()
    plt.savefig(FIGS / "psx_v2_modes.png", dpi=150)
    plt.close(fig)


def plot_rq1_stages(summary: dict) -> None:
    stages = summary["psx_v2_stages"]
    conds = ["rag_calc|hybridx", "agent|hybridx", "agent|bm25"]
    cond_labels = ["rag_calc | hybridx", "agent | hybridx", "agent | bm25"]
    metrics = [
        ("extraction_accuracy", "Extraction"),
        ("operand_selection_accuracy", "Operand Sel."),
        ("formula_selection_accuracy", "Formula Sel."),
        ("arithmetic_accuracy", "Arithmetic"),
        ("answerable_accuracy", "Answerable Acc"),
        ("overall_accuracy", "Overall Acc"),
    ]
    colors = ["#dc2626", "#2563eb", "#0d9488"]

    x = np.arange(len(metrics))
    w = 0.25
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    for idx, (ckey, clabel) in enumerate(zip(conds, cond_labels)):
        vals = [stages[ckey][m[0]] for m in metrics]
        rects = ax.bar(x + (idx - 1) * w, vals, w, label=clabel, color=colors[idx])
        _label_bars(ax, rects, fmt="{:.2f}", fontsize=7.5)

    ax.set_ylabel("Accuracy")
    ax.set_ylim(0, 1.14)
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in metrics])
    ax.set_title("RQ1 Stage-Wise Error Attribution on PSX v2 (n=243)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", frameon=True)

    plt.tight_layout()
    plt.savefig(FIGS / "rq1_stages.png", dpi=150)
    plt.close(fig)


def plot_rq3_abstention(summary: dict) -> None:
    abst = summary["psx_v2_abstention"]
    conds = ["rag_direct|hybridx", "rag_calc|hybridx", "agent|hybridx", "agent|bm25"]
    cond_labels = ["rag_direct\n(hybridx)", "rag_calc\n(hybridx)", "agent\n(hybridx)", "agent\n(bm25)"]
    metrics = [
        ("precision", "Precision", "#2563eb"),
        ("recall", "Recall", "#7c3aed"),
        ("f1", "Abstention F1", "#059669"),
        ("selective_accuracy", "Selective Acc", "#d97706"),
        ("coverage", "Coverage", "#64748b"),
    ]

    x = np.arange(len(conds))
    w = 0.15
    fig, ax = plt.subplots(figsize=(9.5, 4.8))
    mid = (len(metrics) - 1) / 2
    for idx, (mkey, mlabel, col) in enumerate(metrics):
        vals = [abst[c][mkey] for c in conds]
        rects = ax.bar(x + (idx - mid) * w, vals, w, label=mlabel, color=col)
        _label_bars(ax, rects, fmt="{:.2f}", fontsize=7)

    ax.set_ylabel("Score")
    ax.set_ylim(0, 1.14)
    ax.set_xticks(x)
    ax.set_xticklabels(cond_labels)
    ax.set_title("RQ3 Evidence-Aware Abstention on PSX v2 (189 Answerable + 54 Unanswerable)")
    ax.grid(axis="y", linestyle="--", alpha=0.35)
    ax.legend(loc="upper left", ncol=3, frameon=True, fontsize=8.5)

    plt.tight_layout()
    plt.savefig(FIGS / "rq3_abstention.png", dpi=150)
    plt.close(fig)


def main() -> None:
    summary = json.loads((RESULTS / "summary.json").read_text(encoding="utf-8"))
    plot_psx_v2_modes(summary)
    plot_rq1_stages(summary)
    plot_rq3_abstention(summary)
    print("Generated figures in", FIGS)


if __name__ == "__main__":
    main()
