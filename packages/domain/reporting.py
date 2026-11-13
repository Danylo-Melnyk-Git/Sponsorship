"""Human-readable handoff and case exports."""

from .models import CRITERIA, GOALS, STAGE_LABELS, STAGES
from .service import campaign_report, weekly
from packages.scoring.engine import comparison
from .quality import readiness, handoff_markdown


def plain(value):
    return str(value).replace("|", "/").replace("\r", " ").replace("\n", " ")


def money(values, currency):
    return "неизвестно" if values is None else f"{values[0]:,.2f}–{values[1]:,.2f} {currency}"


def markdown(state):
    lines = [f"# {state['title']}", "",
             f"Тип: {'СИНТЕТИЧЕСКОЕ ДЕМО' if state['kind'] == 'synthetic' else 'Рабочий бриф'}.",
             f"Этап: {STAGE_LABELS[STAGES.index(state['stage'])]}. Версия данных: {state['revision']}; брифа: {state['brief_version']}.", "",
             "## Бриф", "", f"- Компания: {state['brief']['company'] or 'не задана'}.",
             f"- Продукт: {state['brief']['product'] or 'не задан'}",
             f"- Цель: {GOALS.get(state['brief']['goal'], 'не задана')}; метрика: {state['brief']['primary_metric'] or 'не выбрана'}.",
             f"- ЦА: {state['brief']['audience'] or 'не задана'}.", f"- GEO: {', '.join(state['brief']['geo']) or 'не задано'}.",
             f"- Бюджет: {state['brief']['budget']}.", "",
             "## Пул и ручной выбор", "", "| Кандидат | Очередь | Выбран | Основание | Риск |", "| --- | --- | --- | --- | --- |"]
    for candidate in state["candidates"]:
        lines.append(f"| {plain(candidate['name'])} | {candidate['queue']} | {'да' if candidate['selected'] else 'нет'} | "
                     f"{plain(candidate.get('selection_reason') or candidate['rationale'])} | {candidate['risk']['status']} |")
    lines += ["", "## Сравнение конкретных пакетов", "",
              "Модель предварительная, эмпирически не валидирована. Балл не является вероятностью успеха или ROI.",
              "", "| Кандидат / пакет | Балл / возможные границы | Покрытие | Полные затраты | Статус |",
              "| --- | --- | --- | --- | --- |"]
    rows = comparison(state)
    for row in rows:
        evaluation = row["evaluation"]
        score = evaluation["score"] if evaluation["score"] is not None else "не рассчитан"
        lines.append(f"| {plain(row['candidate']['name'])} / {plain(row['package']['name'])} | {score}; {evaluation['interval']} | "
                     f"{evaluation['coverage'] * 100:.0f}% | "
                     f"{money(evaluation['economics']['full_cost_range'], evaluation['economics']['currency'])} | "
                     f"{plain(', '.join(evaluation['gates']) or 'готово к ручному рассмотрению')} |")
    for row in rows:
        evaluation = row["evaluation"]
        lines += ["", f"### {plain(row['package']['name'])}", "",
                  f"Активации: {row['package']['deliverables']}", f"Права: {row['package']['rights'] or 'не уточнены'}", ""]
        for key, entry in evaluation["criteria"].items():
            lines.append(f"- {CRITERIA[key]}: {entry['value'] if entry['usable'] else 'неизвестно'}; "
                         f"вес {entry['weight']}; {entry['reason']}; источники {', '.join(entry['source_ids']) or 'нет'}.")
        lines += ["", "Вопросы менеджеру:",
                  "- Подтвердить представителя, доступность и срок действия условий.",
                  "- Запросить цену именно этого пакета, состав расходов, права, территорию, период и ограничения.",
                  "- Получить историю сопоставимых брендированных размещений, GEO/возраст аудитории и способ отчётности.",
                  "- Уточнить обязательные и заменяемые активации, календарь и процесс приёмки.", ""]
    lines += ["## Зафиксированные решения", ""]
    for decision in state["decisions"]:
        lines.append(f"- {decision['at']}: {decision['decision_maker']} — {decision['kind']}; {decision['reason']}.")
    if state["campaign"]:
        summary = weekly(state)
        lines += ["", "## Исполнение", "", f"Просрочено: {len(summary['overdue'])}; "
                  f"на приёмке: {len(summary['awaiting_acceptance'])}; заблокировано: {len(summary['blocked'])}.",
                  "", "| Обязательство | Ответственный | Срок | Статус | Следующий шаг |", "| --- | --- | --- | --- | --- |"]
        for task in state["tasks"]:
            lines.append(f"| {plain(task['title'])} | {plain(task['owner'])} | {task['due']} | "
                         f"{task['status']} | {plain(task['next_action'])} |")
        report = campaign_report(state)
        lines += ["", "## План и факт", "", "Прогноз взят из сохранённой версии на старте кампании.", ""]
        for result in report["metrics"]:
            lines.append(f"- {result['metric']}: план {result['forecast']['base'] if result.get('forecast') else 'не задан'}; "
                         f"факт {result['actual']['value'] if result['actual'] else 'не получен'}; "
                         f"отклонение {result.get('delta') if result.get('delta') is not None else 'не рассчитано'}.")
        lines.append("- ROI: недостаточно данных для причинного финансового расчёта.")
    if state["case"]:
        lines += ["", "## Выводы кейса", "", f"Решение: {state['case']['recommendation']}.", state["case"]["lessons"]]
    lines += ["", "## Источники", ""]
    for source in state["sources"]:
        link = source["url"] or source["reference"]
        lines.append(f"- {source['id']}: {source['title']} — {link}; получен {source['retrieved_on']}; "
                     f"тип {source['kind']}, доступ {source['access']}.")
    lines += ["", "## Расходы исследования", ""]
    known = [s["cost"] for s in state["search_log"] if s.get("cost") is not None]
    lines.append(f"Известные записи расходов: {len(known)}; записей с неизвестной стоимостью: "
                 f"{sum(s.get('cost') is None for s in state['search_log'])}. Валюты и периоды не суммируются автоматически.")
    review = readiness(state)
    if state.get("campaign"):
        lines += ["", "## Реестр прав и обязательств", "", "| Пункт | Единица | Объём | Принято | Зарезервировано | Остаток | Период |", "| --- | --- | --- | --- | --- | --- | --- |"]
        for entry in review["activation"]["register"]:
            lines.append(f"| {plain(entry['title'])} | {plain(entry['unit'])} | {entry['quantity']} | {entry['accepted_quantity']} | {entry['reserved_quantity']} | {entry['unallocated_quantity']} | {entry['start']} — {entry['end']} |")
    measurement = review["measurement"]
    lines += ["", "## План измерения", "", f"Статус: {measurement['status']}. {measurement['boundary']}"]
    if measurement["plan"]:
        for key, value in measurement["plan"].items():
            lines.append(f"- {key}: {plain(value)}")
    lines += ["", "## Запросы для дальнейшей проверки", "", handoff_markdown(review)]
    return "\n".join(lines) + "\n"
