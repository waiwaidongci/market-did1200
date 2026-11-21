import csv
from src.config.settings import ARTIFACTS


def safe_cell(value):
    if isinstance(value, str) and (value.lstrip().startswith(('=', '+', '-', '@'))
                                   or value.startswith(('\t', '\r', '\n'))):
        return "'" + value
    return value


def write_report(run_id, attempt, result):
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'analysis-{run_id}-{attempt}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(result['headline'])])
        writer.writerow([safe_cell(result.get('note', ''))])
        for metric in result['metrics']:
            writer.writerow([safe_cell(metric['label']), safe_cell(metric['value']), safe_cell(metric.get('detail', ''))])
        for table in result['tables']:
            writer.writerow([])
            writer.writerow([safe_cell(table['title'])])
            columns = table['columns']
            writer.writerow([safe_cell(column['label']) for column in columns])
            writer.writerows([safe_cell(row.get(column['key'])) for column in columns] for row in table['rows'])
    staging.replace(path)
    return name


def write_bound_report(run_id, attempt, result):
    """上下限报告：指标、四格区间、对账表，并附每日等待总分钟可达的上下限两端。"""
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    name = f'bound-analysis-{run_id}-{attempt}.csv'
    path = ARTIFACTS / name
    staging = path.with_suffix('.tmp')
    with staging.open('w', encoding='utf-8-sig', newline='') as output:
        writer = csv.writer(output)
        writer.writerow([safe_cell(result['headline'])])
        writer.writerow([safe_cell(result.get('note', ''))])
        for metric in result['metrics']:
            writer.writerow([safe_cell(metric['label']), safe_cell(metric['value']),
                             safe_cell(metric.get('detail', ''))])
        for table in result['tables']:
            writer.writerow([])
            writer.writerow([safe_cell(table['title'])])
            columns = table['columns']
            writer.writerow([safe_cell(column['label']) for column in columns])
            writer.writerows([safe_cell(row.get(column['key'])) for column in columns] for row in table['rows'])

        # 每日等待总分钟：同一张表里给出可达的下限端与上限端。
        writer.writerow([])
        writer.writerow(['每日等待总分钟可达两端（同一市场日的下限解与上限解）'])
        writer.writerow(['市场', '分组', '日期', '窗口位置', '周起始日', '车辆数',
                         '日下界', '日上界', '下限解总分钟', '上限解总分钟'])
        lower = {(row['market'], row['date']): row['total_minutes']
                 for row in result['daily_totals']['lower']}
        for row in result['daily_totals']['upper']:
            key = (row['market'], row['date'])
            writer.writerow([
                safe_cell(row['market']), safe_cell(row['group']), safe_cell(row['date']),
                safe_cell(row['in_window']), safe_cell(row['week_start']), safe_cell(row['trucks']),
                safe_cell(row['lower_minutes']), safe_cell(row['upper_minutes']),
                safe_cell(lower.get(key)), safe_cell(row['total_minutes']),
            ])
    staging.replace(path)
    return name
