import {feedback, field} from '../components/common/fields.js';
import {plot} from '../components/common/chart.js';
import {empty, metrics, panel, pill} from '../components/common/panels.js';
import {table} from '../components/common/table.js';
import {STATUS} from '../constants/enums.js';
import {handler, poll} from '../hooks/action.js';
import {session} from '../stores/session.js';
import {workspace} from '../stores/workspace.js';
import {button, el, h, link, p} from '../utils/dom.js';
import {date} from '../utils/format.js';

const SHORT = 'market-did-bounds';

function runStatePill(job) {
  const state = job.status;
  const node = pill(STATUS[state] || state, state);
  if (job.stale && state !== 'superseded') {
    return el('span', {class:'activity'}, node, pill('已失效待重算', 'failed'));
  }
  return node;
}

function uploadForms(bspec, gateDatasets, ledgerDatasets, refresh, message) {
  const gateSample = button('下载门岗模板 CSV', {class:'quiet',
    onClick: handler({}, message, () => workspace.download('/bucket/template/gate', bspec.title + '-门岗.csv'))});
  const ledgerSample = button('下载周账模板 CSV', {class:'quiet',
    onClick: handler({}, message, () => workspace.download('/bucket/template/ledger', bspec.title + '-周账.csv'))});

  const gateForm = session.canWrite && el('form', {class:'fields'},
    el('h3', {}, '导入门岗区间车数'),
    field({key:'gate_name', label:'门岗批次名称', type:'string', max_length:120}, '门岗区间车数批次'),
    el('label', {class:'field'}, el('span', {}, '门岗 CSV（各等候区间车数）'),
      el('input', {name:'source', type:'file', accept:'.csv,text/csv', required:true})),
    button('校验并导入门岗', {type:'submit', class:'primary'}),
    el('div', {class:'actions'}, gateSample));
  gateForm?.addEventListener('submit', handler(gateForm, message, async event => {
    const data = new FormData(event.target);
    const file = data.get('source');
    if (!file?.size) throw new Error('请选择门岗 CSV 文件');
    if (file.size > 2_000_000) throw new Error('CSV 最多 2 MB');
    const item = await workspace.uploadGate({
      name: data.get('gate_name'), filename: file.name, csv_text: await file.text()});
    message.textContent = item.created ? `已导入门岗批次 #${item.id}` : '相同门岗批次已存在，已复用。';
    await refresh();
  }));

  const ledgerForm = session.canWrite && el('form', {class:'fields'},
    el('h3', {}, '导入周总等待分钟（新版本）'),
    p('同名周账再次导入会生成新版本，并把引用旧版本的运行标记失效、自动登记重算。', 'subtle'),
    field({key:'ledger_name', label:'周账业务名称（同名即新版本）', type:'string', max_length:120}, '澄河七家市场同期等候分钟周账'),
    el('label', {class:'field'}, el('span', {}, '周账 CSV'),
      el('input', {name:'source', type:'file', accept:'.csv,text/csv', required:true})),
    button('导入周账并触发对账', {type:'submit', class:'primary'}),
    el('div', {class:'actions'}, ledgerSample));
  ledgerForm?.addEventListener('submit', handler(ledgerForm, message, async event => {
    const data = new FormData(event.target);
    const file = data.get('source');
    if (!file?.size) throw new Error('请选择周账 CSV 文件');
    if (file.size > 2_000_000) throw new Error('CSV 最多 2 MB');
    const item = await workspace.uploadLedger({
      name: data.get('ledger_name'), filename: file.name, csv_text: await file.text()});
    if (item.created && item.replacement_run_ids?.length) {
      message.textContent = `已生成周账 v${item.version}，${item.replacement_run_ids.length} 条旧运行标记失效并重算中。`;
    } else if (item.created) {
      message.textContent = `已导入周账 v${item.version}。`;
    } else {
      message.textContent = '相同周账内容已存在，已复用。';
    }
    await refresh();
  }));

  const gateTable = table([
    {key:'id', label:'#'}, {key:'name', label:'门岗批次'},
    {key:'row_count', label:'行数'}, {key:'author', label:'导入人'},
    {label:'时间', render: row => date(row.created_at)},
  ], gateDatasets, {caption:'门岗批次', empty:'还没有门岗批次。'});
  const ledgerTable = table([
    {key:'id', label:'#'}, {key:'name', label:'周账名称'},
    {key:'version', label:'版本'}, {key:'row_count', label:'行数'},
    {key:'author', label:'导入人'}, {label:'时间', render: row => date(row.created_at)},
  ], ledgerDatasets, {caption:'周账版本', empty:'还没有周账（可只做门岗区间界上下限）。'});

  return panel('数据导入（门岗区间车数 + 周账）',
    p('门岗只报各等待区间的车数；周账另记同一批车按自然周汇总的总等待分钟。两者分别导入、保留指纹。', 'subtle'),
    gateTable, ledgerTable,
    el('div', {class:'two-col'}, gateForm || p('只读角色可查看批次。', 'subtle'),
      ledgerForm || p('只读角色可查看周账版本。', 'subtle')));
}

