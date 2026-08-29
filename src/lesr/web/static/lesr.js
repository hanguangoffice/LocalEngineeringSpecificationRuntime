/* LESR human interface: engineering meaning in front, machine identity in audit. */
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const runtimeState = {
  workspaceUid: null, base: null, actor: null,
  configurationUid: null, packageUid: null, approval: null,
  reviewPurpose: null, flowIndex: 0, context: null,
  intakeRequest: null, intakeWorkspace: false, selectedItem: null,
  queryKind: '', baselineTag: '',
  change: {humanKey: '', kind: '', statement: '', reason: ''}, audit: [],
};

const KIND_NAMES = {
  software_requirement: '软件需求', software_design: '软件设计',
  test_case: '测试用例', revision: '工程内容',
  configuration_snapshot: '工程配置',
};
const ROLE_NAMES = {
  technical: '技术负责人', quality: '质量负责人', safety: '安全负责人',
  baseline: '基线批准人',
};
const TASK_NAMES = {
  deep_trace: '深度追踪', validation: '完整校验', migration: '版本升级',
  backup: '工程备份', impact: '影响分析',
};

const motion = (() => {
  const media = gsap.matchMedia();
  let enabled = !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let panelTimeline = null;
  const ease = 'power3.out';
  media.add('(prefers-reduced-motion: reduce)', () => {
    enabled = false;
    gsap.set('.panel.active, .priority-work, .project-glance', {clearProps: 'all'});
    return () => { enabled = true; };
  });
  const animate = (targets, vars) => {
    if (!enabled) {
      gsap.set(targets, {clearProps: 'transform,opacity,visibility'});
      return null;
    }
    gsap.set(targets, {willChange: 'transform,opacity'});
    return gsap.to(targets, {
      ...vars,
      onComplete() {
        gsap.set(targets, {clearProps: 'willChange'});
        if (vars.onComplete) vars.onComplete();
      },
    });
  };
  const boot = () => {
    if (!enabled) return;
    gsap.timeline({defaults: {ease}})
      .from('.masthead > *', {y: -12, autoAlpha: 0, duration: .42, stagger: .06})
      .from('.rail .nav-item', {x: -10, autoAlpha: 0, duration: .28, stagger: .025}, '-=.2')
      .from('#overview .eyebrow, #overview h1, #overview .lede', {
        y: 18, autoAlpha: 0, duration: .48, stagger: .07,
      }, '-=.08')
      .from('.priority-work, .project-glance', {
        y: 16, autoAlpha: 0, duration: .38, stagger: .045,
      }, '-=.25')
      .from('.overview-actions button', {
        y: 12, autoAlpha: 0, duration: .32, stagger: .035,
      }, '-=.18');
  };
  const enterPanel = (panel) => {
    if (panelTimeline) panelTimeline.kill();
    if (!enabled) return;
    const content = panel.querySelectorAll(
      '.section-copy, form, .intake-composer, .intake-result, .explore-workspace, .context-key, .context-result, .change-composer, .review-decision, .review-scope, .sign-zone, .baseline-workflow, .task-toolbar, .task-list, .maintenance-layout, .audit-summary, .audit-section, .human-output'
    );
    panelTimeline = gsap.timeline({defaults: {ease}})
      .fromTo(panel, {autoAlpha: 0}, {autoAlpha: 1, duration: .16})
      .from(panel.querySelectorAll('.eyebrow, h2'), {
        y: 15, autoAlpha: 0, duration: .34, stagger: .045,
      }, 0)
      .from(content, {y: 12, autoAlpha: 0, duration: .32, stagger: .035}, .1);
  };
  const step = (index) => {
    runtimeState.flowIndex = Math.max(runtimeState.flowIndex, index);
  };
  const stateChange = (selector, value, tone = 'normal') => {
    const element = document.querySelector(selector);
    if (!element) return;
    element.textContent = value;
    if (!enabled) return;
    gsap.fromTo(element, {
      y: 5, autoAlpha: 0, color: tone === 'danger' ? '#a74335' : '#1f654b',
    }, {y: 0, autoAlpha: 1, color: '', duration: .36, ease});
  };
  const reveal = (targets) => animate(targets, {
    y: 0, autoAlpha: 1, duration: .32, stagger: .04, ease,
  });
  const flash = (target, color = '#dce9df') => {
    if (!enabled) return;
    gsap.timeline().to(target, {backgroundColor: color, duration: .12})
      .to(target, {backgroundColor: '', duration: .55, ease});
  };
  return {boot, enterPanel, step, stateChange, reveal, flash, version: gsap.version};
})();

window.__LESR_MOTION__ = {
  engine: 'GSAP', version: motion.version,
  semantics: 'orientation-focus-state-confirmation',
};

const create = (tag, className, text) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
};
const toast = (message) => {
  const element = document.querySelector('#toast');
  element.querySelector('span').textContent = message;
  gsap.killTweensOf(element);
  gsap.timeline()
    .to(element, {y: 0, autoAlpha: 1, duration: .28, ease: 'power3.out'})
    .to(element, {y: 18, autoAlpha: 0, duration: .24, ease: 'power2.in'}, '+=2.8');
};
const audit = (action, details) => {
  runtimeState.audit.unshift({time: new Date().toISOString(), action, details});
  runtimeState.audit = runtimeState.audit.slice(0, 30);
  document.querySelector('#audit-output').textContent = JSON.stringify(runtimeState.audit, null, 2);
};

