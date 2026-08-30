/* LESR human interface: engineering meaning in front, machine identity in audit. */
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const runtimeState = {
  workspaceUid: null, base: null, actor: null,
  configurationUid: null, packageUid: null, approval: null,
  reviewPurpose: null, flowIndex: 0, context: null,
  intakeRequest: null, intakeWorkspace: false, selectedItem: null,
  queryKind: '', baselineTag: '',
  engineeringMap: null, selectedMapArea: null, selectedMapItem: null,
  missions: [], decisions: [],
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
  let mapTimeline = null;
  let decisionTimeline = null;
  let panelTargets = [];
  let toastTimer = null;
  const ease = 'power3.out';
  const toElements = (targets) => {
    if (!targets) return [];
    if (typeof targets === 'string') return [...document.querySelectorAll(targets)];
    if (targets instanceof Element) return [targets];
    if (typeof targets[Symbol.iterator] === 'function') {
      return [...targets].flatMap((target) => toElements(target));
    }
    return [];
  };
  const clearAnimatedState = (targets) => {
    const elements = toElements(targets);
    if (!elements.length) return;
    gsap.set(elements, {clearProps: 'transform,opacity,visibility,willChange'});
  };
  media.add('(prefers-reduced-motion: reduce)', () => {
    enabled = false;
    if (panelTimeline) panelTimeline.kill();
    if (mapTimeline) mapTimeline.kill();
    clearAnimatedState('.panel, .priority-work, [data-map-column], .map-document-row');
    return () => { enabled = true; };
  });
  const animate = (targets, vars) => {
    const elements = toElements(targets);
    if (!elements.length) return null;
    if (!enabled) {
      clearAnimatedState(elements);
      return null;
    }
    gsap.set(elements, {willChange: 'transform,opacity'});
    const after = vars.onComplete;
    return gsap.to(elements, {
      ...vars,
      onComplete() {
        clearAnimatedState(elements);
        if (after) after();
      },
      onInterrupt() { clearAnimatedState(elements); },
    });
  };
  const boot = () => {
    if (!enabled) return;
    gsap.timeline({defaults: {ease}})
      .addLabel('shell')
      .from('.masthead > *', {y: -12, autoAlpha: 0, duration: .42, stagger: .06}, 'shell')
      .from('.rail .nav-item', {x: -10, autoAlpha: 0, duration: .28, stagger: .025}, 'shell+=.16')
      .addLabel('heading', 'shell+=.26')
      .from('#overview .eyebrow, #overview h1, #overview .lede', {
        y: 18, autoAlpha: 0, duration: .48, stagger: .07,
      }, 'heading')
      .addLabel('atlas', 'heading+=.18')
      .from('[data-map-column]', {
        y: 16, autoAlpha: 0, duration: .38, stagger: .06,
      }, 'atlas')
      .from('.overview-actions button', {
        y: 12, autoAlpha: 0, duration: .32, stagger: .035,
      }, 'atlas+=.2');
  };
  const enterPanel = (panel) => {
    if (panelTimeline) {
      panelTimeline.kill();
      clearAnimatedState(panelTargets);
    }
    if (!enabled) return;
    const content = panel.querySelectorAll(
      '.section-copy, form, .intake-composer, .intake-result, .engineering-atlas, .mission-board, .decision-workspace, .workflow-drawer, .version-ledger, .explore-workspace, .context-key, .context-result, .change-composer, .review-decision, .review-scope, .sign-zone, .baseline-workflow, .task-toolbar, .task-list, .maintenance-layout, .audit-summary, .audit-section, .human-output'
    );
    const headings = panel.querySelectorAll('.eyebrow, h2');
    panelTargets = toElements([panel, headings, content]);
    gsap.set(panelTargets, {willChange: 'transform,opacity'});
    panelTimeline = gsap.timeline({
      defaults: {ease},
      onComplete: () => clearAnimatedState(panelTargets),
      onInterrupt: () => clearAnimatedState(panelTargets),
    })
      .addLabel('panel')
      .fromTo(panel, {autoAlpha: 0}, {autoAlpha: 1, duration: .16}, 'panel')
      .addLabel('heading', 'panel+=.03')
      .from(headings, {
        y: 15, autoAlpha: 0, duration: .34, stagger: .045,
      }, 'heading')
      .addLabel('content', 'heading+=.08')
      .from(content, {y: 12, autoAlpha: 0, duration: .32, stagger: .035}, 'content');
  };
  const mapFlow = (areaTargets, documentTargets, contextTarget) => {
    const areas = toElements(areaTargets);
    const documents = toElements(documentTargets);
    const contexts = toElements(contextTarget);
    const animated = [...areas, ...documents, ...contexts];
    if (mapTimeline) {
      mapTimeline.kill();
      clearAnimatedState(animated);
    }
    if (!enabled) {
      clearAnimatedState(animated);
      return;
    }
    if (!animated.length) return;
    gsap.set(animated, {willChange: 'transform,opacity'});
    mapTimeline = gsap.timeline({
      defaults: {duration: .32, ease},
      onComplete: () => clearAnimatedState(animated),
      onInterrupt: () => clearAnimatedState(animated),
    })
      .addLabel('area')
      .fromTo(areas, {x: -8, autoAlpha: .5}, {x: 0, autoAlpha: 1}, 'area')
      .addLabel('documents', 'area+=.07')
      .fromTo(documents, {x: 10, autoAlpha: 0}, {
        x: 0, autoAlpha: 1, stagger: .035,
      }, 'documents')
      .addLabel('context', 'documents+=.1')
      .fromTo(contexts, {x: 12, autoAlpha: 0}, {x: 0, autoAlpha: 1}, 'context');
  };
  const decisionFlow = (headingTarget, evidenceTargets, responseTarget) => {
    const headings = toElements(headingTarget);
    const evidence = toElements(evidenceTargets);
    const response = toElements(responseTarget);
    const animated = [...headings, ...evidence, ...response];
    if (decisionTimeline) {
      decisionTimeline.kill();
      clearAnimatedState(animated);
    }
    if (!enabled || !animated.length) {
      clearAnimatedState(animated);
      return;
    }
    gsap.set(animated, {willChange: 'transform,opacity'});
    decisionTimeline = gsap.timeline({
      defaults: {ease},
      onComplete: () => clearAnimatedState(animated),
      onInterrupt: () => clearAnimatedState(animated),
    })
      .addLabel('question')
      .fromTo(headings, {y: 10, autoAlpha: 0}, {
        y: 0, autoAlpha: 1, duration: .32,
      }, 'question')
      .addLabel('evidence', 'question+=.1')
      .fromTo(evidence, {x: -8, autoAlpha: 0}, {
        x: 0, autoAlpha: 1, duration: .3, stagger: .045,
      }, 'evidence')
      .addLabel('choice', 'evidence+=.1')
      .fromTo(response, {x: 10, autoAlpha: 0}, {
        x: 0, autoAlpha: 1, duration: .34,
      }, 'choice');
  };
  const step = (index) => {
    runtimeState.flowIndex = Math.max(runtimeState.flowIndex, index);
  };
  const stateChange = (selector, value, tone = 'normal') => {
    const element = document.querySelector(selector);
    if (!element) return;
    element.textContent = value;
    element.classList.toggle('state-danger', tone === 'danger');
    if (!enabled) return;
    gsap.set(element, {willChange: 'transform,opacity'});
    gsap.fromTo(element, {
      y: 5, autoAlpha: 0,
    }, {
      y: 0, autoAlpha: 1, duration: .36, ease,
      onComplete: () => clearAnimatedState(element),
      onInterrupt: () => clearAnimatedState(element),
    });
  };
  const reveal = (targets) => animate(targets, {
    y: 0, autoAlpha: 1, duration: .32, stagger: .04, ease,
  });
  const flash = (target, color = '#dce9df') => {
    if (!enabled) return;
    void color;
    const elements = toElements(target);
    gsap.set(elements, {willChange: 'transform'});
    gsap.timeline({
      defaults: {ease},
      onComplete: () => clearAnimatedState(elements),
      onInterrupt: () => clearAnimatedState(elements),
    })
      .to(target, {scale: .992, duration: .1})
      .to(target, {scale: 1, duration: .32});
  };
  const notify = (target) => {
    const element = toElements(target)[0];
    if (!element) return;
    window.clearTimeout(toastTimer);
    gsap.killTweensOf(element);
    if (!enabled) {
      gsap.set(element, {y: 0, autoAlpha: 1});
      toastTimer = window.setTimeout(() => {
        gsap.set(element, {y: 18, autoAlpha: 0, clearProps: 'willChange'});
      }, 3000);
      return;
    }
    gsap.set(element, {willChange: 'transform,opacity'});
    gsap.timeline({
      onComplete: () => clearAnimatedState(element),
      onInterrupt: () => clearAnimatedState(element),
    })
      .to(element, {y: 0, autoAlpha: 1, duration: .28, ease})
      .to(element, {y: 18, autoAlpha: 0, duration: .24, ease: 'power2.in'}, '+=2.8');
  };
  return {
    boot, enterPanel, mapFlow, decisionFlow, step, stateChange, reveal, flash, notify,
    version: gsap.version,
  };
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
  motion.notify(element);
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
  if (panel.id === 'overview') void loadEngineeringMap();
  if (panel.id === 'missions') void loadMissions();
  if (panel.id === 'decisions') void loadDecisions();
  if (panel.id === 'versions') renderVersions();
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
  renderVersions();
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
      document.querySelector('#overview-priority-note').textContent = '查看未完成内容，继续整理。';
      const primary = document.querySelector('.priority-primary');
      primary.textContent = '继续处理';
      primary.dataset.go = 'workspace';
      delete primary.dataset.intakeMode;
    }
  } catch (error) { toast(error.message); }
}

