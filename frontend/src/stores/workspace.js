import {request, saveFile} from '../api/http.js';
import {session} from './session.js';

const call = (path, body) => request(path, {token:session.token, body});
export const workspace = {
  spec: null,
  datasets: [],
  runs: [],
  async init() { this.spec = await request('/spec'); },
  async refresh() { [this.datasets, this.runs] = await Promise.all([call('/datasets'), call('/runs')]); },
  getDataset: (id, offset = 0) => call(`/datasets/${id}?offset=${offset}`),
  getRun: id => call(`/runs/${id}`),
  upload: data => call('/datasets', data),
  start: data => call('/runs', data),
  review: (id, data) => call(`/runs/${id}/review`, data),
  audit: () => call('/audit'),
  schedules: () => call('/schedules'),
  deliveries: () => call('/deliveries'),
  schedule: data => call('/schedules', data),
  disable: id => call(`/schedules/${id}/disable`, {}),
  download: (path, filename) => saveFile(path, session.token, filename),
  // 区间车数 + 周账上下限
  bucketSpec: () => call('/bucket/spec'),
  gateDatasets: () => call('/bucket/gate-datasets'),
  ledgerDatasets: () => call('/bucket/ledger-datasets'),
  getGateDataset: id => call(`/bucket/gate-datasets/${id}`),
  uploadGate: data => call('/bucket/gate-datasets', data),
  uploadLedger: data => call('/bucket/ledger-datasets', data),
  boundRuns: () => call('/bucket/runs'),
  startBound: data => call('/bucket/runs', data),
  getBoundRun: id => call(`/bucket/runs/${id}`),
  recomputeBound: id => call(`/bucket/runs/${id}/recompute`, {}),
};
