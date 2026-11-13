"""Portable reports with all assumptions retained and no external dependencies."""
from html import escape
import json
from pathlib import Path

from packages.domain.models import GOALS

LABELS = {"resources_declared": "Ресурсы заявлены; пригодность ещё проверить",
          "conditional": "Нужно подтвердить условия", "blocked_by_resources": "Нет необходимого ресурса"}
CATEGORIES = {"creators": "Авторы / эксперты", "athletes": "Спортсмены", "music": "Музыка / артисты",
              "teams": "Команды / клубы / лиги", "events": "События", "gaming_media": "Игры / медиа"}
LANES = {"direct": "Прямая связь", "audience": "Интересы аудитории", "adjacent": "Косвенная связь"}
PRICE = {"budget_fee_cap": "Потолок гонорара по бюджету", "economic_fee_cap": "Потолок по экономическим допущениям",
         "combined_fee_cap": "Потолок с учётом обоих ограничений",
         "required_outcomes_if_full_budget_spent": "Добавочных результатов при расходовании всего бюджета"}


def amount(values):
    if values is None:
        return "Не рассчитано"
    fmt = lambda x: f"{x:,.2f}".rstrip("0").rstrip(".").replace(",", "\u00a0")
    return fmt(values[0]) if values[0] == values[1] else f"{fmt(values[0])} … {fmt(values[1])}"


def markdown(data):
    lines = ["# Профиль партнёра и формат", "", data["title"], "",
             "Статус: гипотезы потребности. " + ("Синтетический пример." if data["kind"] == "synthetic" else "Не оффер и не одобрение партнёра."),
             "", data["fallback"], "", data["order_meaning"], "",
             "Цель: " + GOALS.get(data["brief"]["goal"], "не задана"),
             ("Не заполнено: " + ", ".join(data["missing_brief_fields"]) if data["missing_brief_fields"] else "Основные поля брифа заполнены."), "",
             "Ограничения: " + data["hard_constraints"]["restrictions"], ""]
    for p in data["profiles"]:
        lines += ["## " + p["name"], "", LABELS[p["feasibility"]], "", p["subject"],
                  "", "Категории поиска: " + ", ".join(CATEGORIES[k] for k in p["categories"]),
                  "ЦА: " + p["audience_requirement"], "GEO: " + ", ".join(p["geography_requirement"]),
                  p["product_role"], p["mechanism"], "Метрика: " + p["metric"], "", p["audience_evidence"], ""]
        lines += ["Темы для проверки:", ""] + ["- " + t["term"] + ": " + t["reason"] for t in p["topic_hypotheses"]] + [""]
        for key, name in (("unavailable_resources", "Не хватает"), ("unknown_resources", "Не подтверждено"),
                          ("package", "Что покупать"), ("rights", "Какие условия проверить"),
                          ("activation", "Что сделать"), ("improve", "Как улучшить пакет")):
            lines += ["### " + name, ""] + ["- " + t for t in p[key]] + (["Нет отмеченных пунктов."] if not p[key] else []) + [""]
        lines += ["### Цена и результат", "", "Рыночная ставка: неизвестна.", ""]
        for key, name in PRICE.items():
            unit = " результатов" if key.startswith("required") else " " + (p["price"]["currency"] or "валюта не задана")
            lines.append(f"- {name}: {amount(p['price'][key])}{unit if p['price'][key] is not None else ''}")
        lines += ["", *p["price"]["notes"], "", "Стоп-условие: " + p["stop"], ""]
    plan, execution = data["search_plan"], data["execution"]
    lines += ["## Поиск и пробелы", "", f"Запланировано ячеек: {len(plan['scheduled'])}; отложено: {len(plan['deferred'])}.",
              f"Завершено текущих ячеек: {execution['completed_current_plan_cells']}. Осталось вызовов: {execution['remaining_calls']}; страниц: {execution['remaining_pages']}.",
              "Поиск этой командой не выполнялся. Запрос — черновик для проверки до отправки.",
              "Не хватает для поиска: " + ("; ".join(plan["missing_for_search"]) or "базовые входы есть"),
              "Нет языкового пакета: " + (", ".join(plan["unsupported_geographies"]) or "—"), ""]
    lines += ["- " + t["arguments"]["query"] for t in execution["next_queries"]]
    lines += ["", f"Неудачных ячеек для отдельного решения о повторе: {len(execution['retry_requires_review'])}.",
              "", "## За пределами показанного списка", ""]
    lines += ["- " + p["name"] + ": " + p["reason"] for p in data["deferred_profiles"] + data["excluded_formats"]]
    lines += ["", data["next_decision"], "", "## Исходные данные и прослеживаемость", "",
              "Ниже сохранены бриф, настройки, план, ограничения и основания каждого числового допущения.", "",
              "```json", json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), "```", ""]
    return "\n".join(lines)


