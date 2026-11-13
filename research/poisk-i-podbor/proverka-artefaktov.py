"""Проверка JSON, локальных ссылок и воспроизводимости сохранённого прогона."""
import importlib.util
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("poisk", HERE / "instrument-poiska.py")
poisk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(poisk)

files = list(HERE.rglob("*.json"))
for path in files:
    json.loads(path.read_text(encoding="utf-8-sig"))

brief = poisk.read_json(HERE / "primery/brif-chili-demo.json")
corpus = poisk.read_json(HERE / "primery/dose-chili-public.json")
plan = poisk.make_plan(brief, poisk.read_json(HERE / "pakety-geo.json"))
report = poisk.review(brief, corpus, date(2026, 9, 30))
assert plan == poisk.read_json(HERE / "rezultaty/plan-chili-demo-2026-09-30.json")
assert report == poisk.read_json(HERE / "rezultaty/otbor-chili-demo-2026-09-30.json")
assert poisk.markdown(report) == (HERE / "rezultaty/otbor-chili-demo-2026-09-30.md").read_text(encoding="utf-8")

docs = list(HERE.rglob("*.md")) + [
    ROOT / p for p in ("README.md", "PRIORITIES.md", "research/README.md",
                       "agents/README.md", "agents/poisk-i-podbor.md",
                       "docs/decisions/README.md", "docs/architecture/README.md",
                       "docs/architecture/module-map.md",
                       "docs/product/shablon-brifa.md", "tests/README.md")]
links = 0
for path in docs:
    content = path.read_text(encoding="utf-8-sig")
    for target in re.findall(r"\]\(([^)\n]+)\)", content):
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        local = unquote(target.strip("<>").split("#")[0])
        if local:
            assert (path.parent / local).exists(), f"Broken link: {path}: {target}"
            links += 1
assert len(report["rows"]) == 7
assert len(plan["scheduled"]) == 18
assert len(plan["deferred"]) == 18
assert all(r["budget"]["price_range"] is None for r in report["rows"])
print(f"PASS: {len(files)} JSON; {links} local links; saved plan and report reproduce")
