"""Self-contained Russian reports with original input provenance."""

from html import escape
import json

from .engine import COST_LABELS

CONCLUSIONS = {
    "insufficient_inputs": "Не хватает входов для полного расчёта",
    "nonnegative_in_all_bounds": "Неотрицательный результат во всех заданных границах",
    "negative_in_all_bounds": "Убыток во всех заданных границах",
    "depends_on_assumptions": "Знак результата зависит от допущений",
}


def fmt(value, suffix="", percent=False):
    if value is None:
        return "Не рассчитано"
    if isinstance(value, list):
        if len(value) == 2 and value[0] == value[1]:
            return fmt(value[0], suffix, percent)
        return " … ".join(fmt(x, suffix, percent) for x in value)
    value = value * 100 if percent else value
    return f"{value:,.2f}".replace(",", " ").replace(".", ",").removesuffix(",00") + suffix


def sections(report):
    out = []
    currency = " " + report["scope"]["currency"]
    if "economics" in report:
        e = report["economics"]
        out.append(("01 · Экономика и условия решения", [
            e["meaning"], CONCLUSIONS[e["conclusion"]],
            "Маржа: " + report["inputs"]["economics"]["margin_definition"],
            "Добавочный результат: " + report["inputs"]["economics"]["incremental_outcome_definition"],
            "Состав затрат: " + report["inputs"]["economics"]["cost_scope_note"],
            "Диапазоны считаются по всем сочетаниям границ. Совместимость крайних допущений проверяет аналитик; середина не считается наиболее вероятным исходом.",
            "Предельная цена прав — условие при выбранном сценарии, не рыночная оценка. Отрицательная цена означает, что даже бесплатные права не обеспечивают заданный ROI.",
            "ROI здесь сценарный. Наличие источника и статус observed не подтверждают причинность. Решения о покупке и репутационном допуске остаются у человека.",
            *e["blockers"]], ["Показатель", "Границы / значение"], [
            ["Известная часть затрат", fmt(e["known_cost_subtotal"], currency)],
            ["Полные затраты", fmt(e["total_cost"], currency)],
            ["Добавочных результатов для безубыточности", fmt(e["break_even_outcomes"])],
            ["Заданный целевой ROI", fmt(e["target_roi"], "%", True)],
            ["Добавочных результатов для целевого ROI", fmt(e["target_outcomes"])],
            ["Добавочная маржа до затрат кампании", fmt(e["incremental_contribution"], currency)],
            ["Финансовый результат после затрат", fmt(e["net"], currency)],
            ["Сценарный ROI", fmt(e["roi"], "%", True)],
            ["Максимальная цена прав для целевого ROI", fmt(e["fee_cap"], currency)],
            ["Преимущество над альтернативой по чистому результату", fmt(e["versus_alternative"], currency)],
        ]))
        if e["sensitivity"]:
            out.append(("02 · Что уточнять в первую очередь", [
                "Изменение чистого результата при изменении одного входа от нижней до верхней границы; остальные входы фиксированы в серединах диапазонов.",
                "Это приоритет проверки допущений по величине влияния, не вероятность ошибки и не денежная ценность исследования. Взаимодействия и корреляции здесь не учтены."],
                ["Вход", "Размах результата"], [[x["input"], fmt(x["net_swing"], currency)] for x in e["sensitivity"]]))
        costs = report["inputs"]["economics"]["costs"]
        out.append(("03 · Реестр затрат", ["Все суммы относятся к валюте и окну из паспорта. Явный ноль требует причины; unknown не становится нулём."],
                    ["Статья", "Диапазон", "Статус", "Источник / дата / основание"],
                    [[COST_LABELS[k], fmt([v["low"], v["high"]], currency) if v["status"] != "unknown" else "Неизвестно",
                      {"assumption": "Допущение", "estimate": "Оценка", "observed": "Наблюдение", "unknown": "Неизвестно"}[v["status"]], f'{v["source"]} · {v["as_of"]} · {v["note"]}'] for k, v in costs.items()]))
    if "survey" in report:
        s, raw = report["survey"], report["inputs"]["survey"]
        out.append(("04 · Измерение результата для бренда", [
            raw["metric"] + " · " + raw["population"] + " · " + raw["period"], raw["design_note"], s["interpretation"],
            "Выборка и формулировка вопроса определяют смысл результата. Статистический интервал не учитывает все систематические ошибки. Разница не переводится в деньги автоматически."],
            ["Показатель", "Значение"], [
            ["Ответы в группе воздействия", f'{raw["treatment"]["yes"]} / {raw["treatment"]["n"]}'],
            ["Ответы в сравнении", f'{raw["control"]["yes"]} / {raw["control"]["n"]}'],
            ["Доля в группе воздействия", fmt(s["treatment_rate"], "%", True)],
            ["Доля в сравнении", fmt(s["control_rate"], "%", True)],
            ["Абсолютная разница", fmt(s["difference_pp"], " п.п.")],
            ["Относительная разница", fmt(s["relative_difference"], "%", True)],
            [f'Интервал {fmt(s["confidence_level"], "%", True)}: Newcombe / Wilson', fmt(s["interval_pp"], " п.п.")],
        ]))
    if "sample_plan" in report:
        s, raw = report["sample_plan"], report["inputs"]["sample_plan"]
        out.append(("05 · Можно ли заметить нужный эффект", [s["meaning"],
            "Проверить отклик, отбор, загрязнение контроля и достижимость выборки до оплаты исследования.",
            *(["Малые ожидаемые ячейки: нормальное приближение может быть неточным."] if s["small_expected_cells"] else [])],
            ["Параметр", "Значение"], [
            ["Исходная доля", fmt(raw["baseline_rate"], "%", True)], ["Эффект для планирования", fmt(raw["effect_pp"], " п.п.")],
            ["Мощность / alpha", fmt(raw["power"], "%", True) + " / " + fmt(raw["alpha"])],
            ["Ответов в каждой группе", fmt(s["completed_per_arm"])], ["Ответов всего", fmt(s["completed_total"])],
            ["Приглашений в каждой группе", fmt(s["invitations_per_arm"])], ["Предполагаемый отклик", fmt(raw["response_rate"], "%", True)],
        ]))
    if "audience" in report:
        a, raw = report["audience"], report["inputs"]["audience"]
        rows = [["Размер общей популяции", fmt(raw["population"])], ["Уникальные люди A / B", fmt(raw["reach_a"]) + " / " + fmt(raw["reach_b"])],
                ["Пересечение A и B", fmt(a["overlap"])], ["Объединённый уникальный охват", fmt(a["union"])],
                ["Дополнительные люди B относительно A", fmt(a["new_beyond_a"])]]
        if "joint_target_share" in a:
            rows.append(["Совместная доля всех признаков ЦА", fmt(a["joint_target_share"], "%", True)])
        out.append(("06 · Аудитория без двойного счёта", [a["meaning"], raw["population_definition"] + " · " + raw["period"],
            "Доли GEO, возраста и интереса не перемножаются без основания о независимости. Граница совместной доли относится к исходной популяции; она не умножается автоматически на объединённый охват."], ["Показатель", "Люди / доля"], rows))
    if "ratings" in report:
        a = report["ratings"]
        out.append(("07 · Насколько расходятся оценщики", [a["meaning"],
            "Пропуски: " + (", ".join(a["missing"]) or "нет")], ["Показатель", "Значение"], [
            ["Полных пар оценок", fmt(a["paired"])], ["Точное совпадение", fmt(a["exact_agreement"], "%", True)],
            ["Средний абсолютный разрыв, баллы", fmt(a["mean_absolute_gap"])],
            ["Средний сдвиг A − B, баллы", fmt(a["mean_signed_gap"])],
        ]))
        out.append(("08 · Что разобрать с оценщиками", ["Сначала проверить определение критерия, доступность источников и общую версию пакета. Усреднение не разрешает содержательное разногласие."],
            ["Критерий / объект", "A", "B", "Разрыв"], [[r["id"], fmt(r["a"]), fmt(r["b"]), fmt(r["gap"])] for r in a["rows"]]))
    return out