def html(data, style_href=None):
    e = lambda value: escape(str(value), quote=True)
    ul = lambda rows: "<ul>" + "".join("<li>" + e(t) + "</li>" for t in rows) + "</ul>" if rows else "<p class='muted'>Нет отмеченных пунктов.</p>"
    style = ("<link rel='stylesheet' href='" + e(style_href) + "'>" if style_href else
             "<style>" + (Path(__file__).resolve().parents[2] / "apps/web/strategy.css").read_text(encoding="utf-8") + "</style>")
    cards = []
    for index, p in enumerate(data["profiles"], 1):
        price = p["price"]
        price_rows = "".join("<tr><th>" + e(label) + "</th><td>" + e(amount(price[key])) +
                             (" " + e(price["currency"] or "") if price[key] is not None and not key.startswith("required") else "") + "</td></tr>" for key, label in PRICE.items())
        resource = ("<div class='alert'>Не хватает: " + e("; ".join(p["unavailable_resources"])) + "</div>" if p["unavailable_resources"] else "")
        resource += ("<p class='muted'>Нужно подтвердить: " + e("; ".join(p["unknown_resources"])) + "</p>" if p["unknown_resources"] else "")
        cards.append("<article><div class='eyebrow'>Профиль " + str(index) + " · " + e(LABELS[p["feasibility"]]) + "</div><h2>" + e(p["name"]) +
                     "</h2>" + resource + "<p class='lead'>" + e(p["subject"]) + "</p><dl><dt>Кого искать</dt><dd>" + e(", ".join(CATEGORIES[k] for k in p["categories"])) +
                     "</dd><dt>Аудитория</dt><dd>" + e(p["audience_requirement"]) + "</dd><dt>География</dt><dd>" + e(", ".join(p["geography_requirement"])) +
                     "</dd><dt>Проверяемый результат</dt><dd>" + e(p["metric"]) + "</dd></dl><p>" + e(p["product_role"]) + "</p><p>" + e(p["mechanism"]) +
                     "</p><p><strong>Темы для проверки:</strong> " + e("; ".join(t["term"] for t in p["topic_hypotheses"]) or "не заданы") +
                     ". Связь с нужной аудиторией пока является гипотезой.</p><div class='columns'><section><h3>Что должно быть в пакете</h3>" + ul(p["package"]) + "</section><section><h3>Что сделать с партнёром</h3>" + ul(p["activation"]) +
                     "</section></div><h3>За какую цену имеет смысл рассматривать</h3><p>Рыночная ставка неизвестна. Валюта: " + e(price["currency"] or "не задана") +
                     "; период: " + e(str(price["months"]) + " месяцев" if price["months"] else "не задан") +
                     ("; целевой ROI: " + e(f'{price["target_roi"]*100:g}%') if "target_roi" in price else "") +
                     ".</p><table>" + price_rows + "</table>" + ul(price["notes"]) + "<details><summary>Условия, улучшения и причины отказа</summary><h3>Права и подтверждения</h3>" + ul(p["rights"]) +
                     "<p>" + e(p["audience_evidence"]) + "</p><h3>Как сделать пакет полезнее</h3>" + ul(p["improve"]) + "<p><strong>Стоп-условие:</strong> " + e(p["stop"]) + "</p></details></article>")
    plan, ex = data["search_plan"], data["execution"]
    queries = "".join("<li><strong>" + e(t["geo"] + " / " + CATEGORIES[t["category"]] + " / " + LANES[t["lane"]]) + "</strong><p>" + e(t["arguments"]["query"]) + "</p></li>" for t in ex["next_queries"])
    missing = "<p>" + e("Не заполнено в брифе: " + ", ".join(data["missing_brief_fields"]) if data["missing_brief_fields"] else "Основные поля брифа заполнены.") + "</p>"
    missing += "<p><strong>Ограничения:</strong> " + e(data["hard_constraints"]["restrictions"]) + "</p>"
    return ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Профиль партнёра и формат</title>" + style +
            "</head><body><main><header><div class='eyebrow'>Sponsorship Activation · Профили потребности</div><h1>Сначала задача.<br>Потом имя партнёра.</h1><p class='lead'>" + e(data["title"]) +
            "</p><p>Цель: " + e(GOALS.get(data["brief"]["goal"], "не задана")) + " · GEO: " + e(", ".join(data["brief"]["geo"]) or "не задано") +
            "</p></header><div class='notice'><strong>" + ("Синтетический пример. " if data["kind"] == "synthetic" else "Рабочие гипотезы. ") +
            "Профили и числа требуют проверки.</strong><p>" + e(data["fallback"]) + "</p>" + missing + "<p>" + e(data["order_meaning"]) + "</p></div>" + "".join(cards) +
            "<article><div class='eyebrow'>Поиск</div><h2>Что ещё нужно проверить</h2><div class='stats'><div><strong>" + str(len(plan["scheduled"])) + "</strong>ячеек плана</div><div><strong>" +
            str(ex["completed_current_plan_cells"]) + "</strong>завершено по журналу</div><div><strong>" + str(len(plan["deferred"])) + "</strong>вне лимита</div></div><p>Остаток: " +
            str(ex["remaining_calls"]) + " вызовов / " + str(ex["remaining_pages"]) + " страниц. Эта команда не выполняет поиск.</p><p>Не хватает для поиска: " +
            e("; ".join(plan["missing_for_search"]) or "базовые входы есть") + ". Нет языкового пакета: " + e(", ".join(plan["unsupported_geographies"]) or "—") +
            ".</p><details><summary>Следующие запросы — проверить перед отправкой</summary><ol>" + queries + "</ol>" + ul(plan["next_steps"]) + "</details><p>Неудачных ячеек, требующих решения о повторе: " +
            str(len(ex["retry_requires_review"])) + ".</p><h3>Остальные форматы</h3>" + ul([p["name"] + ": " + p["reason"] for p in data["deferred_profiles"] + data["excluded_formats"]]) +
            "<p><strong>Следующее решение:</strong> " + e(data["next_decision"]) + "</p></article><details><summary>Бриф, ограничения, исходные допущения и журнал расчёта</summary><pre>" +
            e(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)) + "</pre></details><footer>partner-strategy-1 · Хеш брифа: " + e(data["brief_sha256"]) + "</footer></main></body></html>")