const LIFE_NAMES = {
  approved: '已批准', draft: '草案', active: '有效', retired: '已归档',
  planned: '已计划', ready: '可开始', running: '进行中',
  waiting_for_decision: '等待决定', blocked: '受阻', completed: '已完成',
  failed: '失败', cancelled: '已取消', queued: '等待执行', interrupted: '已中断',
};
const CONTEXT_NAMES = {
  COMPLETE: '资料完整', INCOMPLETE_MISSING_RELATION: '缺少关联内容',
  INCOMPLETE_BUDGET: '需要继续读取', INCOMPLETE_CONFIGURATION: '配置待补充',
  INCOMPLETE_CONFLICT: '存在工程冲突', INCOMPLETE_CONFIDENTIALITY: '部分内容受限',
};
const lifeName = (value) => LIFE_NAMES[String(value || '').toLocaleLowerCase()]
  || String(value || '状态待确认').replaceAll('_', ' ');
const optionalApi = async (url) => {
  try { return await api(url); }
  catch (error) {
    audit('渐进界面数据尚未接入', {url, message: error.message});
    return null;
  }
};
const mapItemTitle = (item) => item.title || item.human_key || '未命名工程内容';
const mapItemKind = (item) => humanKind(item.kind_name || item.kind || item.resource_type);
const mapItemSummary = (item) => item.summary || statementOf(item) || '尚无正文摘要。';