async function api(url, options = {}) {
  const method = options.method || 'GET';
  const headers = {'Accept': 'application/json', ...(options.headers || {})};
  if (method !== 'GET') {
    headers['X-LESR-CSRF'] = csrf;
    headers['Content-Type'] = 'application/json';
  }
  let requestBody = null;
  if (options.body) {
    try { requestBody = JSON.parse(options.body); } catch (_) { requestBody = options.body; }
  }
  const response = await fetch(url, {...options, headers});
  if (response.status === 401) {
    location.href = '/locked';
    throw new Error('会话已锁定');
  }
  const body = await response.json();
  audit(`${method} ${url}`, {request: requestBody, status: response.status, response: body});
  if (!response.ok) {
    const detail = body.detail?.error?.message || body.detail?.message
      || body.error?.message || body.detail;
    throw new Error(typeof detail === 'string' ? detail : '操作没有完成，请查看审计详情。');
  }
  return body;
}

const humanKind = (value) => KIND_NAMES[value]
  || String(value || '工程内容').replaceAll('_', ' ');
const humanRole = (value) => ROLE_NAMES[value]
  || String(value || '批准人').replaceAll('_', ' ');
const selectPanel = (name) => {
  const button = document.querySelector(`.nav-item[data-panel="${name}"]`);
  if (button) button.click();
};
document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
  const current = document.querySelector('.panel.active');
  const panel = document.querySelector(`#${button.dataset.panel}`);
  if (!panel || current === panel) return;
  document.querySelectorAll('.nav-item').forEach((item) => item.classList.remove('active'));
  document.querySelectorAll('.panel').forEach((item) => item.classList.remove('active'));
  button.classList.add('active');
  panel.classList.add('active');
  motion.enterPanel(panel);
  if (panel.id === 'tasks') void loadTasks();
  if (panel.id === 'explore') void loadQuery();
}));
document.querySelectorAll('[data-panel-link]').forEach((link) => link.addEventListener('click', (event) => {
  event.preventDefault(); selectPanel(link.dataset.panelLink);
}));
document.querySelectorAll('[data-go]').forEach((button) => button.addEventListener('click', () => {
  selectPanel(button.dataset.go);
  if (button.dataset.intakeMode) selectIntakeMode(button.dataset.intakeMode);
}));

const selectIntakeMode = (mode) => {
  document.querySelectorAll('[data-intake-tab]').forEach((button) => {
    const active = button.dataset.intakeTab === mode;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
  });
  document.querySelectorAll('[data-intake-view]').forEach((view) => {
    view.hidden = view.dataset.intakeView !== mode;
  });
};
document.querySelectorAll('[data-intake-tab]').forEach((button) => {
  button.addEventListener('click', () => selectIntakeMode(button.dataset.intakeTab));
});

