/* LESR human interface: engineering meaning in front, machine identity in audit. */
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const runtimeState = {
  workspaceUid: null, base: null, actor: null, delegationUid: null,
  configurationUid: null, packageUid: null, approval: null,
  reviewPurpose: null, flowIndex: 0, context: null,
  intakeRequest: null,
  change: {humanKey: '', kind: '', statement: '', reason: ''}, audit: [],
};

const KIND_NAMES = {
  software_requirement: '软件需求', software_design: '软件设计',
  test_case: '测试用例', can_signal: 'CAN 信号', revision: '工程内容',
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
    gsap.set('.panel.active, .metric, .flow-step', {clearProps: 'all'});
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
      .from('.current-config-card, .metric', {
        y: 16, autoAlpha: 0, duration: .38, stagger: .045,
      }, '-=.25')
      .from('.quick-actions button, .flow-step', {
        y: 12, autoAlpha: 0, duration: .32, stagger: .035,
      }, '-=.18');
  };
  const enterPanel = (panel) => {
    if (panelTimeline) panelTimeline.kill();
    if (!enabled) return;
    const content = panel.querySelectorAll(
      '.section-copy, form, .intake-layout, .intake-result, .explore-grid, .workspace-layout, .review-grid, .human-output, .maintenance-grid, .task-list, .audit-banner, .audit-facts, .audit-output'
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
    const steps = [...document.querySelectorAll('.flow-step')];
    steps.forEach((element, position) => {
      element.classList.toggle('active', position <= runtimeState.flowIndex);
    });
    const progress = runtimeState.flowIndex / Math.max(1, steps.length - 1);
    animate('#flow-track', {scaleX: progress, duration: .55, ease: 'power2.inOut'});
    if (steps[index] && enabled) {
      gsap.fromTo(steps[index].querySelector('i'), {scale: .78}, {
        scale: 1, duration: .42, ease: 'back.out(1.8)',
      });
    }
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
  const configureGraph = () => {
    const stage = document.querySelector('#graph-stage');
    const core = document.querySelector('#graph-core');
    if (!enabled || !stage || !core) return;
    const xTo = gsap.quickTo(core, 'x', {duration: .42, ease});
    const yTo = gsap.quickTo(core, 'y', {duration: .42, ease});
    stage.addEventListener('pointermove', (event) => {
      const bounds = stage.getBoundingClientRect();
      xTo(((event.clientX - bounds.left) / bounds.width - .5) * 14);
      yTo(((event.clientY - bounds.top) / bounds.height - .5) * 14);
    });
    stage.addEventListener('pointerleave', () => { xTo(0); yTo(0); });
  };
  return {boot, enterPanel, step, stateChange, reveal, flash, configureGraph, version: gsap.version};
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
}));
document.querySelectorAll('[data-panel-link]').forEach((link) => link.addEventListener('click', (event) => {
  event.preventDefault(); selectPanel(link.dataset.panelLink);
}));
document.querySelectorAll('[data-go]').forEach((button) => button.addEventListener('click', () => {
  selectPanel(button.dataset.go);
}));

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
    || '系统会在后台解析对应的精确版本。';
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
        : '配置尚不完整，系统会在操作前明确提示缺口。';
      select.append(option);
    });
    select.addEventListener('change', () => syncConfiguration(select.value));
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
      option.dataset.delegationUid = actor.delegation_uid || '';
      option.dataset.roles = JSON.stringify(actor.roles || []);
      select.append(option);
    });
  });
  if (value.configurations.length) syncConfiguration(value.configurations[0].configuration_uid);
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
    document.querySelectorAll('.metric').forEach((metric) => metric.classList.add('is-live'));
  } catch (error) { toast(error.message); }
}

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
  value.requirements.slice(0, 100).forEach((item) => {
    const row = create('article', 'intake-requirement');
    row.append(create('b', '', item.human_key), create('p', '', item.statement));
    requirements.append(row);
  });
  const reasons = document.querySelector('#intake-reasons');
  reasons.replaceChildren(...value.selection_reasons.map((reason) => create('p', '', reason)));
  const question = document.querySelector('#intake-question');
  question.replaceChildren();
  if (value.next_question) {
    question.append(
      create('b', '', value.next_question.question),
      create('p', '', `推荐：${value.next_question.recommended_answer}`),
      create('p', '', value.next_question.consequence),
    );
  } else {
    question.append(
      create('b', '', '没有阻止建立草案的问题'),
      create('p', '', '可确定内容已由系统整理；其余非阻断项采用模板中的保守默认值。'),
    );
  }
  gsap.set(result, {y: 14, autoAlpha: 0});
  motion.reveal(result);
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
    toast('需求已整理，可以检查后建立工程草案。');
  } catch (error) { toast(error.message); }
});