const renderMapDetail = (item, row) => {
  runtimeState.selectedMapItem = item;
  document.querySelectorAll('.map-document-row').forEach((element) => {
    element.toggleAttribute('aria-current', element === row);
  });
  const detail = document.querySelector('#engineering-item-detail');
  detail.replaceChildren();
  const heading = create('div', 'map-item-heading');
  heading.append(
    create('span', '', mapItemKind(item)),
    create('h3', '', item.human_key || mapItemTitle(item)),
    create('p', '', mapItemTitle(item) === item.human_key ? '' : mapItemTitle(item)),
  );
  const state = create('div', 'map-item-state');
  state.append(
    create('small', '', item.is_candidate || item.workspace_draft ? '本次工作' : '工程内容'),
    create('strong', '', lifeName(item.lifecycle_state || (item.workspace_draft ? 'draft' : 'active'))),
  );
  detail.append(heading, state, create('p', 'map-item-summary', mapItemSummary(item)));

  const traceOutput = document.querySelector('#engineering-trace-summary');
  traceOutput.replaceChildren();
  const matrices = runtimeState.engineeringMap?.trace_coverage || [];
  const traceRows = matrices.flatMap((matrix) => (matrix.rows || [])
    .filter((traceRow) => traceRow.source?.human_key === item.human_key)
    .map((traceRow) => ({...traceRow, matrixLabel: matrix.label})));
  const traceHeading = create('header');
  traceHeading.append(create('h4', '', '追踪覆盖'), create('span', '', traceRows.length
    ? `${traceRows.filter((traceRow) => traceRow.state === 'covered').length}/${traceRows.length}`
    : '—'));
  traceOutput.append(traceHeading);
  if (!traceRows.length) {
    traceOutput.append(create('p', 'map-subtle', '当前映射没有为这项内容定义追踪矩阵。'));
  } else {
    traceRows.forEach((traceRow) => {
      const line = create('section', 'map-trace-line');
      const summary = create('div');
      summary.append(create('b', '', traceRow.matrixLabel || '追踪关系'),
        create('span', '', traceRow.state === 'covered' ? '已覆盖'
          : traceRow.state === 'indeterminate' ? '待确认' : '缺少覆盖'));
      line.append(summary);
      (traceRow.links || []).forEach((link) => {
        line.append(create('p', '', `${link.predicate || '关联'} → ${link.target?.human_key || mapItemTitle(link.target || {})}`));
      });
      traceOutput.append(line);
    });
  }

  const contextOutput = document.querySelector('#engineering-context-summary');
  contextOutput.replaceChildren();
  const context = runtimeState.engineeringMap?.context;
  const contextHeading = create('header');
  contextHeading.append(create('h4', '', '工作资料'), create('span', '', context
    ? (CONTEXT_NAMES[context.completeness] || '资料已整理') : '—'));
  contextOutput.append(contextHeading);
  if (!context) {
    contextOutput.append(create('p', 'map-subtle', '选择具体任务后，这里会汇总必读内容和参考资料。'));
  } else {
    const materialLine = (label, values) => {
      const line = create('section', 'map-material-line');
      line.append(create('b', '', label), create('span', '', `${values.length} 项`));
      if (values.length) line.append(create('p', '', values.slice(0, 5)
        .map((value) => value.human_key || mapItemTitle(value)).join('、')));
      return line;
    };
    contextOutput.append(
      materialLine('必读', context.mandatory_items || []),
      materialLine('参考', context.supporting_items || []),
    );
  }
  document.querySelector('#context-form [name="target_key"]').value = item.human_key || '';
  const changeForm = document.querySelector('#workspace-compose-form');
  changeForm.querySelector('[name="human_key"]').value = item.human_key || '';
  changeForm.querySelector('[name="statement"]').value = item.summary || statementOf(item) || '';
  updateChangePreview();
  motion.mapFlow(
    document.querySelector('.map-area-button[aria-current="true"]'),
    document.querySelectorAll('.map-document-row'),
    document.querySelector('.atlas-detail'),
  );
};