const selectedOption = (selector) => {
  const select = document.querySelector(selector);
  return select?.options[select.selectedIndex] || null;
};
const syncConfiguration = (value) => {
  runtimeState.configurationUid = value;
  document.querySelectorAll('[data-configuration-select]').forEach((select) => {
    if ([...select.options].some((option) => option.value === value)) select.value = value;
  });
  const visible = selectedOption('[data-configuration-select]');
  motion.stateChange('#overview-configuration', visible?.textContent || '尚未选择配置');
  document.querySelector('#overview-configuration-note').textContent = visible?.dataset.note
    || '尚未建立工程配置。';
};
const populateSession = (value) => {
  runtimeState.context = value;
  runtimeState.base = value.audit.canonical_commit;
  motion.stateChange('#project-name', value.project_name || '本地工程');
  document.querySelector('#audit-commit').textContent = value.audit.canonical_commit;
  document.querySelectorAll('[data-configuration-select]').forEach((select) => {
    select.replaceChildren();
    if (!value.configurations.length) {
      const option = create('option', '', '尚无可用配置');
      option.value = ''; option.disabled = true; option.selected = true; select.append(option);
      return;
    }
    value.configurations.forEach((configuration) => {
      const option = create('option', '', configuration.name);
      option.value = configuration.configuration_uid;
      option.dataset.note = configuration.closure_status === 'complete'
        ? `配置完整，包含 ${configuration.change_count} 个已选工程版本。`
        : '配置尚不完整。';
      select.append(option);
    });
    select.onchange = () => syncConfiguration(select.value);
  });
  document.querySelectorAll('[data-actor-select], [data-reviewer-select]').forEach((select) => {
    select.replaceChildren();
    if (!value.actors.length) {
      const option = create('option', '', '尚无已注册的本机用户');
      option.value = ''; option.disabled = true; option.selected = true; select.append(option);
      return;
    }
    value.actors.forEach((actor) => {
      const roles = actor.roles.map(humanRole).join('、');
      const option = create('option', '', `${actor.display_name}${roles ? ` · ${roles}` : ''}`);
      option.value = actor.actor_uid;
      option.dataset.keyUid = actor.key_uid || '';
      option.dataset.roles = JSON.stringify(actor.roles || []);
      select.append(option);
    });
  });
  document.querySelectorAll('[data-kind-select]').forEach((select) => {
    const previous = select.value;
    select.replaceChildren();
    (value.content_types || []).forEach((kind) => {
      const option = create('option', '', kind.name);
      option.value = kind.value; select.append(option);
    });
    if (!select.options.length) {
      const option = create('option', '', '先从需求建立工程内容');
      option.value = ''; option.disabled = true; option.selected = true; select.append(option);
    } else if ([...select.options].some((option) => option.value === previous)) {
      select.value = previous;
    }
    select.onchange = () => suggestEngineeringNumber(false);
  });
  document.querySelectorAll('[data-task-select]').forEach((select) => {
    select.replaceChildren();
    (value.task_types || []).forEach((task) => {
      const option = create('option', '', task.name);
      option.value = task.value; select.append(option);
    });
  });
  renderQueryFilters(value.content_types || []);
  if (value.configurations.length) syncConfiguration(value.configurations[0].configuration_uid);
  const firstActor = value.actors[0];
  if (firstActor && !runtimeState.actor) {
    runtimeState.actor = firstActor.actor_uid;
  }
  suggestEngineeringNumber(false);
  audit('会话上下文已自动解析', value);
};
async function loadSession() {
  try { populateSession(await api('/api/session-context')); }
  catch (error) { toast(error.message); }
}
async function health() {
  try {
    const value = await api('/api/health');
    const authority = value.authority === 'healthy' ? '运行正常' : '需要检查';
    motion.stateChange('#authority-state', authority,
      value.authority === 'healthy' ? 'normal' : 'danger');
    motion.stateChange('#health-canonical', value.canonical === 'VERIFIED' ? '正常' : '需要检查');
    motion.stateChange('#health-projection', value.projection === 'READY' ? '已就绪' : '可按需建立');
    motion.stateChange('#health-manifest', value.manifest.startsWith('1.0') ? '1.0' : '需要检查');
    motion.stateChange('#health-workspaces', String(value.open_workspaces));
    if (value.open_workspaces > 0) {
      motion.stateChange('#overview-priority-title', `继续处理 ${value.open_workspaces} 项变更`);
      document.querySelector('#overview-priority-note').textContent = '查看未完成内容，继续编辑或送审。';
      const primary = document.querySelector('.priority-primary');
      primary.textContent = '继续处理';
      primary.dataset.go = 'workspace';
      delete primary.dataset.intakeMode;
    }
  } catch (error) { toast(error.message); }
}

const INTAKE_CATEGORY_NAMES = {
  goal: '目标', function: '功能', quality: '质量要求', constraint: '约束',
  test: '测试与验收', deliverable: '交付内容', dependency: '外部依赖', safety: '操作约束',
};

const renderIntake = (value) => {
  const result = document.querySelector('#intake-result');
  result.hidden = false;
  motion.stateChange('#intake-pack', value.selected_pack.display_name);
  document.querySelector('#intake-pack-summary').textContent = value.selected_pack.summary;
  motion.stateChange('#intake-count', `${value.requirements.length} 项`);
  const unresolved = value.gaps.filter((gap) => ['blocking', 'needs_decision'].includes(gap.disposition));
  motion.stateChange('#intake-question-count', `${unresolved.length} 项`);

  const requirements = document.querySelector('#intake-requirements');
  requirements.replaceChildren();
  const groups = new Map();
  value.requirements.slice(0, 100).forEach((item) => {
    if (!groups.has(item.category)) groups.set(item.category, []);
    groups.get(item.category).push(item);
  });
  groups.forEach((items, category) => {
    const group = create('section', 'intake-group');
    const heading = create('header');
    heading.append(
      create('h4', '', INTAKE_CATEGORY_NAMES[category] || '工程内容'),
      create('span', '', `${items.length} 项`),
    );
    group.append(heading);
    items.forEach((item) => {
      const row = create('article', 'intake-requirement');
      row.append(create('b', '', item.human_key), create('p', '', item.statement));
      group.append(row);
    });
    requirements.append(group);
  });
  const reasons = document.querySelector('#intake-reasons');
  reasons.replaceChildren(...value.selection_reasons.map((reason) => create('p', '', reason)));
  const question = document.querySelector('#intake-question');
  question.replaceChildren();
  question.hidden = !value.next_question;
  if (value.next_question) {
    question.append(
      create('b', '', value.next_question.question),
      create('p', '', `推荐：${value.next_question.recommended_answer}`),
      create('p', '', value.next_question.consequence),
    );
  }
  gsap.set(result, {y: 14, autoAlpha: 0});
  motion.reveal(result);
  requestAnimationFrame(() => {
    const top = result.getBoundingClientRect().top + window.scrollY - 108;
    window.scrollTo({
      top: Math.max(0, top),
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
    });
  });
};

document.querySelector('#intake-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  runtimeState.intakeRequest = {
    description: String(data.description || '').trim(),
    project_name: String(data.project_name || '').trim() || null,
    known_repository: String(data.known_repository || '').trim() || null,
  };
  try {
    const value = await api('/api/intake/analyze', {
      method: 'POST', body: JSON.stringify(runtimeState.intakeRequest),
    });
    renderIntake(value);
    audit('自然语言需求已按固定上游模板整理', value);
    toast('工程内容已整理。');
  } catch (error) { toast(error.message); }
});

