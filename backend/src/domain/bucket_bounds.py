"""区间车数 + 周总等待分钟约束下的双重差分上下限。

门岗逐市场逐日只报各等候区间的车辆数（单车分钟未知），周账另记同一市场同一
自然周这批车的总等待分钟。本模块在两类约束同时成立时，给出四格均值与双重差分
可达到的最小/最大值：

* 每个市场日总等待分钟 S_d 落在区间车数推出的 [lo_d, hi_d] 内；
* 有周账且该市场周观测逐日齐全时，一周各日 S_d 之和等于周总分钟；
* 目标（四格均值、双重差分、安慰剂）对 S_d 线性，约束按自然周解耦，
  极值可在每个市场周内按系数正负贪心分配得到，且因输入均为整数分钟，
  上下限解可取到整数。

跨试点启动日的自然周整体参与约束；窗口外但属于同一自然周的天也计入周约束。
"""

from datetime import date, timedelta
from fractions import Fraction

from .spec import SPEC

_BUCKET = SPEC["bucket"]
_GROUPS = ("试点组", "对照组")
_TREATED, _CONTROL = _GROUPS
_BUCKETS = _BUCKET["buckets"]
_BUCKET_KEYS = tuple(item["key"] for item in _BUCKETS)
_GATE_REQUIRED = {"market_id", "date", "group", "counts"}
_LEDGER_REQUIRED = {field["key"] for field in _BUCKET["ledger_fields"]}


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #
def _parse_day(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label}须使用 YYYY-MM-DD 日期。")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}须使用有效的 YYYY-MM-DD 日期。") from None
    if value != parsed.isoformat():
        raise ValueError(f"{label}须使用有效的 YYYY-MM-DD 日期。")
    return parsed


def _is_int(value):
    return type(value) is int and not isinstance(value, bool)


