"""Download the FinanceBench open-source sample (150 questions + the 84 source PDFs, ~160 MB)
from https://github.com/patronus-ai/financebench into eval/data/financebench_pdfs/."""
import json
import subprocess
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data"
REPO = DATA / "_financebench_repo"


def main() -> None:
    qs = [json.loads(l) for l in open(DATA / "financebench_open_source.jsonl")]
    needed = sorted({f"pdfs/{q['doc_name']}.pdf" for q in qs})
    if not REPO.exists():
        subprocess.run(["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
                        "https://github.com/patronus-ai/financebench.git", str(REPO)], check=True)
    subprocess.run(["git", "-C", str(REPO), "sparse-checkout", "set", "--no-cone", *needed], check=True)
    out = DATA / "financebench_pdfs"
    out.mkdir(exist_ok=True)
    for p in needed:
        src = REPO / p
        dst = out / Path(p).name
        if not dst.exists():
            try:
                dst.symlink_to(src.resolve())
            except OSError:
                import shutil
                shutil.copy(src.resolve(), dst)
    print(f"{len(list(out.glob('*.pdf')))} PDFs ready in {out}")


if __name__ == "__main__":
    main()