const fileAsBase64 = (file) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onerror = () => reject(new Error('文件读取失败。'));
  reader.onload = () => resolve(String(reader.result).split(',', 2)[1] || '');
  reader.readAsDataURL(file);
});

document.querySelector('#intake-import-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  const file = data.get('spec_file');
  if (!(file instanceof File) || !file.name) return toast('请选择规范文件。');
  try {
    const value = await api('/api/intake/import-preview', {
      method: 'POST', body: JSON.stringify({
        filename: file.name,
        content_base64: await fileAsBase64(file),
        project_name: String(data.get('project_name') || '').trim() || null,
        known_repository: String(data.get('known_repository') || '').trim() || null,
      }),
    });
    runtimeState.intakeRequest = {
      description: value.description,
      project_name: String(data.get('project_name') || '').trim() || null,
      known_repository: String(data.get('known_repository') || '').trim() || null,
    };
    renderIntake(value.analysis);
    toast(`已读取 ${value.source.filename}。`);
  } catch (error) { toast(error.message); }
});

document.querySelector('#intake-accept-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.intakeRequest) return toast('请先分析需求。');
  try {
    const value = await api('/api/intake/accept', {
      method: 'POST', body: JSON.stringify({
        ...runtimeState.intakeRequest,
      }),
    });
    runtimeState.workspaceUid = value.workspace_uid;
    runtimeState.base = value.base_commit;
    runtimeState.actor = value.actor_uid;
    runtimeState.configurationUid = value.configuration_uid;
    runtimeState.intakeWorkspace = true;
    runtimeState.change.humanKey = value.requirement_count === 1
      ? value.human_keys[0] : `初始规格（${value.requirement_count} 项）`;
    runtimeState.change.kind = 'software_requirement';
    runtimeState.change.reason = '从自然语言需求建立初始工程规格';
    await loadSession();
    runtimeState.actor = value.actor_uid;
    runtimeState.configurationUid = value.configuration_uid;
    const changeForm = document.querySelector('#workspace-compose-form');
    changeForm.querySelector('[name="human_key"]').value = value.human_keys[0] || 'REQ-SW-0001';
    const intakeKind = changeForm.querySelector('[name="kind"]');
    if ([...intakeKind.options].some((option) => option.value === 'software_requirement')) {
      intakeKind.value = 'software_requirement';
    }
    changeForm.querySelector('[name="statement"]').value
      = `已从需求整理 ${value.requirement_count} 项初始工程内容。`;
    changeForm.querySelector('[name="change_reason"]').value
      = '从自然语言需求建立初始工程规格';
    const scope = document.querySelector('#workspace-scope');
    scope.querySelector('strong').textContent = `${value.requirement_count} 项初始工程内容`;
    scope.querySelector('p').textContent = value.human_keys.join('、');
    const workspaceOutput = document.querySelector('#workspace-output');
    workspaceOutput.hidden = false;
    workspaceOutput.replaceChildren(create('p', '',
      `已采用“${value.selected_template}”建立可编辑草案。请检查内容，然后送审。`));
    advanceWorkspace('草案已建立', `${value.requirement_count} 项内容可以继续编辑。`, .66);
    motion.step(0);
    audit('零规范需求已转入工程工作区', value);
    selectPanel('workspace');
    toast('工程草案已经建立。');
  } catch (error) { toast(error.message); }
});

const statementOf = (item) => {
  const field = (item.fields || item.draft_fields || [])
    .find((entry) => entry.path === '/statement');
  return typeof field?.value === 'string' ? field.value : '';
};
const itemUid = (item) => item.object_uid || item.revision_uid
  || item.entity_uid || item.uid || '';
