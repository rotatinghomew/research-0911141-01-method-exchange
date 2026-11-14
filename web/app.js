const state = {context: null, current: null};
const element = identifier => document.getElementById(identifier);

async function request(path, body) {
  const response = await fetch(path, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || '请求失败');
  return value;
}

function message(value, error = false) {
  element('status').textContent = value;
  element('status').className = error ? 'error' : '';
}

async function guarded(action) {
  try { await action(); } catch (error) { message(error.message, true); }
}

function selected() {
  const selection = {};
  for (const control of state.context.product.options) selection[control[0]] = element('select-' + control[0]).value;
  return {
    revision: element('revision').value,
    selection,
    tolerance: {
      absolute: Number.isFinite(parseFloat(element('tolerance-absolute').value))
        ? parseFloat(element('tolerance-absolute').value) : 0,
      relative: Number.isFinite(parseFloat(element('tolerance-relative').value))
        ? parseFloat(element('tolerance-relative').value) : 0
    }
  };
}

function renderControls() {
  const revision = element('revision').value || state.context.default_revision;
  element('revision').replaceChildren();
  for (const dataset of state.context.datasets) {
    const option = document.createElement('option');
    option.value = dataset.revision;
    option.textContent = dataset.label + ' · ' + dataset.revision.slice(0, 9);
    element('revision').append(option);
  }
  element('revision').value = revision;
  if (!element('revision').value) element('revision').value = state.context.default_revision;
  if (element('controls').children.length) return;
  for (const [key, labelText, choices] of state.context.product.options) {
    const label = document.createElement('label');
    label.textContent = labelText;
    const select = document.createElement('select');
    select.id = 'select-' + key;
    for (const choice of choices) {
      const option = document.createElement('option');
      option.value = choice;
      option.textContent = choice;
      select.append(option);
    }
    select.value = state.context.product.selection[key];
    label.append(select);
    element('controls').append(label);
  }
}