function runForm(bspec, gateDatasets, ledgerDatasets, refresh, message) {
  if (!session.canWrite) return panel(bspec.title, p('只读角色可查看下方历史上下限运行。', 'empty'));
  if (!gateDatasets.length) return panel(bspec.title, empty('请先导入门岗区间车数。', '#bucket', '前往导入'));
  const params = bspec.params;
  const form = el('form', {class:'fields', 'data-testid':'bound-run-form'},
    field({key:'bound_name', label:'运行名称', type:'string', max_length:120}, '区间周账上下限测算'),
    el('label', {class:'field'}, el('span', {}, '门岗区间车数批次'),
      el('select', {name:'gate_dataset_id', required:true},
        gateDatasets.map(item => el('option', {value:item.id}, `#${item.id} ${item.name} · ${item.row_count} 行`)))),
    el('label', {class:'field'}, el('span', {}, '周账版本（可不选，仅用区间界）'),
      el('select', {name:'ledger_dataset_id'},
        el('option', {value:''}, '不使用周账（区间更宽）'),
        ledgerDatasets.map(item => el('option', {value:item.id}, `#${item.id} ${item.name} · v${item.version}`)))),
    el('div', {class:'form-grid'}, params.map(param => field(param))),
    el('div', {class:'actions'}, button('计算上下限', {type:'submit', class:'primary', 'data-testid':'start-bound-run'})),
    message);
  form.addEventListener('submit', handler(form, message, async event => {
    const data = new FormData(event.target);
    const ledgerId = data.get('ledger_dataset_id');
    const item = await workspace.startBound({
      name: data.get('bound_name'),
      gate_dataset_id: Number(data.get('gate_dataset_id')),
      ledger_dataset_id: ledgerId ? Number(ledgerId) : null,
      params: Object.fromEntries(params.map(param => [param.key, data.get(param.key)])),
    });
    await refresh();
    showRun(item.id, refresh);
  }));
  return panel(bspec.title, form);
}

function showRun(id, refresh) {
  location.hash = `#bucket/${id}`;
  if (location.hash === `#bucket/${id}`) refresh();
}

function runList(boundRuns, message, refresh) {
  return table([
    {label:'运行', render: row => link(row.name, `#bucket/${row.id}`)},
    {label:'状态', render: row => runStatePill(row)},
    {label:'周账版本', render: row => row.ledger_version ? `v${row.ledger_version}` : '—'},
    {label:'替换关系', render: row => {
      if (row.superseded_by) return `已被 #${row.superseded_by} 替换`;
      if (row.replaces_run_id) return `重算自 #${row.replaces_run_id}`;
      return '—';
    }},
    {label:'时间', render: row => date(row.created_at)},
    {label:'操作', render: row => {
      if (row.stale && !row.superseded_by && session.canWrite && !row.replaces_run_id) {
        const btn = button('立即重算', {class:'quiet'});
        btn.addEventListener('click', handler(btn, message, async () => {
          await workspace.recomputeBound(row.id);
          await refresh();
        }));
        return btn;
      }
      return '—';
    }},
  ], boundRuns, {caption:'上下限运行记录', empty:'提交测算后在此显示，含失效与替换血缘。'});
}