const suggestEngineeringNumber = (force) => {
  const kind = document.querySelector('#workspace-compose-form [name="kind"]')?.value;
  const input = document.querySelector('#workspace-compose-form [name="human_key"]');
  const suggestion = runtimeState.context?.key_suggestions?.[kind];
  if (input && suggestion && (force || !input.value.trim())) input.value = suggestion;
};
const renderQueryFilters = (contentTypes) => {
  const filters = document.querySelector('#query-filters');
  filters.replaceChildren();
  [{value: '', name: '全部内容'}, ...contentTypes].forEach((kind) => {
    const button = create('button', '', kind.name);
    button.type = 'button'; button.dataset.kind = kind.value;
    button.classList.toggle('active', kind.value === runtimeState.queryKind);
    button.addEventListener('click', () => {
      runtimeState.queryKind = kind.value;
      filters.querySelectorAll('button').forEach((item) => {
        item.classList.toggle('active', item === button);
      });
      void loadQuery();
    });
    filters.append(button);
  });
};
const selectQueryItem = (item, row) => {
  runtimeState.selectedItem = item;
  document.querySelectorAll('.result-item').forEach((element) => {
    element.removeAttribute('aria-current');
  });
  row.setAttribute('aria-current', 'true');
  document.querySelector('#spec-preview-key').textContent = item.human_key || '未命名';
  document.querySelector('#spec-preview-kind').textContent
    = `${humanKind(item.kind || item.resource_type)}${item.workspace_draft ? ' · 编辑中' : ''}`;
  document.querySelector('#spec-preview-statement').textContent
    = statementOf(item) || '这项内容还没有正文摘要。';
  document.querySelector('#context-form [name="target_key"]').value = item.human_key || '';
  const form = document.querySelector('#workspace-compose-form');
  form.querySelector('[name="human_key"]').value = item.human_key || '';
  const kind = form.querySelector('[name="kind"]');
  if ([...kind.options].some((option) => option.value === item.kind)) kind.value = item.kind;
  form.querySelector('[name="statement"]').value = statementOf(item);
  updateChangePreview();
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    gsap.fromTo('#graph-core, #spec-preview-statement, .preview-next',
      {y: 9, autoAlpha: 0},
      {y: 0, autoAlpha: 1, duration: .34, stagger: .055, ease: 'power3.out'});
  }
  audit('选择工程内容', item);
};
const loadQuery = async () => {
  const form = document.querySelector('#query-form');
  const text = String(new FormData(form).get('text') || '').trim();
  try {
    const value = await api(`/api/query?text=${encodeURIComponent(text)}&kind=${encodeURIComponent(runtimeState.queryKind)}`);
    const results = document.querySelector('#query-results');
    results.replaceChildren();
    document.querySelector('#query-result-count').textContent = value.items.length
      ? `${value.items.length} 项内容` : '没有匹配内容';
    const suggestions = document.querySelector('#engineering-content-suggestions');
    suggestions.replaceChildren();
    value.items.forEach((item) => {
      const row = create('button', 'result-item');
      row.type = 'button'; row.dataset.uid = itemUid(item);
      row.append(create('b', '', item.human_key || '未命名工程内容'),
        create('span', '', `${humanKind(item.kind || item.resource_type)}${item.workspace_draft ? ' · 编辑中' : ''}`),
        create('p', '', statementOf(item) || '尚无正文摘要。'));
      row.addEventListener('click', () => selectQueryItem(item, row));
      results.append(row);
      if (item.human_key) {
        const option = create('option'); option.value = item.human_key; suggestions.append(option);
      }
    });
    if (!value.items.length) {
      const empty = create('div', 'empty-state');
      empty.append(create('b', '', text ? `没有找到“${text}”` : '工程中还没有可查找的内容。'));
      const action = create('button', 'text-action', text ? '清除搜索' : '从需求开始');
      action.type = 'button'; action.addEventListener('click', () => {
        if (text) { form.reset(); void loadQuery(); } else selectPanel('intake');
      });
      empty.append(action); results.append(empty);
    }
    else {
      gsap.set(results.children, {y: 12, autoAlpha: 0}); motion.reveal(results.children);
      selectQueryItem(value.items[0], results.firstElementChild);
    }
  } catch (error) { toast(error.message); }
};
let queryTimer = null;
document.querySelector('#query-form').addEventListener('submit', (event) => {
  event.preventDefault(); void loadQuery();
});
document.querySelector('#query-form [name="text"]').addEventListener('input', () => {
  window.clearTimeout(queryTimer);
  queryTimer = window.setTimeout(() => void loadQuery(), 280);
});
const resolveHumanKey = async (humanKey) => {
  const query = await api(`/api/query?text=${encodeURIComponent(humanKey)}`);
  const exact = query.items.find((item) => String(item.human_key || '').toLocaleLowerCase()
    === humanKey.toLocaleLowerCase());
  if (!exact) throw new Error(`没有找到工程编号“${humanKey}”。`);
  return exact;
};
const renderContext = (value, targetKey) => {
  const output = document.querySelector('#context-output');
  output.replaceChildren();
  const complete = value.completeness === 'COMPLETE';
  const status = complete ? '资料已备齐' : '资料仍有缺口';
  const grid = create('div', 'context-summary');
  grid.dataset.complete = String(complete);
  [['整理结果', status, 'context-status'],
    ['必须阅读', `${(value.mandatory || []).length} 项`, ''],
    ['建议参考', `${(value.supporting || []).length} 项`, '']].forEach(([label, result, className]) => {
    const card = create('article');
    if (className) card.className = className;
    card.append(create('small', '', label), create('strong', '', result)); grid.append(card);
  });
  const explanations = {
    INCOMPLETE_MISSING_RELATION: '缺少完成这项工作所需的关系，请先补充关联内容。',
    INCOMPLETE_BUDGET: '必读资料超出本次读取范围，可以继续进行深度追踪。',
    INCOMPLETE_CONFIGURATION: '当前工程配置不完整，请先选择或补全配置。',
    INCOMPLETE_CONFLICT: '当前配置存在冲突，解决后才能得到完整资料。',
    INCOMPLETE_CONFIDENTIALITY: '部分必读资料受访问限制，当前结果并不完整。',
  };
  output.append(grid, create('p', 'context-explanation', complete
    ? `${targetKey} 的必读资料已经整理完成，可以开始工作。`
    : `${targetKey} 已整理现有资料。${explanations[value.completeness] || '仍有内容无法确定。'}`));
  const materials = create('div', 'context-materials');
  const materialSection = (title, items, tone) => {
    const section = create('section', tone);
    const heading = create('header');
    heading.append(create('h3', '', title), create('span', '', `${items.length} 项`));
    section.append(heading);
    if (!items.length) {
      section.append(create('p', 'context-empty', title === '必须阅读'
        ? '没有解析到必读内容。' : '当前没有额外参考内容。'));
    } else {
      items.forEach((item) => {
        const row = create('article');
        row.append(create('b', '', item.human_key), create('span', '', humanKind(item.kind)));
        section.append(row);
      });
    }
    return section;
  };
  materials.append(
    materialSection('必须阅读', value.mandatory_items || [], 'mandatory-materials'),
    materialSection('建议参考', value.supporting_items || [], 'supporting-materials'),
  );
  output.append(materials);
  if (!complete) output.append(create('p', 'context-gaps',
    explanations[value.completeness] || '当前资料不完整，请先处理缺口。'));
  gsap.set(output.children, {y: 12, autoAlpha: 0});
  motion.reveal(output.children);
};
document.querySelector('#context-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const target = await resolveHumanKey(String(data.target_key));
    const value = await api('/api/context/plan', {
      method: 'POST', body: JSON.stringify({
        configuration_uid: data.configuration_uid, target_uid: itemUid(target),
        task_type: data.task_type, evaluation_time: new Date().toISOString(),
      }),
    });
    renderContext(value, String(data.target_key));
  } catch (error) { toast(error.message); }
});

