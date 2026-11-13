"""CLI for chat-driven research and local UI. Python 3.12+, standard library."""

import argparse
import json
import os
import threading
import time
from pathlib import Path
import sys
import sqlite3

from apps.api.server import Server, summary
from packages.connectors.legacy import probe_operations, probe_payload, search_plan
from packages.domain.agents import import_result, role_task
from packages.domain.demo import complete, seed
from packages.domain.models import ValidationError
from packages.domain.reporting import markdown
from packages.domain.service import ResearchService
from packages.domain.storage import open_store as Store
from packages.scoring.diagnostics import diagnose, load_read_only
from packages.scoring import diagnostic_report
from packages.domain.quality import readiness, handoff_markdown
from packages.measurement.engine import analyze as measure
from packages.measurement import report as measurement_report
from packages.strategy.engine import draft_state, strategy
from packages.strategy import report as strategy_report

ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / "data" / "private" / "workspace.sqlite3"
DEFAULT_JOBS = ROOT / "data" / "private" / "jobs.sqlite3"


def research_jobs(service, args):
    from packages.runtime.jobs import JobStore
    from packages.runtime.research_jobs import ResearchJobs
    return ResearchJobs(JobStore(args.jobs_database), service, args.search_provider, args.daily_jobs)


def worker_loop(jobs, stop=None, once=False):
    """Process queued jobs one by one; each provider call happens once, without auto-retry."""
    from packages.runtime.research_jobs import process_once
    while not (stop and stop.is_set()):
        try:
            worked = process_once(jobs.store, jobs.service)
        except Exception as exc:  # keep the server alive; details stay local
            print(f"Воркер: ошибка обработки ({type(exc).__name__})", file=sys.stderr, flush=True)
            worked = False
        if once:
            return worked
        if not worked:
            (stop.wait(2) if stop else time.sleep(2))


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def output(value, path=None):
    content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8") as file:
            file.write(content)
        print(str(target.resolve()))
    else:
        print(content)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Sponsorship Activation — исследовательский кабинет")
    parser.add_argument("--database", default=str(DEFAULT_DB), help="Путь SQLite или firestore://PROJECT_ID")
    parser.add_argument("--jobs-database", default=str(DEFAULT_JOBS), help="SQLite очереди фоновых заданий")
    parser.add_argument("--search-provider", choices=("disabled", "exa", "stub"),
                        default=os.environ.get("SPONSOR_SEARCH_PROVIDER", "disabled"),
                        help="Фоновый поиск: exa — платные вызовы (нужен EXA_API_KEY_FILE), stub — только учебные исследования")
    parser.add_argument("--daily-jobs", type=int, default=20, help="Общий лимит заданий за 24 часа")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="Запустить локальный интерфейс")
    serve.add_argument("--port", type=int, default=8176)
    serve.add_argument("--no-worker", action="store_true", help="Не запускать встроенный воркер (использовать отдельный sponsor.py worker)")
    work = sub.add_parser("worker", help="Выполнять очередь фоновых заданий исследования")
    work.add_argument("--once", action="store_true", help="Обработать не более одного задания и выйти")
    create = sub.add_parser("create", help="Создать исследование из нормализованного брифа")
    create.add_argument("--title", required=True)
    create.add_argument("--brief", required=True)
    create.add_argument("--request-file")
    create.add_argument("--synthetic", action="store_true")
    activation = sub.add_parser("activation", help="Открыть исполнение уже подписанного партнёрства из карточки JSON")
    activation.add_argument("--file", required=True)
    sub.add_parser("list")
    measurement = sub.add_parser("measure", help="Сценарная экономика и измерение из JSON без обращения к базе")
    measurement.add_argument("--file", required=True)
    measurement.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    measurement.add_argument("--out")
    partner = sub.add_parser("strategy", help="Профили партнёров, форматы, план поиска и условная цена без записи в базу")
    origin = partner.add_mutually_exclusive_group(required=True)
    origin.add_argument("--id", help="ID сохранённого исследования (только чтение)")
    origin.add_argument("--brief", help="JSON с title, kind, request, brief; база не открывается")
    partner.add_argument("--economics", help="Сценарии по форматам, привязанные к хешу нормализованного брифа")
    partner.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    partner.add_argument("--out")
    diagnostic = sub.add_parser("diagnose", help="Диагностика устойчивости сохранённого исследования без записи в базу")
    diagnostic.add_argument("id")
    diagnostic.add_argument("--weight-radius", type=float, required=True, help="Допущение: отклонение каждого веса в п.п., 0–100")
    diagnostic.add_argument("--score-radius", type=float, default=0, help="Допущение: отклонение пригодных оценок в баллах, 0–100")
    diagnostic.add_argument("--format", choices=("markdown", "json", "html"), default="markdown")
    diagnostic.add_argument("--out")
    handoff = sub.add_parser("handoff", help="Проверить пробелы и подготовить поручения отделам без записи в базу")
    handoff.add_argument("id")
    handoff.add_argument("--format", choices=("markdown", "json"), default="markdown")
    handoff.add_argument("--out")
    for command in ("show", "export", "plan", "history"):
        command_parser = sub.add_parser(command)
        command_parser.add_argument("id")
        if command in ("show", "export", "plan"):
            command_parser.add_argument("--out")
        if command == "show":
            command_parser.add_argument("--full", action="store_true")
        if command == "export":
            command_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    snapshot = sub.add_parser("snapshot")
    snapshot.add_argument("id")
    snapshot.add_argument("revision", type=int)
    snapshot.add_argument("--out")
    act = sub.add_parser("act")
    act.add_argument("id")
    act.add_argument("action")
    act.add_argument("--file", required=True)
    act.add_argument("--revision", required=True, type=int)
    act.add_argument("--actor", default="owner")
    task = sub.add_parser("task", help="Подготовить контекст роли для выполнения в Codex")
    task.add_argument("id")
    task.add_argument("role")
    task.add_argument("--out")
    role = sub.add_parser("apply-role", help="Проверить и импортировать фактический результат роли")
    role.add_argument("--file", required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--complete", action="store_true")
    sub.add_parser("import-probe", help="Импорт прежних публичных досье под условный бренд")
    args = parser.parse_args(argv)
    try:
        if args.command == "strategy":
            state = draft_state(read_json(args.brief)) if args.brief else load_read_only(args.database, args.id)
            report = strategy(state, read_json(args.economics) if args.economics else None)
            rendered = report if args.format == "json" else getattr(strategy_report, args.format)(report)
            output(rendered, args.out)
            return 0
        if args.command == "measure":
            report = measure(read_json(args.file))
            rendered = report if args.format == "json" else getattr(measurement_report, args.format)(report)
            output(rendered, args.out)
            return 0
        if args.command == "handoff":
            report = readiness(load_read_only(args.database, args.id))
            output(report if args.format == "json" else handoff_markdown(report), args.out)
            return 0
        if args.command == "diagnose":
            report = diagnose(load_read_only(args.database, args.id), args.weight_radius, args.score_radius)
            rendered = report if args.format == "json" else getattr(diagnostic_report, args.format)(report)
            output(rendered, args.out)
            return 0
        service = ResearchService(Store(args.database))
        if args.command == "serve":
            jobs = research_jobs(service, args)
            server = Server(("127.0.0.1", args.port), service, jobs)
            stop = threading.Event()
            if args.search_provider != "disabled" and not args.no_worker:
                threading.Thread(target=worker_loop, args=(jobs, stop), daemon=True, name="research-worker").start()
            print(f"Sponsorship Activation: http://127.0.0.1:{server.server_address[1]}", flush=True)
            print("Фоновый поиск: " + jobs.status()["message"], flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                stop.set()
                server.server_close()
        elif args.command == "worker":
            jobs = research_jobs(service, args)
            print("Воркер: " + jobs.status()["message"], file=sys.stderr, flush=True)
            if args.once:
                output({"processed": worker_loop(jobs, once=True)})
            else:
                try:
                    worker_loop(jobs)
                except KeyboardInterrupt:
                    pass
        elif args.command == "create":
            request = Path(args.request_file).read_text(encoding="utf-8-sig") if args.request_file else ""
            output(summary(service.create({"title": args.title, "brief": read_json(args.brief), "request": request,
                                           "kind": "synthetic" if args.synthetic else "owner_brief"})))
        elif args.command == "activation":
            output(summary(service.create_signed(read_json(args.file))))
        elif args.command == "list":
            output([summary(s) for s in service.store.list()])
        elif args.command == "show":
            output(service.view(args.id) if args.full else summary(service.store.get(args.id)), args.out)
        elif args.command == "act":
            output(summary(service.act(args.id, args.revision, args.action, read_json(args.file), args.actor)))
        elif args.command == "plan":
            output(search_plan(service.store.get(args.id)), args.out)
        elif args.command == "task":
            output(role_task(service.store.get(args.id), args.role), args.out)
        elif args.command == "apply-role":
            output(summary(import_result(service, read_json(args.file))))
        elif args.command == "history":
            output(service.store.history(args.id))
        elif args.command == "snapshot":
            output(service.store.snapshot(args.id, args.revision), args.out)
        elif args.command == "export":
            state = service.store.get(args.id)
            output(markdown(state) if args.format == "markdown" else state, args.out)
        elif args.command == "demo":
            state = seed(service)
            if args.complete:
                state = complete(service, state["id"])
            output(summary(state))
        elif args.command == "import-probe":
            state = service.create(probe_payload())
            state = service.act(state["id"], state["revision"], "batch", {"operations": probe_operations()})
            state = service.act(state["id"], state["revision"], "advance", {})
            output(summary(state))
    except (ValidationError, KeyError, ValueError, OSError, sqlite3.Error) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