const renderMapDocuments = () => {
  const area = runtimeState.selectedMapArea;
  const output = document.querySelector('#engineering-document-list');
  const query = document.querySelector('#map-filter-input').value.trim().toLocaleLowerCase();
  output.replaceChildren();
  const items = (area?.items || []).filter((item) => !query || [
    item.human_key, mapItemTitle(item), mapItemKind(item), mapItemSummary(item),
  ].some((value) => String(value || '').toLocaleLowerCase().includes(query)));
  document.querySelector('#map-document-count').textContent = String(items.length);
  if (!items.length) {
    const empty = create('div', 'atlas-empty');
    empty.append(create('b', '', query ? '当前区域没有匹配内容' : '这个区域还没有工程内容'));
    if (!query) {
      const start = create('button', 'text-action', '从需求开始');
      start.type = 'button'; start.addEventListener('click', () => selectPanel('intake'));
      empty.append(start);
    }
    output.append(empty);
    document.querySelector('#engineering-item-detail').replaceChildren(
      create('div', 'atlas-empty', query ? '换一个关键词继续查找。' : '选择其他区域，或建立工程内容。'),
    );
    document.querySelector('#engineering-trace-summary').replaceChildren();
    document.querySelector('#engineering-context-summary').replaceChildren();
    return;
  }
  items.forEach((item) => {
    const row = create('button', 'map-document-row');
    row.type = 'button';
    const title = create('div');
    title.append(create('b', '', item.human_key || mapItemTitle(item)),
      create('span', '', mapItemKind(item)));
    row.append(title, create('p', '', mapItemTitle(item)),
      create('small', '', mapItemSummary(item)));
    row.addEventListener('click', () => renderMapDetail(item, row));
    output.append(row);
  });
  renderMapDetail(items[0], output.firstElementChild);
};

const selectMapArea = (area, button) => {
  runtimeState.selectedMapArea = area;
  document.querySelectorAll('.map-area-button').forEach((element) => {
    element.toggleAttribute('aria-current', element === button);
  });
  document.querySelector('#map-area-label').textContent = area.label || '当前区域';
  document.querySelector('#map-filter-input').value = '';
  renderMapDocuments();
};

const renderEngineeringMap = (payload) => {
  const view = payload?.engineering_view || payload?.view || payload || {};
  runtimeState.engineeringMap = view;
  const atlas = document.querySelector('#engineering-map');
  const tree = document.querySelector('#engineering-area-tree');
  tree.replaceChildren();
  const areas = view.areas || [];
  atlas.classList.toggle('is-empty', !areas.length);
  if (!areas.length) {
    const empty = create('div', 'atlas-empty');
    empty.append(create('b', '', '工程地图等待第一批内容'),
      create('p', '', '粘贴需求或导入现有规范，建立工程结构。'));
    const start = create('button', 'text-action', '从需求开始');
    start.type = 'button'; start.addEventListener('click', () => selectPanel('intake'));
    empty.append(start); tree.append(empty);
    runtimeState.selectedMapArea = {label: '工程内容', items: []};
    document.querySelector('#map-area-label').textContent = '工程内容';
    renderMapDocuments();
    return;
  }
  areas.forEach((area, index) => {
    const button = create('button', 'map-area-button');
    button.type = 'button';
    const line = create('span');
    line.append(create('b', '', area.label || area.area_key || '工程区域'),
      create('em', '', String((area.items || []).length)));
    button.append(line);
    if (area.description) button.append(create('small', '', area.description));
    button.addEventListener('click', () => selectMapArea(area, button));
    tree.append(button);
    if (index === 0) selectMapArea(area, button);
  });
};

