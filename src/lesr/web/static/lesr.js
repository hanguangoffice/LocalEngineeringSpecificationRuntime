/* LESR motion language: every animation represents state, causality, or focus. */
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const runtimeState = {
  workspaceUid: null,
  base: null,
  actor: null,
  delegationUid: null,
  configurationUid: null,
  packageUid: null,
  approval: null,
  flowIndex: 0,
};

const motion = (() => {
  const mm = gsap.matchMedia();
  let enabled = true;
  let panelTimeline = null;
  const ease = 'power3.out';

  mm.add('(prefers-reduced-motion: reduce)', () => {
    enabled = false;
    gsap.set('.panel.active, .metric, .flow-step, .state-plate', {clearProps: 'all'});
    return () => { enabled = true; };
  });

  const animate = (targets, vars) => {
    if (!enabled) {
      gsap.set(targets, {...vars, duration: 0, clearProps: vars.clearProps || 'transform,opacity'});
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
    const timeline = gsap.timeline({defaults: {ease}});
    timeline
      .from('.masthead > *', {y: -14, autoAlpha: 0, duration: .46, stagger: .07})
      .from('.rail .nav-item', {x: -12, autoAlpha: 0, duration: .32, stagger: .035}, '-=.18')
      .from('#overview .eyebrow, #overview .kicker', {y: 10, autoAlpha: 0, duration: .34}, '-=.08')
      .from('#overview h1', {y: 28, autoAlpha: 0, duration: .65}, '-=.17')
      .from('#overview .lede', {x: -16, autoAlpha: 0, duration: .42}, '-=.35')
      .from('.state-plate', {x: 22, autoAlpha: 0, duration: .5}, '-=.45')
      .from('.metric', {y: 18, autoAlpha: 0, duration: .42, stagger: .055}, .58)
      .from('.flow-step', {scale: .92, autoAlpha: 0, duration: .3, stagger: .045}, .76);
  };

  const enterPanel = (panel) => {
    if (panelTimeline) panelTimeline.kill();
    if (!enabled) return;
    const header = panel.querySelectorAll('.eyebrow, h2');
    const content = panel.querySelectorAll(
      '.section-copy, .command-form, .two-column, .workbench, .review-grid, .sign-zone, .maintenance-grid, .secondary-action, .task-list, .output'
    );
    panelTimeline = gsap.timeline({defaults: {ease}})
      .fromTo(panel, {autoAlpha: 0}, {autoAlpha: 1, duration: .18})
      .from(header, {y: 18, autoAlpha: 0, duration: .38, stagger: .055}, 0)
      .from(content, {y: 14, autoAlpha: 0, duration: .36, stagger: .045}, .12);
  };

  const step = (index) => {
    runtimeState.flowIndex = Math.max(runtimeState.flowIndex, index);
    const steps = [...document.querySelectorAll('.flow-step')];
    steps.forEach((element, position) => element.classList.toggle('active', position <= runtimeState.flowIndex));
    const progress = runtimeState.flowIndex / Math.max(1, steps.length - 1);
    animate('#flow-track', {scaleX: progress, duration: .65, ease: 'power2.inOut'});
    if (steps[index]) {
      gsap.fromTo(steps[index].querySelector('i'), {scale: .7}, {scale: 1, duration: .5, ease: 'back.out(2)'});
    }
  };

  const stateChange = (target, value, tone = 'normal') => {
    const element = document.querySelector(target);
    element.textContent = value;
    if (!enabled) return;
    gsap.fromTo(
      element,
      {y: 7, autoAlpha: 0, color: tone === 'danger' ? '#c63c25' : '#365be5'},
      {y: 0, autoAlpha: 1, color: '', duration: .42, ease}
    );
  };

  const reveal = (targets) => animate(targets, {y: 0, autoAlpha: 1, duration: .36, stagger: .045, ease});

  const flash = (target, color = '#d9ff43') => {
    if (!enabled) return;
    gsap.timeline()
      .to(target, {backgroundColor: color, duration: .12})
      .to(target, {backgroundColor: '', duration: .65, ease});
  };

  const configureGraph = () => {
    const stage = document.querySelector('#graph-stage');
    const core = document.querySelector('#graph-core');
    if (!enabled || !stage || !core) return;
    const xTo = gsap.quickTo(core, 'x', {duration: .45, ease});
    const yTo = gsap.quickTo(core, 'y', {duration: .45, ease});
    const rotateXTo = gsap.quickTo(stage, 'rotationX', {duration: .55, ease});
    const rotateYTo = gsap.quickTo(stage, 'rotationY', {duration: .55, ease});
    stage.addEventListener('pointermove', (event) => {
      const bounds = stage.getBoundingClientRect();
      const x = (event.clientX - bounds.left) / bounds.width - .5;
      const y = (event.clientY - bounds.top) / bounds.height - .5;
      xTo(x * 18); yTo(y * 18); rotateXTo(y * -2); rotateYTo(x * 2);
    });
    stage.addEventListener('pointerleave', () => {
      xTo(0); yTo(0); rotateXTo(0); rotateYTo(0);
    });
  };

  return {boot, enterPanel, step, stateChange, reveal, flash, configureGraph, version: gsap.version};
})();

window.__LESR_MOTION__ = {engine: 'GSAP', version: motion.version, semantics: 'state-causality-focus'};

const toast = (message) => {
  const element = document.querySelector('#toast');
  element.querySelector('span').textContent = message;
  gsap.killTweensOf(element);
  gsap.timeline()
    .to(element, {y: 0, autoAlpha: 1, duration: .32, ease: 'power3.out'})
    .to(element, {y: 20, autoAlpha: 0, duration: .28, ease: 'power2.in'}, '+=2.8');
};

async function api(url, options = {}) {
  const method = options.method || 'GET';
  const headers = {'Accept': 'application/json', ...(options.headers || {})};
  if (method !== 'GET') {
    headers['X-LESR-CSRF'] = csrf;
    headers['Content-Type'] = 'application/json';
  }
  const response = await fetch(url, {...options, headers});
  if (response.status === 401) location.href = '/locked';
  const body = await response.json();
  if (!response.ok) {
    const detail = body.detail?.error?.message || body.detail?.message || body.error?.message || body.detail;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail || body));
  }
  return body;
}