def validate_gate_rows(rows):
    """校验门岗区间车数记录，返回归一化后的列表。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("门岗区间车数至少需一条市场日记录。")
    result, groups, seen = [], {}, set()
    for index, row in enumerate(rows, start=1):
        label = f"第 {index} 条门岗记录"
        if not isinstance(row, dict) or not _GATE_REQUIRED <= row.keys():
            raise ValueError(f"{label}缺少市场日字段或格式有误。")
        market = row["market_id"]
        if not isinstance(market, str) or not market.strip() or len(market.strip()) > 300:
            raise ValueError(f"{label}的市场名称须为 1–300 个字符。")
        market = market.strip()
        day = _parse_day(row["date"], f"{label}的观测日期").isoformat()
        group = row["group"]
        if group not in _GROUPS:
            raise ValueError(f"{label}的分组须为试点组或对照组。")
        if groups.setdefault(market, group) != group:
            raise ValueError(f"市场「{market}」的试点分组不一致。")
        if (market, day) in seen:
            raise ValueError(f"市场「{market}」在 {day} 的门岗记录重复。")
        counts = row["counts"]
        if not isinstance(counts, dict):
            raise ValueError(f"{label}的区间车数须为按区间键给出的整数映射。")
        unknown = counts.keys() - _BUCKET_KEYS
        if unknown:
            raise ValueError(f"{label}包含未知等候区间：{ '、'.join(sorted(unknown)) }。")
        clean = {}
        total = 0
        for key in _BUCKET_KEYS:
            value = counts.get(key, 0)
            if not _is_int(value) or not 0 <= value <= 10000:
                raise ValueError(f"{label}的「{key}」车辆数须为 0–10000 的整数。")
            clean[key] = value
            total += value
        if not 1 <= total <= 10000:
            raise ValueError(f"{label}各区间车辆数合计须为 1–10000。")
        seen.add((market, day))
        result.append({"market_id": market, "date": day, "group": group,
                       "counts": clean, "truck_count": total})
    return result


def validate_ledger_rows(rows):
    """校验周账记录，返回 (market, week_start_iso) -> 总分钟 的映射。"""
    if not isinstance(rows, (list, tuple)) or not rows:
        raise ValueError("周账至少需一条市场周记录。")
    ledger, seen = {}, set()
    for index, row in enumerate(rows, start=1):
        label = f"第 {index} 条周账记录"
        if not isinstance(row, dict) or not _LEDGER_REQUIRED <= row.keys():
            raise ValueError(f"{label}缺少周账字段或格式有误。")
        market = row["market_id"]
        if not isinstance(market, str) or not market.strip() or len(market.strip()) > 300:
            raise ValueError(f"{label}的市场名称须为 1–300 个字符。")
        market = market.strip()
        week = _parse_day(row["week_start"], f"{label}的周起始日")
        if week.weekday() != 0:
            raise ValueError(f"{label}的周起始日 {week.isoformat()} 不是周一。")
        total = row["total_wait_minutes"]
        if not _is_int(total) or not 0 <= total <= 100_000_000:
            raise ValueError(f"{label}的周总等待分钟须为非负整数。")
        key = (market, week.isoformat())
        if key in seen:
            raise ValueError(f"市场「{market}」在 {week.isoformat()} 当周的周账重复。")
        seen.add(key)
        ledger[key] = Fraction(total)
    return ledger


# --------------------------------------------------------------------------- #
# 区间界与自然周
# --------------------------------------------------------------------------- #
def day_bounds(counts):
    """由区间车数推单个市场日总等待分钟的上下界。"""
    lo = hi = Fraction(0)
    for bucket in _BUCKETS:
        n = counts[bucket["key"]]
        lo += Fraction(bucket["lower"]) * n
        # 末区间含上界，其余区间上界不含；整数分钟下「不含上界」的最大整数
        # 取值为上界减 1 分钟。
        effective_hi = bucket["upper"] if bucket is _BUCKETS[-1] else bucket["upper"] - 1
        hi += Fraction(effective_hi) * n
    return lo, hi


def week_start_of(day):
    """返回 day 所在自然周的周一（date）。"""
    return day - timedelta(days=day.weekday())


# --------------------------------------------------------------------------- #
# 平衡面板（与均值批次同口径），但保留窗口外观测用于周约束
# --------------------------------------------------------------------------- #
def build_panel(gate_rows, start_ord, end_ord, days):
    """返回纳入市场、覆盖清单、每个市场的全部观测（含窗口外）。"""
    by_market = {}
    outside = 0
    for row in gate_rows:
        ordinal = date.fromisoformat(row["date"]).toordinal()
        bucket = by_market.setdefault(row["market_id"], {"group": row["group"], "all": {}, "inside": {}})
        bucket["all"][ordinal] = row
        if start_ord <= ordinal < end_ord:
            bucket["inside"][ordinal] = row
        else:
            outside += 1

    included, coverage = [], []
    sizes = dict.fromkeys(_GROUPS, 0)
    for market in sorted(by_market):
        bucket = by_market[market]
        observed = bucket["inside"]
        missing = [date.fromordinal(o).isoformat() for o in range(start_ord, end_ord) if o not in observed]
        coverage.append({
            "market": market, "group": bucket["group"],
            "observed_days": len(observed), "expected_days": end_ord - start_ord,
            "status": "排除" if missing else "纳入",
            "missing": "、".join(missing) if missing else "无",
        })
        if not missing:
            included.append(market)
            sizes[bucket["group"]] += 1

    absent = [group for group, count in sizes.items() if count == 0]
    if absent:
        raise ValueError(f"{'、'.join(absent)}无完整观测市场。请补齐每日记录或调整窗口。")
    return included, sizes, coverage, outside, by_market


# --------------------------------------------------------------------------- #
# 周结构：把纳入市场的观测按 (市场, 周一起始日) 聚合，并与周账对账
# --------------------------------------------------------------------------- #
def build_weeks(included, by_market, ledger, start_ord, end_ord):
    """构造周聚合与对账结论。

    返回 (weeks, reconciliation)：
    weeks: list[dict]，每项含 market/group/week_start/days（日序号列表）、
           每日 lo/hi、ledger（Fraction 或 None）、status。
    reconciliation: 面向展示的对账行。
    """
    weeks, reconciliation = [], []
    for market in included:
        group = by_market[market]["group"]
        all_obs = by_market[market]["all"]
        grouped = {}
        for ordinal, row in sorted(all_obs.items()):
            monday = week_start_of(date.fromordinal(ordinal))
            grouped.setdefault(monday, []).append(ordinal)
        for monday in sorted(grouped):
            ordinals = sorted(grouped[monday])
            day_lo, day_hi = {}, {}
            for ordinal in ordinals:
                lo, hi = day_bounds(all_obs[ordinal]["counts"])
                day_lo[ordinal], day_hi[ordinal] = lo, hi
            week_iso = monday.isoformat()
            ledger_value = ledger.get((market, week_iso))
            lo_sum, hi_sum = sum(day_lo.values()), sum(day_hi.values())

            # 该周是否与估计窗口相交；只保留相交的周，纯窗口外周不影响目标。
            week_end_ord = (monday + timedelta(days=7)).toordinal()
            intersects = max(monday.toordinal(), start_ord) < min(week_end_ord, end_ord)
            if not intersects:
                continue

            inside_days = [o for o in ordinals if start_ord <= o < end_ord]
            full_week = len(ordinals) == 7
            if ledger_value is None:
                status = "无周账"
            elif not full_week:
                # 有周账但该周观测不逐日齐全（含缺报或数据集只覆盖部分周）：
                # 周账无法与门岗口径对齐，记为软冲突，周约束不启用。
                status = "周账无法核对（观测缺日）"
            elif ledger_value < lo_sum or ledger_value > hi_sum:
                status = "对账冲突"
            else:
                status = "已对账"
            weeks.append({
                "market": market, "group": group, "week_start": week_iso,
                "ordinals": ordinals, "lo": day_lo, "hi": day_hi,
                "ledger": ledger_value, "status": status,
                "lo_sum": lo_sum, "hi_sum": hi_sum,
                "touches_window": bool(inside_days),
            })
            reconciliation.append({
                "market": market, "group": group, "week_start": week_iso,
                "status": status,
                "observed_days": len(ordinals),
                "daily_lower_sum": _num(lo_sum), "daily_upper_sum": _num(hi_sum),
                "ledger_minutes": None if ledger_value is None else _num(ledger_value),
                "in_window_days": len(inside_days),
                "detail": _reconcile_detail(status, lo_sum, hi_sum, ledger_value),
            })
    return weeks, reconciliation


def _cross_check_ledger(ledger, by_market, included, start_ord, end_ord):
    """核对周账与门岗是否对得上：标记门岗里找不到对应市场的周账记录。

    纳入市场的周已在 build_weeks 中处理；这里只覆盖门岗完全没有该市场、
    或该市场被平衡面板排除的情况，并按与估计窗口是否相交过滤。
    """
    rows = []
    group_of = {market: by_market[market]["group"] for market in by_market}
    for (market, week_iso), total in sorted(ledger.items()):
        monday = date.fromisoformat(week_iso)
        week_end_ord = (monday + timedelta(days=7)).toordinal()
        intersects = max(monday.toordinal(), start_ord) < min(week_end_ord, end_ord)
        if not intersects:
            continue
        if market in included:
            continue  # 已在 build_weeks 中按周对账
        if market not in by_market:
            status = "对账冲突（门岗缺该市场）"
            detail = (f"周账记录了市场「{market}」{week_iso} 当周 {_num(total):g} 分钟，"
                      "但门岗区间车数中没有该市场，跨系统数据对不上。")
        else:
            # 门岗有该市场但因窗口内缺报被平衡面板排除：属覆盖问题（见覆盖表），
            # 不记为数值对账冲突，仅说明周账未启用。
            status = "市场已排除（周账未启用）"
            detail = f"市场「{market}」因窗口内缺报被排除，其 {week_iso} 当周周账不参与测算。"
        rows.append({
            "market": market, "group": group_of.get(market, "未知"),
            "week_start": week_iso, "status": status, "observed_days": 0,
            "in_window_days": 0, "daily_lower_sum": None, "daily_upper_sum": None,
            "ledger_minutes": _num(total), "detail": detail,
        })
    return rows


def _reconcile_detail(status, lo_sum, hi_sum, ledger_value):
    if status == "对账冲突":
        if ledger_value < lo_sum:
            return f"周账 {_num(ledger_value):g} 分钟低于每日区间下界之和 {_num(lo_sum):g}。"
        return f"周账 {_num(ledger_value):g} 分钟高于每日区间上界之和 {_num(hi_sum):g}。"
    if status == "已对账":
        return f"周总分钟落在 [{_num(lo_sum):g}, {_num(hi_sum):g}] 内。"
    if status == "无周账":
        return "该周未提供周账，仅使用每日区间界。"
    return "门岗观测缺日，周账无法逐日核对，本周不启用周总额约束。"


# --------------------------------------------------------------------------- #
# 线性目标在周解耦约束下的极值
# --------------------------------------------------------------------------- #
def _week_extreme(week, coef, maximize):
    """单个市场周在线性日系数 coef[(market, ordinal)] 下的极值分配。

    返回 (分配 dict[ordinal -> 分钟], 目标值 Fraction)。无周账或周账不可用
    （缺日软冲突）时只按日界取端点。
    """
    market = week["market"]
    ordinals = week["ordinals"]
    lo, hi = week["lo"], week["hi"]

    def c_at(o):
        return coef.get((market, o), Fraction(0))

    # 对账冲突的周周账不可行，回退为仅使用每日区间界，但保留冲突标记。
    if week["status"] != "已对账":
        assign, value = {}, Fraction(0)
        for o in ordinals:
            c = c_at(o)
            if c == 0:
                pick = lo[o]
            else:
                pick = hi[o] if (c > 0) == maximize else lo[o]
            assign[o] = pick
            value += c * pick
        return assign, value

    target = week["ledger"]
    assign = {o: lo[o] for o in ordinals}
    slack = target - sum(assign.values())
    if slack < 0:  # 理论上已在对账阶段拦截，防御性处理。
        raise ValueError(f"市场「{market}」{week['week_start']} 周账不可行。")
    order = sorted(ordinals, key=lambda o: c_at(o), reverse=maximize)
    for o in order:
        if slack == 0:
            break
        room = hi[o] - assign[o]
        added = min(room, slack)
        assign[o] += added
        slack -= added
    if slack != 0:
        raise ValueError(f"市场「{market}」{week['week_start']} 周账无法在区间界内分配。")
    value = sum(c_at(o) * assign[o] for o in ordinals)
    return assign, value


def solve_objective(weeks, coef, maximize):
    """对全部市场周求目标 sum(coef * S) 的极值，返回 (总值, 每日分配)。

    每日分配键为 ordinal（不同市场 ordinal 相同但分属不同周对象，合并时
    以 (market, ordinal) 唯一化）。
    """
    total = Fraction(0)
    assignment = {}
    for week in weeks:
        assign, value = _week_extreme(week, coef, maximize)
        total += value
        for o, minutes in assign.items():
            assignment[(week["market"], o)] = minutes
    return total, assignment


# --------------------------------------------------------------------------- #
# 面板系数：四格均值 / 双重差分 / 安慰剂
# --------------------------------------------------------------------------- #
def cell_coefficients(included, by_market, start_ord, pilot_ord, end_ord):
    """生成四格（组 × 试点前/后）的日系数映射与分母。

    系数键为 (market, ordinal)，每个市场日等权 1/(市场数 × 天数)。
    """
    cells = {}
    for group in _GROUPS:
        markets = [m for m in included if by_market[m]["group"] == group]
        n_markets = len(markets)
        for period_index, (lo_b, hi_b) in enumerate((
            (start_ord, pilot_ord),       # 试点前（两段合并）
            (pilot_ord, end_ord),         # 试点后
        )):
            period = "试点前" if period_index == 0 else "试点后"
            n_days = hi_b - lo_b
            denom = Fraction(n_markets * n_days)
            coef = {}
            for market in markets:
                for o in range(lo_b, hi_b):
                    coef[(market, o)] = Fraction(1) / denom
            cells[(group, period)] = {
                "coef": coef, "denom": denom,
                "markets": n_markets, "market_days": n_markets * n_days,
                "start": lo_b, "end": hi_b,
            }
    return cells


def analyze_bounds(gate_rows, ledger_rows, normalized_params):
    """主入口：返回与均值批次同构的结果字典（metrics/tables/charts/sections）。"""
    gate = validate_gate_rows(gate_rows)
    ledger = validate_ledger_rows(ledger_rows) if ledger_rows else {}
    start_ord, pilot_ord, end_ord, days, threshold = _parameters(normalized_params)

    included, sizes, coverage, outside, by_market = build_panel(gate, start_ord, end_ord, days)
    weeks, reconciliation = build_weeks(included, by_market, ledger, start_ord, end_ord)
    orphan_rows = _cross_check_ledger(ledger, by_market, included, start_ord, end_ord)
    reconciliation = reconciliation + orphan_rows
    hard_conflicts = [row for row in reconciliation if row["status"].startswith("对账冲突")]

    cells = cell_coefficients(included, by_market, start_ord, pilot_ord, end_ord)

    # 四格均值上下限
    cell_results = {}
    for key, spec_cell in cells.items():
        coef = spec_cell["coef"]
        lo_val, lo_assign = solve_objective(weeks, coef, False)
        hi_val, hi_assign = solve_objective(weeks, coef, True)
        cell_results[key] = {"lo": lo_val, "hi": hi_val,
                             "lo_assign": lo_assign, "hi_assign": hi_assign}

    # 双重差分 = (试点后-试点前)_试点组 - (试点后-试点前)_对照组
    did_lo = did_hi = None
    did_lo_assign = did_hi_assign = None
    did_coef = {}
    for group in _GROUPS:
        sign = Fraction(1) if group == _TREATED else Fraction(-1)
        for period in ("试点前", "试点后"):
            period_sign = sign * (Fraction(-1) if period == "试点前" else Fraction(1))
            for (market, o), c in cells[(group, period)]["coef"].items():
                did_coef[(market, o)] = did_coef.get((market, o), Fraction(0)) + period_sign * c
    did_lo, did_lo_assign = solve_objective(weeks, did_coef, False)
    did_hi, did_hi_assign = solve_objective(weeks, did_coef, True)

    # 试点前安慰剂：以第二段起点为假启动日，比较两组前段→后段变化之差
    placebo_coef = {}
    seg_bounds = ((start_ord, pilot_ord - days), (pilot_ord - days, pilot_ord))
    for group in _GROUPS:
        sign = Fraction(1) if group == _TREATED else Fraction(-1)
        markets = [m for m in included if by_market[m]["group"] == group]
        denom = Fraction(len(markets) * days)
        for seg_index, (lo_b, hi_b) in enumerate(seg_bounds):
            seg_sign = sign * (Fraction(-1) if seg_index == 0 else Fraction(1))
            for market in markets:
                for o in range(lo_b, hi_b):
                    placebo_coef[(market, o)] = placebo_coef.get((market, o), Fraction(0)) + seg_sign / denom
    placebo_lo, _ = solve_objective(weeks, placebo_coef, False)
    placebo_hi, _ = solve_objective(weeks, placebo_coef, True)
    review_pretrend = abs(placebo_lo) > threshold or abs(placebo_hi) > threshold

    return _assemble_result(locals())


# --------------------------------------------------------------------------- #
# 参数与结果组装
# --------------------------------------------------------------------------- #
def _parameters(normalized_params):
    if not isinstance(normalized_params, dict):
        raise ValueError("运行参数格式有误。")
    pilot = _parse_day(normalized_params.get("pilot_date", "2026-11-09"), "试点启动日").toordinal()
    days = normalized_params.get("window_days", 7)
    if not _is_int(days) or not 1 <= days <= 28:
        raise ValueError("每段自然日数须为 1–28 的整数。")
    threshold_raw = normalized_params.get("pretrend_threshold", 2)
    if type(threshold_raw) not in (int, float) or not 0 <= threshold_raw <= 1440:
        raise ValueError("试点前偏离阈值须为 0–1440 分钟。")
    threshold = Fraction(str(threshold_raw))
    start, end = pilot - 2 * days, pilot + days
    if start < date.min.toordinal() or end - 1 > date.max.toordinal():
        raise ValueError("试点窗口超出有效日期范围，请调整启动日或每段天数。")
    return start, pilot, end, days, threshold


def _num(value):
    """Fraction 转展示浮点，保留 2 位。"""
    return float(round(value, 2))


def _range_label(start_ord, end_ord):
    return f"{date.fromordinal(start_ord).isoformat()} 至 {date.fromordinal(end_ord - 1).isoformat()}"


def _table(title, columns, rows):
    return {"title": title,
            "columns": [{"key": key, "label": label} for key, label in columns],
            "rows": rows}


def _daily_total_rows(included, by_market, assignment, start_ord, end_ord):
    """生成每日等待总分钟表（取某个极值分配），窗口外但有观测的天也列出。

    assignment 键为 (market, ordinal)。
    """
    rows = []
    for market in included:
        for ordinal in sorted(by_market[market]["all"]):
            row = by_market[market]["all"][ordinal]
            lo, hi = day_bounds(row["counts"])
            in_window = start_ord <= ordinal < end_ord
            rows.append({
                "market": market, "group": row["group"],
                "date": date.fromordinal(ordinal).isoformat(),
                "in_window": "窗口内" if in_window else "窗口外",
                "trucks": row["truck_count"],
                "lower_minutes": _num(lo), "upper_minutes": _num(hi),
                "total_minutes": _num(assignment.get((market, ordinal), lo)),
                "week_start": week_start_of(date.fromordinal(ordinal)).isoformat(),
            })
    rows.sort(key=lambda r: (r["market"], r["date"]))
    return rows


def _assemble_result(ctx):
    included = ctx["included"]
    sizes = ctx["sizes"]
    coverage = ctx["coverage"]
    outside = ctx["outside"]
    reconciliation = ctx["reconciliation"]
    hard_conflicts = ctx["hard_conflicts"]
    cell_results = ctx["cell_results"]
    did_lo, did_hi = ctx["did_lo"], ctx["did_hi"]
    placebo_lo, placebo_hi = ctx["placebo_lo"], ctx["placebo_hi"]
    threshold = ctx["threshold"]
    start_ord, pilot_ord, end_ord, days = ctx["start_ord"], ctx["pilot_ord"], ctx["end_ord"], ctx["days"]
    by_market = ctx["by_market"]
    weeks = ctx["weeks"]
    cells_meta = ctx["cells"]

    cutoff = date.fromordinal(pilot_ord - days).isoformat()
    width = did_hi - did_lo
    midpoint = (did_lo + did_hi) / 2
    warnings = []
    excluded = len(coverage) - sum(sizes.values())
    if excluded:
        warnings.append(f"{excluded} 家市场因缺报排除。")
    if hard_conflicts:
        warnings.append(f"{len(hard_conflicts)} 个市场周对账冲突，已在对账表标出。")
    if any(row["status"] == "周账无法核对（观测缺日）" for row in reconciliation):
        warnings.append("部分市场周有周账但门岗缺日，周约束未启用。")
    excluded_ledger = [row for row in reconciliation if row["status"] == "市场已排除（周账未启用）"]
    if excluded_ledger:
        markets = sorted({row["market"] for row in excluded_ledger})
        warnings.append(f"{'、'.join(markets)} 的周账因市场被排除而未启用。")
    if min(sizes.values()) < 2:
        warnings.append("至少一组仅有一家完整市场，估计易受单个市场影响。")
    if ctx["review_pretrend"]:
        warnings.append("试点前安慰剂区间触及复核阈值，复核同期变化假设。")

    cell_rows = []
    for group in _GROUPS:
        for period in ("试点前", "试点后"):
            res = cell_results[(group, period)]
            meta = cells_meta[(group, period)]
            cell_rows.append({
                "group": group, "period": period,
                "dates": _range_label(meta["start"], meta["end"]),
                "markets": meta["markets"], "market_days": meta["market_days"],
                "lower_wait": _num(res["lo"]), "upper_wait": _num(res["hi"]),
                "wait_span": _num(res["hi"] - res["lo"]),
            })

    metrics = [
        {"label": "双重差分下限（分钟）", "value": _num(did_lo),
         "detail": "周账与区间界同时成立时可达到的最小双重差分，负值表示相对缩短。"},
        {"label": "双重差分上限（分钟）", "value": _num(did_hi),
         "detail": "周账与区间界同时成立时可达到的最大双重差分。"},
        {"label": "双重差分区间宽度（分钟）", "value": _num(width),
         "detail": "上限减下限，宽度越大说明区间车数口径下不确定性越高。"},
        {"label": "双重差分区间中点（分钟）", "value": _num(midpoint),
         "detail": "仅供对照的区间中心，不是点估计。"},
        {"label": "试点前安慰剂差分区间（分钟）",
         "value": f"{_num(placebo_lo):g} ~ {_num(placebo_hi):g}",
         "detail": f"假启动日 {cutoff}；区间触及阈值 {float(threshold):g} 分钟时提示复核。"},
        {"label": "平衡市场数", "value": sum(sizes.values()),
         "detail": f"窗口内 {len(coverage)} 家市场，排除 {excluded} 家；窗口外 {outside} 条观测计入所在周约束。"},
        {"label": "对账冲突市场周", "value": len(hard_conflicts),
         "detail": "周总分钟落在每日区间界之和之外的市场周数量。"},
    ]

    daily_lo_rows = _daily_total_rows(included, by_market, ctx["did_lo_assign"], start_ord, end_ord)
    daily_hi_rows = _daily_total_rows(included, by_market, ctx["did_hi_assign"], start_ord, end_ord)

    tables = [
        _table("四格平均等候上下限（分钟）", (
            ("group", "分组"), ("period", "阶段"), ("dates", "观测日期（含首尾）"),
            ("markets", "市场数"), ("market_days", "市场日数"),
            ("lower_wait", "下限"), ("upper_wait", "上限"), ("wait_span", "区间宽度"),
        ), cell_rows),
        _table("周账与每日区间界对账", (
            ("market", "市场"), ("group", "分组"), ("week_start", "周起始日（周一）"),
            ("status", "对账状态"), ("observed_days", "观测日数"),
            ("in_window_days", "窗口内日数"),
            ("daily_lower_sum", "每日下界之和"), ("daily_upper_sum", "每日上界之和"),
            ("ledger_minutes", "周账总分钟"), ("detail", "说明"),
        ), reconciliation),
        _table("市场观测覆盖", (
            ("market", "市场"), ("group", "分组"), ("observed_days", "已报日数"),
            ("expected_days", "应报日数"), ("status", "样本状态"), ("missing", "缺报日期"),
        ), coverage),
        _table("每日等待总分钟 · 取下限解", (
            ("market", "市场"), ("group", "分组"), ("date", "日期"),
            ("in_window", "窗口位置"), ("week_start", "周起始日"), ("trucks", "车辆数"),
            ("lower_minutes", "日下界"), ("upper_minutes", "日上界"),
            ("total_minutes", "该解总分钟"),
        ), daily_lo_rows),
        _table("每日等待总分钟 · 取上限解", (
            ("market", "市场"), ("group", "分组"), ("date", "日期"),
            ("in_window", "窗口位置"), ("week_start", "周起始日"), ("trucks", "车辆数"),
            ("lower_minutes", "日下界"), ("upper_minutes", "日上界"),
            ("total_minutes", "该解总分钟"),
        ), daily_hi_rows),
    ]

    charts = [
        {"title": "双重差分可达区间（分钟）", "kind": "range", "series": [
            {"label": "双重差分", "low": _num(did_lo), "high": _num(did_hi)},
            {"label": "安慰剂差分", "low": _num(placebo_lo), "high": _num(placebo_hi)},
        ]},
        {"title": "四格平均等候上下限（分钟）", "kind": "bar", "series": [
            {"label": f"{row['group']} · {row['period']}（下限）", "value": row["lower_wait"]}
            for row in cell_rows] + [
            {"label": f"{row['group']} · {row['period']}（上限）", "value": row["upper_wait"]}
            for row in cell_rows]},
    ]

    sections = [
        {"title": "数据口径与约束", "text":
            "门岗仅报各等候区间车辆数，单车分钟未知；每个市场日总分钟被区间界限定。"
            "周账给出同一市场同一自然周的总等待分钟，与区间界同时成立。"
            "跨试点启动日的自然周整体参与约束，窗口外的天也计入所在周的总额。"},
        {"title": "上下限如何取到", "text":
            "双重差分对每日总分钟是线性函数，各自然周约束彼此解耦。"
            "在每个市场周内，把可分配的周总分钟按日系数从大到小（求上限）或从小到大（求下限）"
            "贪心填入区间界，即可同时达到全局上下限；整数分钟保证解为整数。"},
        {"title": "对账冲突与解释限制", "text":
            "周总分钟低于每日下界之和或高于每日上界之和时记为对账冲突并列出市场与周；"
            "有周账但门岗缺日的周无法核对，不启用周约束。"
            "因果解释仍依赖平行趋势、无提前响应和无跨市场分流，缺报筛选会影响代表性。"},
    ]

    state = "warning" if warnings else "ok"
    return {
        "mode": "bucket_bounds",
        "state": state,
        "headline": f"双重差分可达区间为 [{_num(did_lo):+g}, {_num(did_hi):+g}] 分钟。",
        "note": f"纳入 {sum(sizes.values())} 家市场；窗口外 {outside} 条观测计入周约束。" + "".join(warnings),
        "metrics": metrics, "tables": tables, "charts": charts, "sections": sections,
        "bounds": {"did_lower": _num(did_lo), "did_upper": _num(did_hi),
                   "did_lower_exact": str(did_lo), "did_upper_exact": str(did_hi),
                   "placebo_lower": _num(placebo_lo), "placebo_upper": _num(placebo_hi),
                   "conflict_weeks": [f"{r['market']} {r['week_start']}" for r in hard_conflicts]},
        "daily_totals": {"lower": daily_lo_rows, "upper": daily_hi_rows},
        "reconciliation": reconciliation,
    }