document.querySelector('#intake-accept-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.intakeRequest) return toast('请先分析需求。');
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/intake/accept', {
      method: 'POST', body: JSON.stringify({
        ...runtimeState.intakeRequest,
        display_name: String(data.display_name || '本机工程所有者'),
        human_confirm: data.human_confirm === 'on',
        accept_recommended: true,
      }),
    });
    runtimeState.workspaceUid = value.workspace_uid;
    runtimeState.base = value.base_commit;
    runtimeState.actor = value.actor_uid;
    runtimeState.delegationUid = value.delegation_uid;
    runtimeState.configurationUid = value.configuration_uid;
    runtimeState.change.humanKey = value.requirement_count === 1
      ? value.human_keys[0] : `初始规格（${value.requirement_count} 项）`;
    runtimeState.change.kind = 'software_requirement';
    runtimeState.change.reason = '从自然语言需求建立初始工程规格';
    await loadSession();
    runtimeState.actor = value.actor_uid;
    runtimeState.delegationUid = value.delegation_uid;
    runtimeState.configurationUid = value.configuration_uid;
    const scope = document.querySelector('#workspace-scope');
    scope.querySelector('strong').textContent = `${value.requirement_count} 项初始工程内容`;
    scope.querySelector('p').textContent = value.human_keys.join('、');
    document.querySelector('#workspace-output').replaceChildren(create('p', '',
      `已采用“${value.selected_template}”建立可编辑草案。请检查内容，然后送审。`));
    advanceWorkspace('草案已建立', '模板、身份、配置和 Human Key 已由系统处理。', .66);
    motion.step(0);
    audit('零规范需求已转入工程工作区', value);
    selectPanel('workspace');
    toast('工程草案已经建立。');
  } catch (error) { toast(error.message); }
});

const statementOf = (item) => {
  const field = (item.fields || []).find((entry) => entry.path === '/statement');
  return typeof field?.value === 'string' ? field.value : '';
};
const itemUid = (item) => item.object_uid || item.revision_uid
  || item.entity_uid || item.uid || '';