const show = (selector, value) => {
  const output = document.querySelector(selector);
  output.textContent = JSON.stringify(value, null, 2);
  motion.flash(output, '#26302b');
};

const selectPanel = (name) => {
  const button = document.querySelector(`.nav-item[data-panel="${name}"]`);
  if (button) button.click();
};

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
  const current = document.querySelector('.panel.active');
  const panel = document.querySelector(`#${button.dataset.panel}`);
  if (current === panel) return;
  document.querySelectorAll('.nav-item').forEach((element) => element.classList.remove('active'));
  document.querySelectorAll('.panel').forEach((element) => element.classList.remove('active'));
  button.classList.add('active');
  panel.classList.add('active');
  motion.enterPanel(panel);
}));

document.querySelectorAll('[data-panel-link]').forEach((link) => link.addEventListener('click', (event) => {
  event.preventDefault();
  selectPanel(link.dataset.panelLink);
}));

async function health() {
  try {
    const value = await api('/api/health');
    const authority = value.authority.toUpperCase();
    motion.stateChange('#authority-state', authority);
    motion.stateChange('#plate-authority', authority);
    motion.stateChange('#health-canonical', value.canonical);
    motion.stateChange('#health-projection', value.projection);
    motion.stateChange('#health-manifest', value.manifest);
    motion.stateChange('#health-workspaces', String(value.open_workspaces));
    document.querySelectorAll('.metric').forEach((metric) => metric.classList.add('is-live'));
  } catch (error) { toast(error.message); }
}

document.querySelector('#query-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const text = new FormData(event.target).get('text');
  try {
    const value = await api(`/api/query?text=${encodeURIComponent(text)}`);
    const results = document.querySelector('#query-results');
    results.replaceChildren();
    value.items.forEach((item) => {
      const row = document.createElement('button');
      row.className = 'result-item';
      const title = document.createElement('b');
      title.textContent = item.human_key || item.resource_type || 'RESOURCE';
      const resourceUid = document.createElement('code');
      resourceUid.textContent = item.revision_uid || item.entity_uid || item.uid || '';
      const kind = document.createElement('span');
      kind.textContent = item.kind || '';
      row.append(title, resourceUid, kind);
      row.addEventListener('click', () => {
        document.querySelectorAll('.result-item').forEach((element) => element.removeAttribute('aria-current'));
        row.setAttribute('aria-current', 'true');
        motion.flash('#graph-core');
      });
      results.append(row);
    });
    if (!value.items.length) {
      const empty = document.createElement('div');
      empty.className = 'empty-line'; empty.textContent = 'No exact matches.'; results.append(empty);
    } else {
      gsap.set(results.children, {y: 14, autoAlpha: 0});
      motion.reveal(results.children);
    }
    motion.step(0);
  } catch (error) { toast(error.message); }
});

