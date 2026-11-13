"""Воспроизводимая арифметика синтетического примера, не код продукта.

Все значения вымышлены. Скрипт проверяет только формулы и устойчивость
методов; его вывод не является рыночной оценкой или прогнозом кампании.
"""

from math import exp, log, sqrt


PACKAGES = {
    "A": {"impressions": (800_000, 1_000_000, 1_200_000), "target_share": 0.80,
          "cost": 200_000, "activation": 80, "rights": 90},
    "B": {"impressions": (1_300_000, 1_600_000, 1_900_000), "target_share": 0.60,
          "cost": 160_000, "activation": 65, "rights": 70},
    "C": {"impressions": (800_000, 1_000_000, 1_200_000), "target_share": 0.75,
          "cost": 230_000, "activation": 75, "rights": 60},
}

DELIVERY_TARGET = 1_000_000  # условный плановый ориентир, не результат кампании
WEIGHTS_BASE = (0.35, 0.25, 0.25, 0.15)
WEIGHTS_DELIVERY = (0.10, 0.60, 0.20, 0.10)


def score_components(package):
    qualified_base = package["impressions"][1] * package["target_share"]
    return (
        100 * package["target_share"],
        min(100, 100 * qualified_base / DELIVERY_TARGET),
        package["activation"],
        package["rights"],
    )


def weighted(values, weights):
    return sum(value * weight for value, weight in zip(values, weights))


def topsis(matrix, weights):
    """Классический TOPSIS с векторной нормализацией; все критерии выгодные."""
    norms = [sqrt(sum(row[j] ** 2 for row in matrix)) for j in range(len(weights))]
    normalized = [
        [row[j] / norms[j] * weights[j] for j in range(len(weights))]
        for row in matrix
    ]
    best = [max(row[j] for row in normalized) for j in range(len(weights))]
    worst = [min(row[j] for row in normalized) for j in range(len(weights))]
    result = []
    for row in normalized:
        distance_best = sqrt(sum((row[j] - best[j]) ** 2 for j in range(len(weights))))
        distance_worst = sqrt(sum((row[j] - worst[j]) ** 2 for j in range(len(weights))))
        result.append(distance_worst / (distance_best + distance_worst))
    return result


def ahp_geometric_weights(matrix):
    means = [exp(sum(log(value) for value in row) / len(row)) for row in matrix]
    return tuple(value / sum(means) for value in means)


def main():
    names = tuple(PACKAGES)
    components = {name: score_components(PACKAGES[name]) for name in names}
    matrix = [components[name] for name in names]

    assert abs(sum(WEIGHTS_BASE) - 1) < 1e-12
    assert abs(sum(WEIGHTS_DELIVERY) - 1) < 1e-12
    assert all(0 <= value <= 100 for row in matrix for value in row)

    print("СИНТЕТИЧЕСКИЙ МЕДИЙНЫЙ СЦЕНАРИЙ")
    for name, package in PACKAGES.items():
        qualified = tuple(round(value * package["target_share"]) for value in package["impressions"])
        cost_per_thousand = package["cost"] / (qualified[1] / 1000)
        print(f"{name}: показы={package['impressions']}; квалифицированные={qualified}; "
              f"полные затраты=${package['cost']:,}; цена/1000=${cost_per_thousand:.2f}")

    print("\nSCORECARD, КРИТЕРИИ K1–K4")
    for name, row in components.items():
        print(f"{name}: {tuple(round(x, 2) for x in row)}; "
              f"базовые веса={weighted(row, WEIGHTS_BASE):.2f}; "
              f"приоритет доставки={weighted(row, WEIGHTS_DELIVERY):.2f}")

    ahp_matrix = (
        (1, 2, 1, 3),
        (1 / 2, 1, 1 / 2, 2),
        (1, 2, 1, 3),
        (1 / 3, 1 / 2, 1 / 3, 1),
    )
    ahp_weights = ahp_geometric_weights(ahp_matrix)
    aw = [sum(ahp_matrix[i][j] * ahp_weights[j] for j in range(4)) for i in range(4)]
    lambda_estimate = sum(aw[i] / ahp_weights[i] for i in range(4)) / 4
    consistency_index = (lambda_estimate - 4) / 3
    print("\nAHP: веса=" + str(tuple(round(x, 4) for x in ahp_weights)) +
          f"; приближённый индекс согласованности={consistency_index:.4f}")
    for name, row in components.items():
        print(f"{name}: AHP-веса + аддитивная оценка={weighted(row, ahp_weights):.2f}")

    base_topsis = topsis(matrix, WEIGHTS_BASE)
    # E доминируется A по всем критериям. Он добавлен лишь для проверки состава списка.
    dominated_e = (80, 45, 80, 45)
    expanded_topsis = topsis(matrix + [dominated_e], WEIGHTS_BASE)
    print("\nTOPSIS, исходный состав:", dict(zip(names, (round(x, 4) for x in base_topsis))))
    print("TOPSIS, добавлен E:", dict(zip(names + ("E",), (round(x, 4) for x in expanded_topsis))))

    # D имеет неизвестную доставку K2. Диапазон не подставляет ноль как факт.
    d_known = (70, None, 80, 40)
    lower = sum(WEIGHTS_BASE[j] * value for j, value in enumerate(d_known) if value is not None)
    upper = lower + sum(100 * WEIGHTS_BASE[j] for j, value in enumerate(d_known) if value is None)
    coverage = sum(WEIGHTS_BASE[j] for j, value in enumerate(d_known) if value is not None)
    print(f"\nD: K2 неизвестен; диапазон оценки=[{lower:.2f}, {upper:.2f}]; "
          f"покрытие весов={coverage:.0%}; экономика неизвестна")

    assert [names[i] for i in sorted(range(3), key=lambda i: weighted(matrix[i], WEIGHTS_BASE), reverse=True)] == ["A", "C", "B"]
    assert [names[i] for i in sorted(range(3), key=lambda i: weighted(matrix[i], WEIGHTS_DELIVERY), reverse=True)] == ["B", "A", "C"]
    assert base_topsis[2] > base_topsis[1]
    assert expanded_topsis[1] > expanded_topsis[2]
    assert lower == 50.5 and upper == 75.5 and coverage == 0.75
    print("\nАрифметические проверки пройдены.")


if __name__ == "__main__":
    main()