def markdown(report):
    scope = report["scope"]
    lines = [f'# {report["title"]}', "", "**СИНТЕТИЧЕСКИЙ ПРИМЕР — все числа вымышлены.**" if report["kind"] == "synthetic" else "**Сценарный расчёт по предоставленным входам.**",
             f'{scope["territory"]} · {scope["period_start"]} — {scope["period_end"]} · {scope["currency"]} · единица результата: {scope["outcome_unit"]}', ""]
    clean = lambda value: str(value).replace("|", "\\|").replace("\n", " ")
    for title, notes, headers, rows in sections(report):
        lines.extend(["## " + title, "", *[n + "\n" for n in notes], "| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"])
        lines.extend("| " + " | ".join(clean(v) for v in row) + " |" for row in rows)
        lines.append("")
    lines.extend(["## Воспроизводимость", "", f'Модель: {report["schema_version"]}; SHA-256 входов: {report["input_sha256"]}.',
                  "Все исходные значения, источники и статусы:", "", "```json", json.dumps(report["inputs"], ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def html(report):
    esc = lambda value: escape(str(value), quote=True)
    scope = report["scope"]
    banner = "СИНТЕТИЧЕСКИЙ ПРИМЕР · ВСЕ ЧИСЛА ВЫМЫШЛЕНЫ" if report["kind"] == "synthetic" else "СЦЕНАРНЫЙ РАСЧЁТ · ТРЕБУЕТ ПРОВЕРКИ ВХОДОВ"
    blocks = []
    for title, notes, headers, rows in sections(report):
        head = "".join("<th>" + esc(h) + "</th>" for h in headers)
        body = "".join("<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>" for row in rows)
        table_class = ' class="evidence-table"' if title.startswith("03") else ""
        blocks.append(f'<section><h2>{esc(title)}</h2>' + "".join(f"<p>{esc(n)}</p>" for n in notes[:2]) + f'<div class="table-wrap"><table{table_class}><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>' + "".join(f"<p>{esc(n)}</p>" for n in notes[2:]) + '</section>')
    provenance = esc(json.dumps(report["inputs"], ensure_ascii=False, indent=2))
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'">
<title>{esc(report["title"])}</title><style>
:root{{font-family:Segoe UI,Arial,sans-serif;color:#16312e;background:#f2f4ef;font-size:16px;line-height:1.55}}
*{{box-sizing:border-box}}body{{margin:0}}main{{max-width:1100px;margin:auto;padding:36px 24px 60px}}
header{{background:#153e39;color:#fff;border-radius:18px;padding:30px;margin-bottom:24px}}h1{{font-size:clamp(27px,4vw,43px);line-height:1.15;margin:16px 0}}header p{{color:#d9e9de}}
.badge{{color:#fff0c1;font-weight:700;font-size:12px;letter-spacing:.08em}}section{{background:white;border:1px solid #d8e0d7;border-radius:16px;padding:26px;margin:20px 0}}
h2{{font-size:23px;margin:0 0 12px}}p{{margin:10px 0;color:#425852}}.table-wrap{{overflow-x:auto;margin-top:20px}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}.evidence-table{{min-width:640px}}th,td{{text-align:left;padding:12px;border-bottom:1px solid #e2e8df;vertical-align:top;overflow-wrap:anywhere}}th{{background:#edf3ea;color:#274b40;font-size:13px}}td:first-child{{font-weight:600}}td:last-child{{min-width:135px}}tbody tr:hover{{background:#f8faf6}}
.evidence-table{{table-layout:fixed}}.evidence-table th:nth-child(1){{width:24%}}.evidence-table th:nth-child(2){{width:18%}}.evidence-table th:nth-child(3){{width:16%}}.evidence-table th:nth-child(4){{width:42%}}
details{{background:#e8eee4;padding:20px;border-radius:12px}}summary{{cursor:pointer;font-weight:700}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}footer{{font-size:12px;overflow-wrap:anywhere;margin-top:20px}}
@media(max-width:600px){{main{{padding:16px 10px}}header,section{{padding:18px 14px}}h2{{font-size:20px}}td,th{{padding:10px 8px;font-size:14px}}}}
@media print{{body{{background:#fff}}main{{max-width:none;padding:0}}header{{color:#000;background:white;border:1px solid}}header p,.badge{{color:#000}}section{{break-inside:avoid}}details{{display:none}}}}
</style></head><body><main><header><div class="badge">{banner}</div><h1>{esc(report["title"])}</h1>
<p>Экономика · эффект для бренда · аудитория · расхождения оценщиков</p><p>{esc(scope["territory"])} · {esc(scope["period_start"])} — {esc(scope["period_end"])} · {esc(scope["currency"])}<br>Единица результата: {esc(scope["outcome_unit"])}</p></header>
{"".join(blocks)}<details><summary>Исходные данные, источники и допущения</summary><pre>{provenance}</pre></details>
<footer>Модель {esc(report["schema_version"])} · SHA-256 входов {esc(report["input_sha256"])}<br>Денежный расчёт и результат опроса не объединяются в искусственный «балл окупаемости».</footer></main></body></html>'''