const uid = () => {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let milliseconds = BigInt(Date.now());
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(milliseconds & 0xffn); milliseconds >>= 8n;
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x70; bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};
const envelope = (operation, overrides = {}) => ({
  workspace_uid: runtimeState.workspaceUid || overrides.workspaceUid || uid(),
  expected_base: runtimeState.base || overrides.base, idempotency_key: uid(),
  actor: runtimeState.actor || overrides.actor,
  dry_run: false, operation,
});
const advanceWorkspace = (state, guidance, progress) => {
  motion.stateChange('#workspace-state', state);
  document.querySelector('#workspace-guidance').textContent = guidance;
  gsap.to('#workspace-progress', {scaleX: progress, duration: .5, ease: 'power2.inOut'});
};
const updateChangePreview = () => {
  const form = document.querySelector('#workspace-compose-form');
  const data = Object.fromEntries(new FormData(form));
  const key = String(data.human_key || '').trim();
  const statement = String(data.statement || '').trim();
  const reason = String(data.change_reason || '').trim();
  const scope = document.querySelector('#workspace-scope');
  scope.querySelector('strong').textContent = key || '等待填写';
  scope.querySelector('p').textContent = key
    ? `${humanKind(data.kind)}${reason ? ` · ${reason}` : ''}` : '工程编号和内容类型会在这里汇总。';
  if (key && statement && reason) advanceWorkspace('可以送审', '内容和理由已经填写。', .72);
  else advanceWorkspace('准备填写', '完成内容后即可送审。', key || statement || reason ? .35 : 0);
};
document.querySelector('#workspace-compose-form').addEventListener('input', updateChangePreview);
document.querySelector('#workspace-compose-form').addEventListener('change', updateChangePreview);
const paintDecision = (validation) => {
  const decision = validation.operation_decision || {};
  const blocking = (decision.blocking_finding_uids || []).length;
  const findings = (validation.findings || validation.finding_hashes || []).length;
  const strip = document.querySelector('#decision-strip');
  if (!strip) return;
  strip.dataset.disposition = decision.disposition || (blocking ? 'block' : 'allow');
  strip.querySelector('strong').textContent = blocking ? '需要先处理' : '可以进入批准';
  strip.querySelector('small').textContent = blocking
    ? `发现 ${blocking} 项会阻止保存的问题。`
    : findings ? `有 ${findings} 项提示可供审阅。` : '校验通过。';
  motion.flash(strip, blocking ? '#f3ded9' : '#dce9df');
};
const findExistingItem = async (humanKey) => {
  if (runtimeState.selectedItem?.human_key?.toLocaleLowerCase() === humanKey.toLocaleLowerCase()) {
    return runtimeState.selectedItem;
  }
  const query = await api(`/api/query?text=${encodeURIComponent(humanKey)}`);
  return query.items.find((item) => String(item.human_key || '').toLocaleLowerCase()
    === humanKey.toLocaleLowerCase()) || null;
};
const openChangeWorkspace = async (data, actorOption) => {
  runtimeState.workspaceUid = uid(); runtimeState.actor = String(data.actor);
  runtimeState.configurationUid = String(data.configuration_uid);
  const value = await api('/api/workspace/open', {
    method: 'POST', body: JSON.stringify(envelope({
      type: 'open_workspace', configuration_uid: data.configuration_uid,
    })),
  });
  runtimeState.workspaceUid = value.workspace_uid;
  audit('工作副本已建立', value);
};
const saveChangeContent = async (data) => {
  runtimeState.change = {humanKey: String(data.human_key), kind: String(data.kind),
    statement: String(data.statement), reason: String(data.change_reason)};
  const existing = await findExistingItem(runtimeState.change.humanKey);
  const operation = {
    operation_type: 'create_object',
    working_copy: {
      workspace_uid: runtimeState.workspaceUid,
      object_uid: existing?.object_uid || uid(),
      base_revision_uid: existing?.revision_uid || null,
      base_revision_number: Number(existing?.revision_number || 0),
      human_key: runtimeState.change.humanKey, kind: runtimeState.change.kind,
      facets: existing?.facets || [], effective_model_hash: 'bound-by-runtime',
      draft_fields: [{path: '/statement', value: runtimeState.change.statement}],
      draft_fragments: existing?.fragments || [], relation_proposals: [], edit_log: [],
    },
  };
  const value = await api('/api/workspace/edit', {
    method: 'POST', body: JSON.stringify(envelope(operation)),
  });
  const scope = document.querySelector('#workspace-scope');
  scope.querySelector('strong').textContent = runtimeState.change.humanKey;
  scope.querySelector('p').textContent = `${humanKind(runtimeState.change.kind)} · ${runtimeState.change.reason}`;
  audit('变更内容已保存', value);
};