function resultPanel(job, bspec, refresh, message) {
  const finished = item => ['complete', 'failed', 'superseded'].includes(item.status);
  if (!finished(job)) {
    const original = location.hash;
    const status = el('p', {role:'status'}, '后台正在计算上下限，完成后自动展示。');
    poll(() => workspace.getBoundRun(job.id), finished, () => location.hash === original)
      .then(item => { if (item && status.isConnected && location.hash === original) refresh(); })
      .catch(error => { if (status.isConnected) status.textContent = error.message; });
    return panel(job.name, runStatePill(job), status, button('刷新', {class:'quiet', onClick: refresh}));
  }
  if (!job.result) {
    return panel(job.name, runStatePill(job), p(job.error || '计算失败。', 'feedback'),
      link('返回调整参数', '#bucket', {class:'quiet'}));
  }
  const result = job.result;
  const download = button('下载结果 CSV（含每日等待总分钟两端）', {class:'quiet',
    'data-testid':'bound-export',
    onClick: handler({}, message, () =>
      workspace.download(`/bucket/runs/${job.id}/export`, `${SHORT}-${job.id}.csv`))});
  const conflictRows = result.reconciliation.filter(row => row.status.startsWith('对账冲突'));
  const conflictBanner = conflictRows.length
    ? el('div', {class:'empty', role:'alert', style:'border-color:oklch(58% .16 29)'},
      p(`发现 ${conflictRows.length} 个对账冲突的市场周（周总分钟与每日区间界对不上），已在对账表标红，这些周回退为仅用区间界：`),
      el('ul', {}, conflictRows.map(row => el('li', {}, `${row.group} · ${row.market} · 周 ${row.week_start}：${row.detail}`))))
    : null;
  const staleBanner = job.stale
    ? el('div', {class:'empty', role:'alert'}, p(job.stale_reason || '上游周账已更新，本结果标记失效。'),
      job.superseded_by ? link(`查看替换结果 #${job.superseded_by}`, `#bucket/${job.superseded_by}`, {class:'quiet'}) : null)
    : null;

  return el('section', {class:'analysis', 'data-testid':'bound-complete'},
    el('div', {class:'result-head'}, p(job.name, 'eyeline'), h(2, result.headline),
      p(result.note, 'intro-copy'), el('div', {class:'actions'}, runStatePill(job), download, message)),
    staleBanner, conflictBanner,
    metrics(result.metrics),
    (result.charts || []).map(plot),
    (result.sections || []).map(item => panel(item.title, p(item.text))),
    result.tables.map(item => panel(item.title, table(item.columns, item.rows, {caption:item.title}))));
}

export async function bucketPage(route, refresh) {
  const message = feedback();
  const [bspec, gateDatasets, ledgerDatasets, boundRuns] = await Promise.all([
    workspace.bucketSpec(), workspace.gateDatasets(), workspace.ledgerDatasets(), workspace.boundRuns()]);
  const id = route.id || boundRuns[0]?.id;
  const job = id ? await workspace.getBoundRun(id).catch(() => null) : null;

  const listPanel = panel('运行与周账血缘', runList(boundRuns, message, refresh));
  const methodPanel = panel('计算口径', el('ul', {class:'method-list'},
    bspec.methodology.map(text => el('li', {}, text))));
  const main = el('div', {},
    uploadForms(bspec, gateDatasets, ledgerDatasets, refresh, message),
    runForm(bspec, gateDatasets, ledgerDatasets, refresh, message),
    job ? resultPanel(job, bspec, refresh, message) : panel(bspec.title, empty('选择一条运行查看上下限与对账结果。')));
  return el('div', {class:'two-col'}, el('div', {class:'wide-panel'}, main),
    el('aside', {class:'sidebar-panel'}, listPanel, methodPanel));
}