const loadEngineeringMap = async () => {
  const mapped = await optionalApi('/api/engineering/map');
  if (mapped) return renderEngineeringMap(mapped);
  const queried = await optionalApi('/api/query?text=&kind=');
  if (!queried) return renderEngineeringMap({areas: []});
  renderEngineeringMap({
    mapping_name: '工程内容',
    areas: [{
      area_key: 'all-content', label: '全部工程内容',
      description: '当前配置中的文档与条目',
      items: (queried.items || []).map((item) => ({
        ...item,
        title: item.human_key || humanKind(item.kind || item.resource_type),
        kind_name: item.kind || item.resource_type,
        summary: statementOf(item),
        lifecycle_state: item.workspace_draft ? 'draft' : 'active',
        is_candidate: Boolean(item.workspace_draft),
      })),
    }],
    trace_coverage: [], context: null,
  });
};

document.querySelector('#map-filter-input').addEventListener('input', renderMapDocuments);

const missionStateName = (value) => lifeName(value || 'planned');
const workPackageDepths = (packages) => {
  const byUid = new Map(packages.map((item) => [item.work_package_uid, item]));
  const memo = new Map();
  const depth = (item, path = new Set()) => {
    if (memo.has(item.work_package_uid)) return memo.get(item.work_package_uid);
    if (path.has(item.work_package_uid)) return 0;
    const nextPath = new Set(path); nextPath.add(item.work_package_uid);
    const dependencies = (item.dependency_uids || []).map((key) => byUid.get(key)).filter(Boolean);
    const value = dependencies.length ? 1 + Math.max(...dependencies.map((entry) => depth(entry, nextPath))) : 0;
    memo.set(item.work_package_uid, value); return value;
  };
  packages.forEach((item) => depth(item));
  return memo;
};

const renderMission = (record, button) => {
  const mission = record.mission || record;
  document.querySelectorAll('.mission-select').forEach((element) => {
    element.toggleAttribute('aria-current', element === button);
  });
  document.querySelector('#mission-title').textContent = mission.title || '工程任务';
  document.querySelector('#mission-objective').textContent = mission.objective || '推进当前工程工作。';
  document.querySelector('#mission-state').textContent = missionStateName(mission.state);
  const packages = mission.work_packages || record.work_packages || [];
  const depths = workPackageDepths(packages);
  const dag = document.querySelector('#mission-dag'); dag.replaceChildren();
  packages.forEach((workPackage) => {
    const node = create('article', 'mission-node');
    node.style.setProperty('--mission-depth', String(depths.get(workPackage.work_package_uid) || 0));
    node.dataset.state = workPackage.state || 'planned';
    const marker = create('i');
    const body = create('div');
    body.append(create('b', '', workPackage.title || '工作包'),
      create('p', '', workPackage.objective || '完成这一项工程工作。'));
    const meta = create('span', '', `${missionStateName(workPackage.state)} · ${humanRole(workPackage.role || 'engineering')}`);
    node.append(marker, body, meta); dag.append(node);
  });
  if (!packages.length) dag.append(create('div', 'mission-empty', '这项任务尚未分解工作包。'));

  const runs = record.agent_runs || mission.agent_runs || [];
  const agent = record.current_agent || mission.current_agent
    || runs.find((run) => run.state === 'running') || null;
  const agentOutput = document.querySelector('#mission-agent'); agentOutput.replaceChildren();
  if (agent) {
    agentOutput.append(create('b', '', humanRole(agent.role || 'engineering')),
      create('p', '', agent.current_work || agent.objective || '正在处理当前工作包。'),
      create('span', '', missionStateName(agent.state || 'running')));
  } else {
    const running = packages.find((item) => item.state === 'running');
    agentOutput.append(create('b', '', running ? humanRole(running.role) : '尚未分派'),
      create('p', '', running?.objective || '等待可执行的工作包。'));
  }
  const next = packages.find((item) => item.state === 'waiting_for_decision')
    || packages.find((item) => item.state === 'ready')
    || packages.find((item) => item.state === 'planned');
  const nextOutput = document.querySelector('#mission-next-step'); nextOutput.replaceChildren();
  if (next) {
    nextOutput.append(create('b', '', next.title || '下一工作包'),
      create('p', '', next.objective || '继续推进工程任务。'),
      create('span', '', missionStateName(next.state)));
  } else {
    nextOutput.append(create('b', '', mission.state === 'completed' ? '任务已完成' : '等待下一项工作'),
      create('p', '', mission.state === 'completed' ? '全部工作包已经完成。' : '代理正在整理下一步。'));
  }
};