function displayValue(value) {
  if (value === null || value === undefined) return '未观测';
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(4);
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

function drawChart(series) {
  const canvas = element('chart');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  const values = series.filter(point => typeof point.y === 'number' && Number.isFinite(point.y));
  context.font = '12px sans-serif';
  if (!values.length) { context.fillText('该范围没有可定量的描述值', 30, 50); return; }
  const low = Math.min(0, ...values.map(point => point.y));
  const high = Math.max(1, ...values.map(point => point.y));
  const scale = value => 250 - (value - low) / (high - low || 1) * 210;
  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(45, 20); context.lineTo(45, 250); context.lineTo(940, 250); context.stroke();
  context.fillStyle = '#0a7168';
  const scatter = values.every(point => typeof point.x === 'number');
  const minimumX = scatter ? Math.min(...values.map(point => point.x)) : 0;
  const maximumX = scatter ? Math.max(...values.map(point => point.x)) : 1;
  values.forEach((point, index) => {
    const position = scatter ? 60 + (point.x - minimumX) / (maximumX - minimumX || 1) * 850 : 55 + index * 875 / values.length;
    if (scatter) {
      context.beginPath(); context.arc(position, scale(point.y), 3.5, 0, Math.PI * 2); context.fill();
    } else {
      context.fillRect(position, Math.min(scale(point.y), scale(0)), Math.max(3, 800 / values.length), Math.max(1, Math.abs(scale(point.y) - scale(0))));
    }
    if (values.length < 12) context.fillText(point.label, position, 275);
  });
  context.fillStyle = '#29434e';
  context.fillText(high.toFixed(2), 0, 45); context.fillText(low.toFixed(2), 0, 250);
  context.fillText(scatter ? '沿用方法均值 → 候选方法均值（原始定量配对）' : '按表中顺序展示描述值；缺测不绘制为零', 50, 20);
}

function clearNode(node) { node.replaceChildren(); }

function card(title, value, extra) {
  const article = document.createElement('article');
  const span = document.createElement('span'); span.textContent = title;
  const strong = document.createElement('strong'); strong.textContent = displayValue(value);
  article.append(span, strong);
  if (extra) { const note = document.createElement('small'); note.textContent = extra; article.append(note); }
  return article;
}

function drawBiasChart(samples, policy) {
  const canvas = element('bias-chart');
  const context = canvas.getContext('2d');
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.font = '12px sans-serif';
  const points = samples
    .filter(sample => typeof sample.reference_mean === 'number' && typeof sample.difference === 'number')
    .sort((a, b) => a.reference_mean - b.reference_mean);
  if (!points.length) { context.fillStyle = '#667d83'; context.fillText('没有可定量配对，偏差图无证据可绘制', 30, 50); return; }
  const xs = points.map(point => point.reference_mean);
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const toleranceAt = x => policy.absolute + policy.relative * Math.abs(x);
  const bandPoints = points.map(point => toleranceAt(point.reference_mean));
  const biases = points.map(point => point.difference);
  const minY = Math.min(0, ...biases, ...bandPoints.map(value => -value));
  const maxY = Math.max(0, ...biases, ...bandPoints);
  const pad = (maxY - minY) * 0.08 || 1;
  const lowY = minY - pad, highY = maxY + pad;
  const positionX = x => 55 + (x - minX) / (maxX - minX || 1) * 870;
  const positionY = y => 250 - (y - lowY) / (highY - lowY || 1) * 225;

  context.strokeStyle = '#90a5ad';
  context.beginPath(); context.moveTo(55, 20); context.lineTo(55, 250); context.lineTo(925, 250); context.stroke();
  // 零偏差参考线
  context.strokeStyle = '#b8cece'; context.setLineDash([4, 4]);
  context.beginPath(); context.moveTo(55, positionY(0)); context.lineTo(925, positionY(0)); context.stroke();
  context.setLineDash([]);
  // 容许误差带（随读数变化）
  if (policy.verdict_enabled) {
    context.fillStyle = 'rgba(46,155,129,0.12)';
    context.beginPath();
    points.forEach((point, index) => {
      const x = positionX(point.reference_mean), y = positionY(toleranceAt(point.reference_mean));
      index === 0 ? context.moveTo(x, y) : context.lineTo(x, y);
    });
    for (let index = points.length - 1; index >= 0; index -= 1) {
      context.lineTo(positionX(points[index].reference_mean), positionY(-toleranceAt(points[index].reference_mean)));
    }
    context.closePath(); context.fill();
    context.strokeStyle = '#2e9b81'; context.setLineDash([6, 4]);
    context.beginPath();
    points.forEach((point, index) => {
      const x = positionX(point.reference_mean), y = positionY(toleranceAt(point.reference_mean));
      index === 0 ? context.moveTo(x, y) : context.lineTo(x, y);
    });
    context.stroke(); context.setLineDash([]);
  }
  // 偏差点：超限红色，带内绿色
  points.forEach(point => {
    context.beginPath();
    context.fillStyle = point.within_tolerance === false ? '#9c302d' : '#0a7168';
    context.arc(positionX(point.reference_mean), positionY(point.difference), 4, 0, Math.PI * 2);
    context.fill();
  });
  context.fillStyle = '#29434e';
  context.fillText('偏差（候选 − 参考）随参考方法读数变化；绿带为当前容许误差范围，红点为超限配对', 55, 18);
  context.fillStyle = '#667d83';
  context.fillText(minX.toFixed(2), 50, 272); context.fillText(maxX.toFixed(2), 895, 272);
  context.fillText('观测量程：' + minX.toFixed(2) + ' 至 ' + maxX.toFixed(2) + '，区间外不推断', 650, 272);
}

function renderComparison(result) {
  const comp = result.view.comparison;
  const policy = comp.policy;
  element('policy-echo').textContent = '当前误差约定 TEa(x) = ' + displayValue(policy.absolute) +
    ' + ' + displayValue(policy.relative) + ' × |x|' +
    (policy.verdict_enabled ? '' : '（两者均为 0，仅描述，不做合格判定）');

  const cards = element('comparison-cards'); clearNode(cards);
  const coverage = comp.coverage;
  cards.append(
    card('可定量配对', coverage.quantitative_pairs, '其中含检出限复测 ' + coverage.partial_censored_pairs + ' 对'),
    card('Deming 斜率', comp.deming.slope, '1 为无比例偏差；截距 ' + displayValue(comp.deming.intercept)),
    card('平均偏差', comp.bland_altman.mean_bias, '候选 − 参考'),
    card('一致性界限', comp.bland_altman.loa_lower === null ? '不足' :
      displayValue(comp.bland_altman.loa_lower) + ' ~ ' + displayValue(comp.bland_altman.loa_upper), 'mean ± 1.96 SD，非 TEa'),
    card('两方法均低于检出限', coverage.fully_censored_pairs, '量程下端无定量证据'),
    card('仅一侧可定量', coverage.one_sided_censored_pairs, '不能形成配对差值')
  );

  drawBiasChart(comp.samples, policy);

  const notes = element('comparison-notes'); clearNode(notes);
  for (const note of comp.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; notes.append(paragraph);
  }

  // 分箱剖面
  const profileHead = element('profile-table').querySelector('thead');
  const profileBody = element('profile-table').querySelector('tbody');
  clearNode(profileHead); clearNode(profileBody);
  const profileColumns = [
    ['status', '判定'], ['range_low', '量程下限'], ['range_high', '量程上限'], ['n_pairs', '配对数'],
    ['mean_bias', '平均偏差'], ['max_abs_bias', '最大绝对偏差'], ['tolerance_at_center', '箱中心容许误差'],
    ['sample_ids', '支持样品']
  ];
  const headRow = document.createElement('tr');
  for (const [, labelText] of profileColumns) { const th = document.createElement('th'); th.textContent = labelText; headRow.append(th); }
  profileHead.append(headRow);
  for (const binEntry of comp.profile.bins) {
    const row = document.createElement('tr');
    row.className = binEntry.status === '合格' ? 'pass' : binEntry.status === '超限' ? 'fail' : 'weak';
    row.tabIndex = 0;
    for (const [field] of profileColumns) {
      const cell = document.createElement('td');
      cell.textContent = field === 'sample_ids' ? binEntry.sample_ids.join(', ') : displayValue(binEntry[field]);
      row.append(cell);
    }
    row.onclick = () => showSamples(binEntry.sample_ids, '量程箱 ' + binEntry.range_low + '–' + binEntry.range_high);
    row.onkeydown = event => { if (event.key === 'Enter') row.click(); };
    profileBody.append(row);
  }

  // 适用范围与限制
  const applicable = element('applicable'); clearNode(applicable);
  const range = comp.profile.evidence_range;
  const evidence = document.createElement('p');
  evidence.className = 'hint';
  evidence.textContent = range ? ('观测量程 ' + displayValue(range.low) + ' 至 ' + displayValue(range.high) +
    '；超出该范围没有证据，保持空白结论，不向外推断。') : '没有可定量观测量程。';
  applicable.append(evidence);
  const addRangeList = (labelText, items, style) => {
    const block = document.createElement('div'); block.className = 'range-block ' + style;
    const title = document.createElement('strong'); title.textContent = labelText; block.append(title);
    if (!items.length) { const empty = document.createElement('span'); empty.textContent = '无'; block.append(empty); }
    for (const item of items) {
      const chip = document.createElement('button');
      chip.className = 'chip';
      chip.textContent = displayValue(item.range_low) + ' – ' + displayValue(item.range_high) +
        '（' + item.n_pairs + ' 对）';
      chip.onclick = () => showSamples(item.sample_ids, labelText);
      block.append(chip);
    }
    applicable.append(block);
  };
  addRangeList('容许误差内的适用范围', comp.profile.applicable_ranges, 'pass');
  addRangeList('超限限制区间', comp.profile.restricted_bins, 'fail');
  addRangeList('证据不足/无证据区间', comp.profile.insufficient_bins, 'weak');

  // 实验室与批次
  const groupHead = element('group-table').querySelector('thead');
  const groupBody = element('group-table').querySelector('tbody');
  clearNode(groupHead); clearNode(groupBody);
  const groupColumns = [['dimension', '维度'], ['name', '名称'], ['methods_measured', '测过的方法'],
    ['n_samples', '样品数'], ['n_pairs', '配对数'], ['mean_bias', '平均偏差'], ['max_abs_bias', '最大绝对偏差'],
    ['sample_ids', '支持样品']];
  const groupHeadRow = document.createElement('tr');
  for (const [, labelText] of groupColumns) { const th = document.createElement('th'); th.textContent = labelText; groupHeadRow.append(th); }
  groupHead.append(groupHeadRow);
  for (const group of [...comp.lab_groups, ...comp.lot_groups]) {
    const row = document.createElement('tr');
    if (group.only_one_method) row.className = 'weak';
    row.tabIndex = 0;
    for (const [field] of groupColumns) {
      const cell = document.createElement('td');
      cell.textContent = Array.isArray(group[field]) ? group[field].join(', ') : displayValue(group[field]);
      row.append(cell);
    }
    if (group.only_one_method) {
      const cell = document.createElement('td');
      cell.textContent = '仅测过一种方法，不参与配对判定';
      row.append(cell);
    }
    row.onclick = () => showSamples(group.sample_ids, group.dimension + ' ' + group.name);
    row.onkeydown = event => { if (event.key === 'Enter') row.click(); };
    groupBody.append(row);
  }

  // 检出限与单方法
  const censored = element('censored'); clearNode(censored);
  const addCensorList = (labelText, items, renderText) => {
    const block = document.createElement('div'); block.className = 'range-block weak';
    const title = document.createElement('strong'); title.textContent = labelText + '（' + items.length + '）';
    block.append(title);
    for (const item of items) {
      const chip = document.createElement('button'); chip.className = 'chip';
      chip.textContent = renderText(item);
      chip.onclick = () => showSamples([item.sample_id], labelText);
      block.append(chip);
    }
    censored.append(block);
  };
  addCensorList('两方法均低于检出限（不按零值处理）', comp.fully_censored_samples,
    item => item.sample_id + '，limit ≤ ' + displayValue(item.reference_limit));
  addCensorList('仅一侧可定量（不能配对）', comp.one_sided_censored_samples,
    item => item.sample_id + '，' + item.censored_method + ' 低于 ' + displayValue(item.limit));
  addCensorList('只测过一种方法的样品', comp.single_method_samples,
    item => item.sample_id + '（' + item.methods.join(', ') + '）');
}

function showSamples(sampleIds, source) {
  const comp = state.current.view.comparison;
  const details = comp.samples.filter(sample => sampleIds.includes(sample.sample_id));
  element('details').textContent = JSON.stringify({来源: source, 样品依据: details}, null, 2);
  message('已定位到 ' + details.length + ' 个支持样品 · 数据 ' + state.current.revision.slice(0, 12));
}

function render(result, heading) {
  state.current = result;
  element('summary').replaceChildren();
  for (const [label, value] of Object.entries(result.view.summary)) {
    const cardNode = document.createElement('article');
    const title = document.createElement('span'); title.textContent = label;
    const amount = document.createElement('strong'); amount.textContent = displayValue(value);
    cardNode.append(title, amount); element('summary').append(cardNode);
  }
  element('notes').replaceChildren();
  for (const note of result.view.notes) {
    const paragraph = document.createElement('p'); paragraph.textContent = note; element('notes').append(paragraph);
  }
  const rows = result.view.rows;
  const fields = rows.length ? Object.keys(rows[0]) : [];
  const header = document.createElement('tr');
  for (const field of fields) { const cell = document.createElement('th'); cell.textContent = field; header.append(cell); }
  element('columns').replaceChildren(header); element('rows').replaceChildren();
  for (const row of rows) {
    const line = document.createElement('tr'); line.tabIndex = 0;
    for (const field of fields) { const cell = document.createElement('td'); cell.textContent = displayValue(row[field]); line.append(cell); }
    line.onclick = () => {
      const sample = state.current.view.comparison.samples.find(item => item.sample_id === row.sample_id);
      element('details').textContent = JSON.stringify(sample || row, null, 2);
    };
    line.onkeydown = event => { if (event.key === 'Enter') line.click(); };
    element('rows').append(line);
  }
  drawChart(result.view.series);
  renderComparison(result);
  const savedTolerance = result.selection && result.selection.tolerance;
  if (savedTolerance) {
    element('tolerance-absolute').value = savedTolerance.absolute;
    element('tolerance-relative').value = savedTolerance.relative;
  }
  element('details').textContent = JSON.stringify({revision: result.revision, selection: result.selection,
    history: result.view.history || null}, null, 2);
  message((heading || '已更新比较') + ' · 数据 ' + result.revision.slice(0, 12));
}

async function refresh() {
  state.context = await request('/api/context');
  renderControls();
  element('archive').replaceChildren();
  for (const notebook of state.context.notebooks) {
    const button = document.createElement('button'); button.textContent = notebook.title + ' #' + notebook.id;
    button.onclick = () => guarded(async () => {
      const saved = await request('/api/notebooks/' + notebook.id);
      element('revision').value = saved.revision;
      for (const [key, value] of Object.entries(saved.selection)) {
        const control = element('select-' + key); if (control) control.value = value;
      }
      const tolerance = saved.selection.tolerance || {};
      element('tolerance-absolute').value = tolerance.absolute ?? 0;
      element('tolerance-relative').value = tolerance.relative ?? 0;
      render(saved.result, '已读取保存的比较，数据与误差约定均已冻结，不随新数据变化');
    });
    element('archive').append(button);
  }
}

async function inspectCurrent() {
  render(await request('/api/explore', selected()));
}

element('inspect').onclick = () => guarded(inspectCurrent);
element('save').onclick = () => guarded(async () => {
  const saved = await request('/api/notebooks', {...selected(), title: element('title').value});
  await refresh(); render(saved.result, '已保存记录 #' + saved.id);
});
element('raw').onclick = () => guarded(async () => {
  const revision = state.current ? state.current.revision : element('revision').value;
  element('details').textContent = JSON.stringify(await request('/api/data?revision=' + encodeURIComponent(revision)), null, 2);
});
element('upload').onchange = () => guarded(async () => {
  const file = element('upload').files[0]; if (!file) return;
  const data = JSON.parse(await file.text());
  const uploaded = await request('/api/datasets', {label: file.name, data});
  await refresh(); element('revision').value = uploaded.revision;
  render(await request('/api/explore', selected()), '已导入独立数据版本');
});
element('export').onclick = () => guarded(async () => {
  if (!state.current) throw new Error('请先查看一个范围');
  const data = await request('/api/data?revision=' + encodeURIComponent(state.current.revision));
  const blob = new Blob([JSON.stringify({description: state.current, data}, null, 2)], {type: 'application/json'});
  const url = URL.createObjectURL(blob); const link = document.createElement('a');
  link.href = url; link.download = 'analysis-' + state.current.revision.slice(0, 12) + '.json'; link.click();
  URL.revokeObjectURL(url);
});

guarded(async () => {
  await refresh();
  const initialData = await request('/api/data?revision=' + encodeURIComponent(state.context.default_revision));
  const limits = initialData.limits || {};
  element('tolerance-absolute').value = limits.absolute ?? 0;
  element('tolerance-relative').value = limits.relative ?? 0;
  await inspectCurrent();
});