document.querySelector('#context-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/context/plan', {method: 'POST', body: JSON.stringify(data)});
    show('#context-output', value);
    motion.step(1);
  } catch (error) { toast(error.message); }
});

document.querySelector('#sign-form [name="package_uid"]').addEventListener('change', async (event) => {
  try {
    const value = await api(`/api/review-package/${encodeURIComponent(event.target.value)}`);
    motion.stateChange('#sign-package', value.package_hash);
    motion.stateChange('#sign-model', value.effective_model_hash);
    motion.stateChange('#sign-scope', value.candidate_scope.join(', '));
    motion.stateChange('#sign-role', `${value.stages.map((stage) => `${stage.stage}: ${stage.role}`).join(', ')} / ${value.signature_expiry_minutes} min`);
    document.querySelector('#sign-output').textContent = `Conditions: ${JSON.stringify(value.conditions)}`;
  } catch (error) {
    document.querySelector('#sign-package').textContent = 'Not found';
    toast(error.message);
  }
});

document.querySelector('#sign-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  data.human_confirm = data.human_confirm === 'on';
  try {
    const value = await api('/api/sign', {method: 'POST', body: JSON.stringify(data)});
    runtimeState.approval = value.approval;
    show('#sign-output', value);
    motion.step(4);
    motion.flash('.sign-seal');
  } catch (error) { toast(error.message); }
});

const uid = () => {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let milliseconds = BigInt(Date.now());
  for (let index = 5; index >= 0; index -= 1) {
    bytes[index] = Number(milliseconds & 0xffn);
    milliseconds >>= 8n;
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
};

const envelope = (operation, overrides = {}) => ({
  workspace_uid: runtimeState.workspaceUid || overrides.workspaceUid || uid(),
  expected_base: runtimeState.base || overrides.base,
  idempotency_key: uid(),
  actor: runtimeState.actor || overrides.actor,
  delegation_uid: runtimeState.delegationUid || overrides.delegationUid,
  dry_run: false,
  risk_class: overrides.riskClass || 'high',
  operation,
});

const advanceWorkspace = (state, progress) => {
  motion.stateChange('#workspace-state', state);
  gsap.to('#workspace-progress', {scaleX: progress, duration: .55, ease: 'power2.inOut'});
};

const paintDecision = (validation) => {
  const decision = validation.operation_decision;
  const strip = document.querySelector('#decision-strip');
  strip.dataset.disposition = decision.disposition;
  strip.querySelector('strong').textContent = decision.disposition.replaceAll('_', ' ').toUpperCase();
  strip.querySelector('small').textContent = decision.blocking_finding_uids.length
    ? `${decision.blocking_finding_uids.length} unresolved enforcement blocker(s).`
    : `${validation.finding_hashes.length} finding(s); zero unresolved blockers.`;
  motion.flash(strip, decision.blocking_finding_uids.length ? '#efc7be' : '#d8efc8');
};

document.querySelector('#workspace-open-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  runtimeState.workspaceUid = uid();
  runtimeState.base = data.expected_base;
  runtimeState.actor = data.actor;
  runtimeState.delegationUid = data.delegation_uid;
  runtimeState.configurationUid = data.configuration_uid;
  try {
    const value = await api('/api/workspace/open', {
      method: 'POST',
      body: JSON.stringify(envelope({type: 'open_workspace', configuration_uid: data.configuration_uid})),
    });
    document.querySelector('#workspace-uid').textContent = runtimeState.workspaceUid;
    advanceWorkspace('EDITABLE', .22);
    show('#workspace-output', value);
    motion.step(2);
  } catch (error) { toast(error.message); }
});

document.querySelector('#workspace-edit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.workspaceUid) return toast('Open a Workspace first.');
  const data = Object.fromEntries(new FormData(event.target));
  const objectUid = data.object_uid || uid();
  const operation = {
    operation_type: 'create_object',
    working_copy: {
      workspace_uid: runtimeState.workspaceUid,
      object_uid: objectUid,
      base_revision_uid: null,
      base_revision_number: 0,
      human_key: data.human_key,
      kind: data.kind,
      facets: [],
      effective_model_hash: 'bound-by-runtime',
      delegation_uid: runtimeState.delegationUid,
      draft_fields: [{path: '/statement', value: data.statement}],
      draft_fragments: [], relation_proposals: [], edit_log: [],
    },
  };
  try {
    const value = await api('/api/workspace/edit', {method: 'POST', body: JSON.stringify(envelope(operation))});
    advanceWorkspace('DIRTY / CHECKPOINTED', .52);
    show('#workspace-output', value);
    motion.flash('#workspace-edit-form');
  } catch (error) { toast(error.message); }
});