const renderReview = (value) => {
  const reason = runtimeState.reviewPurpose === 'baseline'
    ? '确认当前完整配置可以作为正式工程基线发布。'
    : runtimeState.change.reason || value.approval_reason;
  motion.stateChange('#review-reason', reason);
  const scope = document.querySelector('#sign-scope'); scope.replaceChildren();
  (value.scope_items || []).forEach((item) => {
    scope.append(create('span', '', `${item.human_key} · ${humanKind(item.kind)}`));
  });
  if (!scope.children.length) scope.append(create('span', '', '当前完整工程配置'));
  motion.stateChange('#review-validation', value.blocking_count ? '需要先处理' : '可以批准',
    value.blocking_count ? 'danger' : 'normal');
  document.querySelector('#review-findings').textContent = value.blocking_count
    ? `${value.blocking_count} 项问题会阻止保存。`
    : value.finding_count ? `有 ${value.finding_count} 项提示可供审阅。`
      : '校验通过。';
  const stages = value.stages || [];
  const roleNames = stages.map((stage) => {
    return humanRole(stage.role);
  }).join('、') || '批准人';
  document.querySelector('#sign-form [name="role"]').value = stages[0]?.role || '';
  motion.stateChange('#sign-role', roleNames);
  motion.stateChange('#sign-role-inline', roleNames);
  document.querySelector('#sign-form [name="package_uid"]').value = value.package_uid;
  document.querySelector('#sign-form [name="human_confirm"]').checked = false;
  document.querySelector('#approve-and-apply').textContent = runtimeState.reviewPurpose === 'baseline'
    ? '批准并发布基线' : '批准并写入工程';
  document.querySelector('#sign-output').classList.remove('is-ready');
  document.querySelector('#sign-output span').textContent = '等待批准。';
  audit('审阅摘要已加载', value);
};
const loadReviewPackage = async (packageUid) => {
  renderReview(await api(`/api/review-package/${encodeURIComponent(packageUid)}`));
};
const assessChangeWorkspace = async () => {
  const value = await api('/api/workspace/validate', {
    method: 'POST', body: JSON.stringify({
      workspace_uid: runtimeState.workspaceUid,
      evaluation_time: new Date().toISOString(), maximum_depth: 3,
    }),
  });
  const disposition = value.decision?.disposition || 'BLOCK';
  const state = disposition === 'HUMAN_DECISION_NOW' ? '需要决定'
    : disposition === 'BLOCK' ? '正在修正' : '检查通过';
  const guidance = disposition === 'HUMAN_DECISION_NOW'
    ? '存在需要你选择的工程取舍。'
    : disposition === 'BLOCK'
      ? '代理将根据校验结论继续修正。'
      : '变更仍可继续编辑，代理可进入下一项工作。';
  advanceWorkspace(state, guidance, disposition === 'BLOCK' ? .65 : 1);
  paintDecision(value.validation);
  document.querySelector('#workspace-output').replaceChildren(create('p', '',
    `${runtimeState.change.humanKey} 已完成后台评估。`));
  audit('工作副本评估完成', value);
};
document.querySelector('#workspace-compose-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = Object.fromEntries(new FormData(form));
  const actorOption = selectedOption('#workspace-compose-form [name="actor"]');
  if (!data.configuration_uid || !data.actor || !actorOption) {
    return toast('当前工程还没有可用的配置和操作人。');
  }
  const button = form.querySelector('button[type="submit"], button:not([type])');
  button.disabled = true; button.textContent = '正在检查…';
  try {
    if (!runtimeState.intakeWorkspace) {
      await openChangeWorkspace(data, actorOption);
      await saveChangeContent(data);
    }
    await assessChangeWorkspace();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false; button.textContent = '评估变更';
  }
});
const addResultConfiguration = (uidValue) => {
  document.querySelectorAll('[data-configuration-select]').forEach((select) => {
    if (![...select.options].some((option) => option.value === uidValue)) {
      const option = create('option', '', '应用后的配置');
      option.value = uidValue; option.dataset.note = '包含刚刚批准并写入的工程变更。';
      select.append(option);
    }
    select.value = uidValue;
  });
  syncConfiguration(uidValue);
};
const applyApprovedCandidate = async () => {
  const value = await api('/api/apply', {
    method: 'POST', body: JSON.stringify(envelope({
      review_package_uid: runtimeState.packageUid,
      signed_approvals: [runtimeState.approval], evaluation_time: new Date().toISOString(),
    })),
  });
  runtimeState.base = value.result_commit;
  runtimeState.configurationUid = value.configuration_uid;
  runtimeState.approval = null; runtimeState.workspaceUid = null;
  addResultConfiguration(value.configuration_uid);
  document.querySelector('#sign-output span').textContent
    = `${runtimeState.change.humanKey} 已写入工程。`;
  motion.step(3); audit('批准的变更已写入工程', value);
  toast('变更已经写入工程。');
};
const applyApprovedBaseline = async () => {
  const value = await api('/api/baseline/apply', {
    method: 'POST', body: JSON.stringify(envelope({
      review_package_uid: runtimeState.packageUid,
      signed_approvals: [runtimeState.approval], evaluation_time: new Date().toISOString(),
      tag_name: runtimeState.baselineTag || null,
    })),
  });
  runtimeState.base = value.result_commit; runtimeState.approval = null;
  motion.stateChange('#baseline-state', '已发布');
  document.querySelector('#baseline-guidance').textContent = '当前配置已经成为正式工程基线。';
  document.querySelector('#baseline-output').replaceChildren(create('p', '',
    runtimeState.baselineTag
      ? `基线“${runtimeState.baselineTag}”已发布。` : '工程基线已发布。'));
  audit('工程基线已发布', value); toast('基线已经发布。'); selectPanel('baseline');
};
document.querySelector('#sign-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.packageUid) return toast('当前没有待批准事项。');
  const data = Object.fromEntries(new FormData(event.target));
  const reviewer = selectedOption('#sign-form [name="reviewer"]');
  const button = document.querySelector('#approve-and-apply');
  button.disabled = true; button.textContent = '正在完成…';
  try {
    const value = await api('/api/sign', {
      method: 'POST', body: JSON.stringify({package_uid: runtimeState.packageUid,
        actor_uid: data.reviewer, key_uid: reviewer?.dataset.keyUid,
        role: data.role, human_confirm: data.human_confirm === 'on'}),
    });
    runtimeState.approval = value.approval;
    const output = document.querySelector('#sign-output'); output.classList.add('is-ready');
    output.querySelector('span').textContent = '批准完成，正在写入…';
    motion.step(2); motion.flash('.sign-zone', '#274a3d'); audit('人工批准已签名', value);
    if (runtimeState.reviewPurpose === 'baseline') await applyApprovedBaseline();
    else await applyApprovedCandidate();
  } catch (error) {
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = runtimeState.reviewPurpose === 'baseline'
      ? '批准并发布基线' : '批准并写入工程';
  }
});

