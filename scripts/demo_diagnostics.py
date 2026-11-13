"""Create an isolated, explicitly synthetic sensitivity demonstration."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.domain.demo import seed
from packages.domain.service import ResearchService
from packages.domain.store import Store
from packages.scoring.diagnostics import diagnose
from packages.scoring.diagnostic_report import html, markdown


def main():
    parser = argparse.ArgumentParser(description="Создать новый синтетический пример диагностики")
    parser.add_argument("--database", required=True)
    parser.add_argument("--out-directory", required=True)
    args = parser.parse_args()
    database, output = Path(args.database), Path(args.out_directory)
    if database.exists() or output.exists():
        parser.error("База и каталог результата должны быть новыми: существующие материалы не перезаписываются")
    service = ResearchService(Store(database))
    state = seed(service)

    def act(action, payload):
        nonlocal state
        state = service.act(state["id"], state["revision"], action, payload, actor="synthetic_demo")

    candidate = deepcopy(state["candidates"][0])
    candidate.update(id="demo-d", name="Условная команда Г", kind="club", entity_key="synthetic:demo-d", metrics=[])
    act("save_candidate", candidate)
    act("select_candidate", {"candidate_id": "demo-d", "selected": True, "reason": "Только синтетическая проверка"})
    package = deepcopy(state["packages"][0])
    package.update(id="pkg-demo-d", candidate_id="demo-d", name="Пакет с акцентом на аудиторию")
    for key, value in zip(("audience", "delivery", "fit", "rights"), (90, 76, 72, 84)):
        package["criteria"][key]["value"] = value
    act("save_package", package)
    report = diagnose(state, weight_radius_pp=5, score_radius=0)
    output.mkdir(parents=True, exist_ok=False)
    for name, content in (("diagnostika.html", html(report)), ("diagnostika.md", markdown(report)),
                          ("diagnostika.json", json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))):
        (output / name).write_text(content, encoding="utf-8")
    print(json.dumps({"research_id": state["id"], "revision": state["revision"], "database": str(database.resolve()),
                      "report": str((output / "diagnostika.html").resolve())}, ensure_ascii=False))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