document.querySelector('#workspace-submit-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/workspace/submit', {
      method: 'POST',
      body: JSON.stringify(envelope({
        configuration_uid: runtimeState.configurationUid,
        evaluation_time: data.evaluation_time,
        maximum_depth: Number(data.maximum_depth),
      })),
    });
    runtimeState.packageUid = value.review_package.package_uid;
    advanceWorkspace('SUBMITTED / READ-ONLY', 1);
    paintDecision(value.validation);
    const packageInput = document.querySelector('#sign-form [name="package_uid"]');
    packageInput.value = runtimeState.packageUid;
    packageInput.dispatchEvent(new Event('change'));
    show('#workspace-output', value);
    motion.step(3);
    selectPanel('review');
  } catch (error) { toast(error.message); }
});

document.querySelector('#apply-candidate').addEventListener('click', async () => {
  if (!runtimeState.approval || !runtimeState.packageUid) return toast('A human signature is required.');
  try {
    const value = await api('/api/apply', {
      method: 'POST',
      body: JSON.stringify(envelope({
        review_package_uid: runtimeState.packageUid,
        signed_approvals: [runtimeState.approval],
        evaluation_time: new Date().toISOString(),
      })),
    });
    runtimeState.base = value.result_commit;
    runtimeState.configurationUid = value.configuration_uid;
    runtimeState.approval = null;
    const baselineConfiguration = document.querySelector('#baseline-prepare-form [name="configuration_uid"]');
    baselineConfiguration.value = value.configuration_uid;
    show('#sign-output', value);
    motion.step(5);
    selectPanel('baseline');
  } catch (error) { toast(error.message); }
});

document.querySelector('#baseline-prepare-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/baseline/prepare', {
      method: 'POST', body: JSON.stringify(envelope({configuration_uid: data.configuration_uid, evaluation_time: data.evaluation_time}))
    });
    runtimeState.packageUid = value.review_package.package_uid;
    document.querySelector('#baseline-apply-form [name="review_package_uid"]').value = runtimeState.packageUid;
    const packageInput = document.querySelector('#sign-form [name="package_uid"]');
    packageInput.value = runtimeState.packageUid;
    packageInput.dispatchEvent(new Event('change'));
    show('#baseline-output', value);
    selectPanel('review');
  } catch (error) { toast(error.message); }
});

document.querySelector('#baseline-apply-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!runtimeState.approval) return toast('Sign the Baseline Review Package first.');
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/baseline/apply', {
      method: 'POST', body: JSON.stringify(envelope({
        review_package_uid: data.review_package_uid,
        signed_approvals: [runtimeState.approval],
        evaluation_time: data.evaluation_time,
        tag_name: data.tag_name || null,
      }))
    });
    show('#baseline-output', value);
    runtimeState.base = value.result_commit;
    runtimeState.approval = null;
  } catch (error) {
    show('#baseline-output', {error: error.message});
    toast(error.message);
  }
});

document.querySelector('#refresh-tasks').addEventListener('click', async () => {
  try {
    const value = await api('/api/tasks');
    const list = document.querySelector('#task-results');
    list.replaceChildren();
    value.forEach((task) => {
      const card = document.createElement('article'); card.className = 'task-card';
      const title = document.createElement('b'); title.textContent = task.task_type;
      const state = document.createElement('code'); state.textContent = `${task.state} / ${task.progress}%`;
      const progress = document.createElement('i'); progress.style.setProperty('--progress', String(task.progress / 100));
      card.append(title, state, progress); list.append(card);
    });
    if (!value.length) {
      const empty = document.createElement('div'); empty.className = 'empty-line'; empty.textContent = 'Queue empty.'; list.append(empty);
    }
    gsap.set(list.children, {y: 12, autoAlpha: 0});
    motion.reveal(list.children);
  } catch (error) { toast(error.message); }
});

document.querySelector('#gc-plan').addEventListener('click', async () => {
  try {
    const value = await api('/api/maintenance/gc', {method: 'POST', body: '{}'});
    show('#maintenance-output', value);
  } catch (error) { toast(error.message); }
});

document.querySelector('#lock-button').addEventListener('click', async () => {
  await api('/api/lock', {method: 'POST', body: '{}'});
  location.href = '/locked';
});

motion.boot();
motion.configureGraph();
health();
