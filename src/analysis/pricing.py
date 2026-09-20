"""Цены моделей, $ за 1M токенов. Нужны только для оценки стоимости в KPI.

Источник — прайс Anthropic API. Cache read = 0.1x входа, cache write = 1.25x входа
(стандартный TTL). Неизвестная модель -> None: цену не выдумываем, показываем "нет данных".
"""

from __future__ import annotations

# model_id -> (input, output) $/MTok
_BASE = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-fable-5": (10.0, 50.0),
    "claude-mythos-5-1": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-opus-4-8": (5.0, 25.0),
    "claude-opus-4-7": (5.0, 25.0),
    "claude-opus-4-6": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}
# исключения по цене чтения кэша
_CACHE_READ_OVERRIDE = {"claude-fable-5-1": 0.25, "claude-mythos-5-1": 0.25}


def rates(model: str | None) -> dict | None:
    """$/MTok для модели: {"in","out","cacheRead","cacheWrite"} или None."""
    if not isinstance(model, str):
        return None
    key = model
    if key not in _BASE:
        # версии с датой в конце и префиксы провайдеров: berrock/vertex
        stripped = key.replace("anthropic.", "").split("@")[0]
        for known in _BASE:
            if stripped == known or stripped.startswith(known + "-2"):
                key = known
                break
        else:
            return None
    inp, out = _BASE[key]
    return {
        "in": inp,
        "out": out,
        "cacheRead": _CACHE_READ_OVERRIDE.get(key, inp * 0.1),
        "cacheWrite": inp * 1.25,
    }


def billable_input_equivalent(tin: int, tout: int, cache_read: int, cache_write: int) -> int:
    """Единая мера «во что обошёлся участок», в эквиваленте обычных входных токенов.

    Чтение кэша примерно в 10 раз дешевле обычного входа, поэтому делим его на 10.
    Формула живёт здесь одна: детектор и отчёт обязаны считать одинаково.
    """
    return int(tin) + int(tout) + int(cache_write) + int(cache_read) // 10


def step_cost(step: dict) -> float | None:
    """Стоимость одного шага в долларах или None, если модель неизвестна."""
    u = step.get("usage")
    if not isinstance(u, dict):
        return None
    r = rates(step.get("model"))
    if r is None:
        return None
    return (
        u.get("in", 0) * r["in"]
        + u.get("out", 0) * r["out"]
        + u.get("cacheRead", 0) * r["cacheRead"]
        + u.get("cacheWrite", 0) * r["cacheWrite"]
    ) / 1_000_000