const renderMissions = (payload) => {
  const records = Array.isArray(payload) ? payload : payload?.missions || payload?.items || [];
  runtimeState.missions = records;
  document.querySelector('#mission-count').textContent = String(records.length);
  const list = document.querySelector('#mission-list'); list.replaceChildren();
  if (!records.length) {
    const empty = create('div', 'mission-empty');
    empty.append(create('b', '', '尚无工程任务'), create('p', '', '从需求或现有规范建立工程内容。'));
    const start = create('button', 'text-action', '从需求开始');
    start.type = 'button'; start.addEventListener('click', () => selectPanel('intake'));
    empty.append(start); list.append(empty);
    document.querySelector('#mission-dag').replaceChildren(create('div', 'mission-empty', '暂无工作包。'));
    return;
  }
  records.forEach((record, index) => {
    const mission = record.mission || record;
    const button = create('button', 'mission-select');
    button.type = 'button';
    button.append(create('b', '', mission.title || '工程任务'),
      create('span', '', missionStateName(mission.state)));
    button.addEventListener('click', () => renderMission(record, button));
    list.append(button);
    if (index === 0) renderMission(record, button);
  });
};

const loadMissions = async () => renderMissions(await optionalApi('/api/missions'));

const decisionNeedsHuman = (decision) => {
  const disposition = String(decision.disposition || decision.decision_disposition || '');
  const state = String(decision.state || decision.status || '').toLocaleLowerCase();
  if (['resolved', 'completed', 'cancelled', 'closed'].includes(state)) return false;
  if (disposition) return disposition === 'HUMAN_DECISION_NOW';
  return decision.requires_human !== false;
};
const decisionText = (decision, ...names) => names
  .map((name) => decision[name]).find((value) => typeof value === 'string' && value.trim()) || '';

const humanDecisionType = (value) => String(value || '工程取舍')
  .replaceAll('_', ' ')
  .replaceAll('-', ' ');
const humanDecisionArea = (areaKey) => {
  const areas = runtimeState.engineeringMap?.areas || [];
  return areas.find((area) => area.area_key === areaKey)?.label
    || humanKind(areaKey || '工程范围');
};
const decisionActor = () => {
  const actors = runtimeState.context?.actors || [];
  return actors.find((actor) => actor.actor_uid === runtimeState.actor) || actors[0] || null;
};
const conclusionName = (value) => ({
  passed: '检查通过', failed: '检查未通过', indeterminate: '仍需补充信息',
}[String(value || '').toLocaleLowerCase()] || '检查结果待整理');

const appendDecisionOption = (group, value) => {
  const label = create('label', `decision-option${value.primary ? ' decision-option-primary' : ''}`);
  const radio = create('input');
  radio.type = 'radio';
  radio.name = 'decision-choice';
  radio.value = value.value;
  radio.dataset.selectionKind = value.selectionKind;
  radio.required = true;
  const copy = create('span');
  const title = create('span', 'decision-option-title');
  title.append(create('b', '', value.title));
  if (value.primary) title.append(create('em', '', '代理建议'));
  copy.append(title, create('p', '', value.summary));
  if (value.tradeOff) copy.append(create('small', '', value.tradeOff));
  label.append(radio, copy);
  group.append(label);
};