document.querySelector('#query-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = String(new FormData(event.target).get('text') || '').trim();
  if (!text) return toast('请输入 Human Key 或关键词。');
  try {
    const value = await api(`/api/query?text=${encodeURIComponent(text)}`);
    const results = document.querySelector('#query-results');
    results.replaceChildren();
    value.items.forEach((item) => {
      const row = create('button', 'result-item');
      row.type = 'button'; row.dataset.uid = itemUid(item);
      row.append(create('b', '', item.human_key || '未命名工程内容'),
        create('span', '', humanKind(item.kind || item.resource_type)),
        create('p', '', statementOf(item) || '没有可显示的正文摘要。'));
      row.addEventListener('click', () => {
        document.querySelectorAll('.result-item').forEach((element) => {
          element.removeAttribute('aria-current');
        });
        row.setAttribute('aria-current', 'true');
        const core = document.querySelector('#graph-core');
        core.querySelector('b').textContent = item.human_key || '未命名';
        core.querySelector('span').textContent = humanKind(item.kind || item.resource_type);
        motion.flash('#graph-core', '#2b795b'); audit('选择工程内容', item);
      });
      results.append(row);
    });
    if (!value.items.length) results.append(create('div', 'empty-state', '没有找到匹配内容。'));
    else {
      gsap.set(results.children, {y: 12, autoAlpha: 0}); motion.reveal(results.children);
    }
  } catch (error) { toast(error.message); }
});
const resolveHumanKey = async (humanKey) => {
  const query = await api(`/api/query?text=${encodeURIComponent(humanKey)}`);
  const exact = query.items.find((item) => String(item.human_key || '').toLocaleLowerCase()
    === humanKey.toLocaleLowerCase());
  if (!exact) throw new Error(`没有找到 Human Key“${humanKey}”。`);
  return exact;
};
const renderContext = (value, targetKey) => {
  const output = document.querySelector('#context-output');
  output.replaceChildren();
  const status = value.completeness === 'COMPLETE' ? '资料完整' : '资料存在缺口';
  const grid = create('div', 'summary-grid');
  [['整理结果', status], ['必须阅读', `${(value.mandatory || []).length} 项`],
    ['建议参考', `${(value.supporting || []).length} 项`]].forEach(([label, result]) => {
    const card = create('article');
    card.append(create('small', '', label), create('strong', '', result)); grid.append(card);
  });
  output.append(grid, create('p', 'output-note', value.completeness === 'COMPLETE'
    ? `已为 ${targetKey} 整理完成；系统标识保存在审计详情中。`
    : `已为 ${targetKey} 整理现有资料，但仍有关系或配置缺口。`));
  motion.flash(output);
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
  delegation_uid: runtimeState.delegationUid || overrides.delegationUid,
  dry_run: false, risk_class: overrides.riskClass || 'high', operation,
});
const advanceWorkspace = (state, guidance, progress) => {
  motion.stateChange('#workspace-state', state);
  document.querySelector('#workspace-guidance').textContent = guidance;
  gsap.to('#workspace-progress', {scaleX: progress, duration: .5, ease: 'power2.inOut'});
};
const paintDecision = (validation) => {
  const decision = validation.operation_decision || {};
  const blocking = (decision.blocking_finding_uids || []).length;
  const findings = (validation.findings || validation.finding_hashes || []).length;
  const strip = document.querySelector('#decision-strip');
  strip.dataset.disposition = decision.disposition || (blocking ? 'block' : 'allow');
  strip.querySelector('strong').textContent = blocking ? '需要先处理' : '可以进入批准';
  strip.querySelector('small').textContent = blocking
    ? `发现 ${blocking} 项会阻止保存的问题。`
    : findings ? `发现 ${findings} 项提示，没有阻止保存的问题。` : '没有发现会阻止保存的问题。';
  motion.flash(strip, blocking ? '#f3ded9' : '#dce9df');
};
document.querySelector('#workspace-open-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const actorOption = selectedOption('#workspace-open-form [name="actor"]');
  if (!data.configuration_uid || !data.actor || !actorOption?.dataset.delegationUid) {
    return toast('当前工程缺少可用配置或本机授权。');
  }
  runtimeState.workspaceUid = uid(); runtimeState.actor = String(data.actor);
  runtimeState.delegationUid = actorOption.dataset.delegationUid;
  runtimeState.configurationUid = String(data.configuration_uid);
  try {
    const value = await api('/api/workspace/open', {
      method: 'POST', body: JSON.stringify(envelope({
        type: 'open_workspace', configuration_uid: data.configuration_uid,
      })),
    });
    advanceWorkspace('可以编辑', '工作副本已经建立。现在说明要改什么。', .25);
    document.querySelector('#workspace-output').replaceChildren(create('p', '',
      `已按“${selectedOption('#workspace-open-form [name="configuration_uid"]')?.textContent}”开始本次变更。`));
    motion.step(0); audit('工作副本已建立', value);
  } catch (error) { toast(error.message); }
});
document.querySelector('#workspace-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.workspaceUid) return toast('请先选择工作范围并开始编辑。');
  const data = Object.fromEntries(new FormData(event.target));
  runtimeState.change = {humanKey: String(data.human_key), kind: String(data.kind),
    statement: String(data.statement), reason: String(data.change_reason)};
  const operation = {
    operation_type: 'create_object',
    working_copy: {
      workspace_uid: runtimeState.workspaceUid, object_uid: uid(),
      base_revision_uid: null, base_revision_number: 0,
      human_key: runtimeState.change.humanKey, kind: runtimeState.change.kind,
      facets: [], effective_model_hash: 'bound-by-runtime',
      delegation_uid: runtimeState.delegationUid,
      draft_fields: [{path: '/statement', value: runtimeState.change.statement}],
      draft_fragments: [], relation_proposals: [], edit_log: [],
    },
  };
  try {
    const value = await api('/api/workspace/edit', {
      method: 'POST', body: JSON.stringify(envelope(operation)),
    });
    advanceWorkspace('内容已保存', '可以继续检查并送审。', .58);
    const scope = document.querySelector('#workspace-scope');
    scope.querySelector('strong').textContent = runtimeState.change.humanKey;
    scope.querySelector('p').textContent = `${humanKind(runtimeState.change.kind)} · ${runtimeState.change.reason}`;
    document.querySelector('#workspace-output').replaceChildren(create('p', '',
      `已保存 ${runtimeState.change.humanKey}（${humanKind(runtimeState.change.kind)}）。变更理由会随审阅一起提交。`));
    motion.flash('#workspace-edit-form'); audit('变更内容已保存', value);
  } catch (error) { toast(error.message); }
});

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
    : value.finding_count ? `${value.finding_count} 项提示，不影响本次批准。`
      : '没有发现会阻止本次批准的问题。';
  const roleSelect = document.querySelector('#sign-form [name="role"]');
  roleSelect.replaceChildren();
  (value.stages || []).forEach((stage) => {
    const option = create('option', '', humanRole(stage.role));
    option.value = stage.role; roleSelect.append(option);
  });
  motion.stateChange('#sign-role', (value.stages || []).map((stage) => {
    return humanRole(stage.role);
  }).join('、') || '批准人');
  document.querySelector('#sign-form [name="package_uid"]').value = value.package_uid;
  document.querySelector('#sign-output').classList.remove('is-ready');
  document.querySelector('#sign-output span').textContent = '尚未签名。';
  document.querySelector('#apply-candidate').disabled = true;
  audit('审阅摘要已加载', value);
};
const loadReviewPackage = async (packageUid) => {
  renderReview(await api(`/api/review-package/${encodeURIComponent(packageUid)}`));
};
document.querySelector('#workspace-submit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.change.humanKey) return toast('请先保存变更内容。');
  try {
    const value = await api('/api/workspace/submit', {
      method: 'POST', body: JSON.stringify(envelope({
        configuration_uid: runtimeState.configurationUid,
        evaluation_time: new Date().toISOString(), maximum_depth: 3,
      })),
    });
    runtimeState.packageUid = value.review_package.package_uid;
    runtimeState.reviewPurpose = 'candidate'; runtimeState.approval = null;
    advanceWorkspace('等待批准', '系统校验已完成，请由合适的人确认范围和理由。', 1);
    paintDecision(value.validation);
    document.querySelector('#workspace-output').replaceChildren(create('p', '',
      `${runtimeState.change.humanKey} 已完成校验并送交审阅。`));
    motion.step(1); await loadReviewPackage(runtimeState.packageUid); selectPanel('review');
  } catch (error) { toast(error.message); }
});
document.querySelector('#sign-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.packageUid) return toast('当前没有待批准事项。');
  const data = Object.fromEntries(new FormData(event.target));
  const reviewer = selectedOption('#sign-form [name="reviewer"]');
  try {
    const value = await api('/api/sign', {
      method: 'POST', body: JSON.stringify({package_uid: runtimeState.packageUid,
        actor_uid: data.reviewer, key_uid: reviewer?.dataset.keyUid,
        role: data.role, human_confirm: data.human_confirm === 'on'}),
    });
    runtimeState.approval = value.approval;
    const output = document.querySelector('#sign-output'); output.classList.add('is-ready');
    output.querySelector('span').textContent = runtimeState.reviewPurpose === 'baseline'
      ? '批准已完成。返回“发布基线”即可发布。'
      : '批准已完成。现在可以将变更写入工程。';
    document.querySelector('#apply-candidate').disabled = runtimeState.reviewPurpose !== 'candidate';
    motion.step(2); motion.flash('.sign-zone', '#274a3d'); audit('人工批准已签名', value);
  } catch (error) { toast(error.message); }
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
document.querySelector('#apply-candidate').addEventListener('click', async () => {
  if (!runtimeState.approval || runtimeState.reviewPurpose !== 'candidate') {
    return toast('需要先由人完成批准。');
  }
  try {
    const value = await api('/api/apply', {
      method: 'POST', body: JSON.stringify(envelope({
        review_package_uid: runtimeState.packageUid,
        signed_approvals: [runtimeState.approval], evaluation_time: new Date().toISOString(),
      })),
    });
    runtimeState.base = value.result_commit; runtimeState.configurationUid = value.configuration_uid;
    runtimeState.approval = null; addResultConfiguration(value.configuration_uid);
    document.querySelector('#sign-output span').textContent
      = `${runtimeState.change.humanKey} 已安全写入工程。`;
    document.querySelector('#apply-candidate').disabled = true;
    motion.step(3); audit('批准的变更已写入工程', value);
    toast('变更已经写入工程。'); selectPanel('baseline');
  } catch (error) { toast(error.message); }
});

document.querySelector('#baseline-prepare-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const actorOption = selectedOption('#workspace-open-form [name="actor"]');
  if (!runtimeState.actor && actorOption?.value) {
    runtimeState.actor = actorOption.value;
    runtimeState.delegationUid = actorOption.dataset.delegationUid;
  }
  if (!runtimeState.actor || !runtimeState.delegationUid) {
    return toast('当前工程缺少可用的本机身份。');
  }
  try {
    const value = await api('/api/baseline/prepare', {
      method: 'POST', body: JSON.stringify(envelope({
        configuration_uid: data.configuration_uid, evaluation_time: new Date().toISOString(),
      })),
    });
    runtimeState.packageUid = value.review_package.package_uid;
    runtimeState.reviewPurpose = 'baseline'; runtimeState.approval = null;
    document.querySelector('#baseline-apply-form [name="review_package_uid"]')
      .value = runtimeState.packageUid;
    motion.stateChange('#baseline-state', '等待人工批准');
    document.querySelector('#baseline-output').replaceChildren(create('p', '',
      '工程状态已检查完成。请确认范围和理由，再返回这里发布。'));
    await loadReviewPackage(runtimeState.packageUid); selectPanel('review');
  } catch (error) { toast(error.message); }
});
document.querySelector('#baseline-apply-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.approval || runtimeState.reviewPurpose !== 'baseline') {
    return toast('请先在“审阅与批准”完成基线批准。');
  }
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/baseline/apply', {
      method: 'POST', body: JSON.stringify(envelope({
        review_package_uid: data.review_package_uid,
        signed_approvals: [runtimeState.approval], evaluation_time: new Date().toISOString(),
        tag_name: data.tag_name || null,
      })),
    });
    runtimeState.base = value.result_commit; runtimeState.approval = null;
    motion.stateChange('#baseline-state', '已发布');
    document.querySelector('#baseline-output').replaceChildren(create('p', '',
      data.tag_name ? `基线“${data.tag_name}”已发布。` : '基线已发布。'));
    audit('工程基线已发布', value); toast('基线已经发布。');
  } catch (error) { toast(error.message); }
});

document.querySelector('#refresh-tasks').addEventListener('click', async () => {
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
});
document.querySelector('#gc-plan').addEventListener('click', async () => {
  try {
    const value = await api('/api/maintenance/gc', {method: 'POST', body: '{}'});
    document.querySelector('#maintenance-output').replaceChildren(create('p', '',
      `已生成清理计划：${(value.candidates || value.removable_refs || []).length} 项可供检查。本次没有删除任何内容。`));
  } catch (error) { toast(error.message); }
});
document.querySelector('#lock-button').addEventListener('click', async () => {
  await api('/api/lock', {method: 'POST', body: '{}'}); location.href = '/locked';
});

motion.boot();
motion.configureGraph();
Promise.all([loadSession(), health()]);
