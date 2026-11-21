"""区间车数与周账的演示数据。

由与均值批次相同的市场/日期/车数骨架派生：逐车生成确定性的等候分钟并归入
对应区间，门岗只保留各区间车数；周账按同一批车的分钟合计生成，因此门岗
区间界与周总分钟天然自洽。东埠仍缺 2026-11-12，用于演示缺报排除。
"""

from datetime import date, timedelta

from .demo import _MARKETS
from .spec import SPEC

_BUCKETS = SPEC['bucket']['buckets']
_BUCKET_KEYS = tuple(item['key'] for item in _BUCKETS)
_START = date(2026, 10, 26)


def _bucket_index(minute):
    for index, bucket in enumerate(_BUCKETS):
        lower, upper = bucket['lower'], bucket['upper']
        if index == len(_BUCKETS) - 1:
            if lower <= minute <= upper:
                return index
        elif lower <= minute < upper:
            return index
    return len(_BUCKETS) - 1


def _truck_minutes(baseline, offset, weekday, market_index, truck_index, group, week):
    """逐车确定性分钟，试点组在试点后（第 3 周）整体前移。"""
    reduction = 8 if week == 2 and group == '试点组' else 0
    base = baseline + 2 * week + (-2, -1, 0, 1, 0, -1, 3)[weekday] - reduction
    # 在均值附近铺开，制造跨区间分布。
    spread = ((truck_index * 7 + market_index * 3 + offset * 5) % 17) - 8
    minute = int(base + spread)
    return max(0, min(1440, minute))


def _skeleton():
    """复用均值批次的市场、日期、车数与东埠缺报。"""
    from .demo import demo_rows
    return demo_rows()


def demo_gate_rows():
    baseline_of = dict((name, base) for name, _group, base in _MARKETS)
    gate = []
    for row in _skeleton():
        counts = {key: 0 for key in _BUCKET_KEYS}
        day = date.fromisoformat(row['date'])
        offset = (day - _START).days
        week, weekday = divmod(offset, 7)
        market_index = next(i for i, (name, _g, _b) in enumerate(_MARKETS) if name == row['market_id'])
        for truck_index in range(row['truck_count']):
            minute = _truck_minutes(baseline_of[row['market_id']],
                                   offset, weekday, market_index, truck_index, row['group'], week)
            counts[_BUCKET_KEYS[_bucket_index(minute)]] += 1
        gate.append({
            'market_id': row['market_id'], 'date': row['date'], 'group': row['group'],
            'counts': counts, 'truck_count': row['truck_count'],
        })
    return gate


def _gate_day_minute_range(counts):
    lo = hi = 0
    for index, bucket in enumerate(_BUCKETS):
        n = counts[bucket['key']]
        lo += bucket['lower'] * n
        effective_hi = bucket['upper'] if index == len(_BUCKETS) - 1 else bucket['upper'] - 1
        hi += effective_hi * n
    return lo, hi


def demo_ledger_rows(midpoint=True):
    """按 (市场, 自然周) 汇总。midpoint=True 取每日可行区间合计的中点。"""
    grouped = {}
    for row in demo_gate_rows():
        day = date.fromisoformat(row['date'])
        monday = day - timedelta(days=day.weekday())
        lo, hi = _gate_day_minute_range(row['counts'])
        item = grouped.setdefault((row['market_id'], monday), [0, 0])
        item[0] += lo
        item[1] += hi
    ledger = []
    for (market, monday), (lo_sum, hi_sum) in sorted(grouped.items()):
        if midpoint:
            total = (lo_sum + hi_sum) // 2
        else:
            total = lo_sum
        ledger.append({'market_id': market, 'week_start': monday.isoformat(),
                       'total_wait_minutes': int(total)})
    return ledger


def demo_ledger_update_rows():
    """周账更新版本：在可行区间内整体上调，制造与首版不同的周总分钟。"""
    base = {(r['market_id'], r['week_start']): r['total_wait_minutes'] for r in demo_ledger_rows()}
    grouped = {}
    for row in demo_gate_rows():
        day = date.fromisoformat(row['date'])
        monday = day - timedelta(days=day.weekday())
        lo, hi = _gate_day_minute_range(row['counts'])
        item = grouped.setdefault((row['market_id'], monday), [0, 0])
        item[0] += lo
        item[1] += hi
    updated = []
    for (market, monday), (lo_sum, hi_sum) in sorted(grouped.items()):
        current = base[(market, monday.isoformat())]
        # 向上界方向移动可行宽度的四分之一，确保仍是整数且不越界。
        candidate = min(hi_sum, current + max(1, (hi_sum - lo_sum) // 4))
        updated.append({'market_id': market, 'week_start': monday.isoformat(),
                        'total_wait_minutes': int(candidate)})
    return updated