const renderDecision = (decision, button) => {
  document.querySelectorAll('.decision-select').forEach((element) => {
    element.toggleAttribute('aria-current', element === button);
  });
  const output = document.querySelector('#decision-request'); output.replaceChildren();
  const target = decision.target || {};
  const targetLabel = target.label || target.engineering_key || '当前工程内容';
  const heading = create('header', 'decision-request-heading');
  heading.append(create('small', '', `${humanDecisionArea(decision.engineering_area)} · ${humanDecisionType(decision.decision_type)}`),
    create('h3', '', targetLabel),
    create('p', '', decision.change_summary || '请选择后续采用的工程方向。'));
  if (target.engineering_key) {
    heading.append(create('span', 'decision-engineering-key', `工程编号 ${target.engineering_key}`));
  }
  output.append(heading);

  const body = create('div', 'decision-body');
  const brief = create('div', 'decision-brief');
  const impact = decision.impact || {};
  const impactSection = create('section', 'decision-section decision-impact');
  impactSection.append(create('h4', '', '影响'));
  impactSection.append(create('p', '', impact.summary || '影响集中在当前工作范围。'));
  const areaValues = Array.isArray(impact.affected_areas) ? impact.affected_areas : [];
  const scopeList = create('div', 'decision-scope-list');
  scopeList.append(create('span', '', target.engineering_key || targetLabel));
  areaValues.forEach((area) => scopeList.append(create('span', '', humanDecisionArea(area))));
  impactSection.append(scopeList);
  brief.append(impactSection);

  const validation = decision.validation || {};
  const validationSection = create('section', 'decision-section decision-validation');
  validationSection.append(create('h4', '', '检查结论'),
    create('strong', '', conclusionName(validation.conclusion)),
    create('p', '', validation.summary || '检查结果已纳入本次选择。'));
  brief.append(validationSection);

  const policies = Array.isArray(decision.triggered_policies) ? decision.triggered_policies : [];
  const reasonSection = create('section', 'decision-section decision-why');
  reasonSection.append(create('h4', '', '为什么现在需要选择'));
  policies.forEach((policy) => {
    const row = create('article');
    row.append(create('b', '', policy.title || '工程规则'),
      create('p', '', policy.explanation || '这项规则要求明确工程方向。'));
    reasonSection.append(row);
  });
  if (!policies.length) reasonSection.append(create('p', '', '当前工作出现了需要明确取舍的工程分支。'));
  brief.append(reasonSection);

  const response = create('aside', 'decision-response');
  const recommendation = decision.recommendation
    || decisionText(decision, 'recommended_option');
  if (recommendation) {
    const note = create('section', 'decision-recommendation');
    note.append(create('small', '', '建议方向'), create('p', '', recommendation));
    response.append(note);
  }
  const form = create('form', 'decision-resolution-form');
  form.id = 'decision-resolution-form';
  const choice = create('fieldset', 'decision-options');
  choice.append(create('legend', '', '选择一个方向'));
  const action = decision.action || {};
  if (action.operation && action.label) {
    appendDecisionOption(choice, {
      primary: true,
      selectionKind: 'action',
      value: action.operation,
      title: action.label,
      summary: action.result || recommendation || '按此方向继续当前任务。',
    });
  }
  const alternatives = Array.isArray(decision.alternatives) ? decision.alternatives : [];
  alternatives.forEach((alternative, index) => {
    appendDecisionOption(choice, {
      primary: false,
      selectionKind: 'alternative',
      value: alternative.title,
      title: alternative.title || `备选方向 ${index + 1}`,
      summary: alternative.summary || '采用这一备选方向。',
      tradeOff: alternative.trade_off || '',
    });
  });
  if (!choice.querySelector('input')) {
    choice.append(create('p', 'decision-no-options', '可选方向正在整理。'));
  }
  form.append(choice);

  const reason = create('label', 'decision-reason');
  reason.append(create('span', '', '你的判断依据'));
  const reasonInput = create('textarea');
  reasonInput.name = 'reason';
  reasonInput.required = true;
  reasonInput.maxLength = 4000;
  reasonInput.placeholder = '简要说明为什么选择这个方向';
  reason.append(reasonInput);
  form.append(reason);

  const actor = decisionActor();
  const footer = create('footer', 'decision-submit');
  const actorLine = create('p');
  actorLine.append(create('span', '', '记录人'), create('strong', '', actor?.display_name || '尚未设置本机用户'));
  const submit = create('button', '', '记录选择并继续任务');
  submit.type = 'submit';
  submit.disabled = !actor || !choice.querySelector('input');
  footer.append(actorLine, submit);
  const status = create('p', 'decision-resolution-status');
  status.setAttribute('role', 'status');
  form.append(footer, status);

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const selected = form.querySelector('input[name="decision-choice"]:checked');
    const reasonText = reasonInput.value.trim();
    if (!selected || !actor) {
      toast('请选择一个工程方向。');
      return;
    }
    if (!reasonText) {
      toast('请简要写下判断依据。');
      reasonInput.focus();
      return;
    }
    submit.disabled = true;
    submit.textContent = '正在记录…';
    status.textContent = '';
    try {
      const payload = {
        actor_uid: actor.actor_uid,
        reason: reasonText,
        selected_action: selected.dataset.selectionKind === 'action' ? selected.value : null,
        selected_alternative: selected.dataset.selectionKind === 'alternative' ? selected.value : null,
      };
      await api(`/api/decisions/${encodeURIComponent(decision.decision_request_uid)}/resolve`, {
        method: 'POST', body: JSON.stringify(payload),
      });
      toast('选择已记录，任务继续推进。');
      await Promise.all([loadDecisions(), loadMissions()]);
    } catch (error) {
      status.textContent = error.message;
      submit.disabled = false;
      submit.textContent = '记录选择并继续任务';
    }
  });

  response.append(form);
  body.append(brief, response);
  output.append(body);
  motion.decisionFlow(heading, brief.querySelectorAll('.decision-section'), response);
};