document.querySelector('#baseline-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const actorOption = selectedOption('#workspace-compose-form [name="actor"]');
  if (!runtimeState.actor && actorOption?.value) {
    runtimeState.actor = actorOption.value;
  }
  if (!runtimeState.actor) {
    return toast('当前工程缺少可用的本机身份。');
  }
  try {
    runtimeState.configurationUid = String(data.configuration_uid);
    runtimeState.baselineTag = String(data.tag_name || '').trim();
    runtimeState.workspaceUid = uid();
    const value = await api('/api/baseline/prepare', {
      method: 'POST', body: JSON.stringify(envelope({
        configuration_uid: data.configuration_uid, evaluation_time: new Date().toISOString(),
      })),
    });
    runtimeState.packageUid = value.review_package.package_uid;
    runtimeState.reviewPurpose = 'baseline'; runtimeState.approval = null;
    motion.stateChange('#baseline-state', '等待批准');
    document.querySelector('#baseline-guidance').textContent = '内容已检查，正在进入批准。';
    document.querySelector('#baseline-output').replaceChildren(create('p', '',
      '发布内容已经汇总。'));
    await loadReviewPackage(runtimeState.packageUid); selectPanel('review');
  } catch (error) { toast(error.message); }
});

const loadTasks = async () => {
  try {
    const value = await api('/api/tasks');
    const list = document.querySelector('#task-results'); list.replaceChildren();
    value.forEach((task) => {
      const card = create('article', 'task-card');
      card.append(create('b', '', TASK_NAMES[task.task_type] || humanKind(task.task_type)),
        create('span', '', `${task.state === 'complete' ? '已完成' : '处理中'} · ${task.progress}%`),
        create('i'));
      card.querySelector('i').style.setProperty('--progress', String(task.progress / 100));
      list.append(card);
    });
    if (!value.length) list.append(create('div', 'empty-state', '目前没有后台任务。'));
    gsap.set(list.children, {y: 10, autoAlpha: 0}); motion.reveal(list.children);
  } catch (error) { toast(error.message); }
};
document.querySelector('#refresh-tasks').addEventListener('click', loadTasks);
document.querySelector('#gc-plan').addEventListener('click', async () => {
  try {
    const value = await api('/api/maintenance/gc', {method: 'POST', body: '{}'});
    document.querySelector('#maintenance-output').replaceChildren(create('p', '',
      `清理清单包含 ${(value.candidates || value.removable_refs || []).length} 项。`));
  } catch (error) { toast(error.message); }
});
document.querySelector('#lock-button').addEventListener('click', async () => {
  await api('/api/lock', {method: 'POST', body: '{}'}); location.href = '/locked';
});

motion.boot();
Promise.all([loadSession(), health()]);