const renderDecisions = (payload) => {
  const raw = Array.isArray(payload) ? payload : payload?.decisions || payload?.items || [];
  const decisions = raw.filter(decisionNeedsHuman);
  runtimeState.decisions = decisions;
  document.querySelector('#decision-count').textContent = String(decisions.length);
  const navCount = document.querySelector('#decision-nav-count');
  navCount.textContent = String(decisions.length); navCount.hidden = !decisions.length;
  const list = document.querySelector('#decision-list'); list.replaceChildren();
  if (!decisions.length) {
    list.append(create('div', 'decision-empty', '当前没有待处理决策。'));
    const output = document.querySelector('#decision-request'); output.replaceChildren();
    const empty = create('div', 'decision-empty decision-empty-main');
    empty.append(create('span', '', '清'), create('h3', '', '当前没有待定的工程取舍'),
      create('p', '', '任务按既定方向推进中。'));
    output.append(empty); return;
  }
  decisions.forEach((decision, index) => {
    const button = create('button', 'decision-select'); button.type = 'button';
    const target = decision.target || {};
    button.append(create('b', '', target.label || target.engineering_key || '工程决策'),
      create('span', '', `${humanDecisionArea(decision.engineering_area)} · ${humanDecisionType(decision.decision_type)}`));
    button.addEventListener('click', () => renderDecision(decision, button));
    list.append(button); if (index === 0) renderDecision(decision, button);
  });
};

const loadDecisions = async () => renderDecisions(await optionalApi('/api/decisions'));

const renderVersions = () => {
  const configurations = runtimeState.context?.configurations || [];
  const selected = configurations.find((item) => item.configuration_uid === runtimeState.configurationUid)
    || configurations[0];
  document.querySelector('#version-current-name').textContent = selected?.name || '尚未选择配置';
  document.querySelector('#version-current-note').textContent = selected
    ? `${selected.change_count || 0} 项工程内容 · ${selected.closure_status === 'complete' ? '配置完整' : '仍需补充'}`
    : '建立工程配置后显示版本内容。';
  document.querySelector('#version-count').textContent = String(configurations.length);
  const list = document.querySelector('#version-list'); list.replaceChildren();
  configurations.forEach((configuration) => {
    const row = create('button', 'version-row'); row.type = 'button';
    const copy = create('span');
    copy.append(create('b', '', configuration.name || '工程配置'),
      create('small', '', `${configuration.change_count || 0} 项内容`));
    row.append(copy, create('em', '', configuration.closure_status === 'complete' ? '完整' : '待补充'));
    row.toggleAttribute('aria-current', configuration === selected);
    row.addEventListener('click', () => { syncConfiguration(configuration.configuration_uid); renderVersions(); });
    list.append(row);
  });
  if (!configurations.length) list.append(create('div', 'version-empty', '当前还没有工程配置。'));
};

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
      `已采用“${value.selected_template}”建立工程草案，任务正在按工程结构展开。`));
    advanceWorkspace('草案已建立', `${value.requirement_count} 项内容可以继续编辑。`, .66);
    motion.step(0);
    audit('需求已建立工程任务', value);
    await Promise.all([loadEngineeringMap(), loadMissions()]);
    selectPanel('missions');
    toast('工程任务已经建立。');
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
  if (key && statement && reason) advanceWorkspace('可以检查', '内容和理由已经填写。', .72);
  else advanceWorkspace('准备填写', '完成内容后可以检查。', key || statement || reason ? .35 : 0);
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
  strip.querySelector('strong').textContent = blocking ? '需要先处理' : '检查通过';
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
const submitChangeWorkspace = async () => {
  const value = await api('/api/workspace/submit', {
    method: 'POST', body: JSON.stringify(envelope({
      configuration_uid: runtimeState.configurationUid,
      evaluation_time: new Date().toISOString(), maximum_depth: 3,
    })),
  });
  runtimeState.packageUid = value.review_package.package_uid;
  runtimeState.reviewPurpose = 'candidate'; runtimeState.approval = null;
  runtimeState.intakeWorkspace = false;
  advanceWorkspace('等待正式审阅', '变更范围和检查结论已经汇总。', 1);
  paintDecision(value.validation);
  const output = document.querySelector('#workspace-output');
  output.hidden = false;
  output.replaceChildren(create('p', '', `${runtimeState.change.humanKey} 已进入正式审阅。`));
  motion.step(1);
  await loadReviewPackage(runtimeState.packageUid);
  selectPanel('review');
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
  const output = document.querySelector('#workspace-output');
  output.hidden = false;
  output.replaceChildren(create('p', '', `${runtimeState.change.humanKey} 已完成检查。`));
  if (!['BLOCK', 'HUMAN_DECISION_NOW'].includes(disposition)) {
    const review = create('button', 'secondary-action', '送交正式审阅');
    review.type = 'button';
    review.addEventListener('click', async () => {
      review.disabled = true; review.textContent = '正在整理…';
      try { await submitChangeWorkspace(); }
      catch (error) {
        review.disabled = false; review.textContent = '送交正式审阅'; toast(error.message);
      }
    });
    output.append(review);
  }
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
    button.disabled = false; button.textContent = '保存并检查';
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
const initializeInterface = async () => {
  await Promise.all([loadSession(), health()]);
  await Promise.all([loadEngineeringMap(), loadMissions(), loadDecisions()]);
};
void initializeInterface();
