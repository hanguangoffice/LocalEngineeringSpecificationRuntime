const csrf = document.querySelector('meta[name="csrf-token"]').content;
const runtimeState = {
  workspaceUid: null, base: null, actor: null, delegationUid: null,
  configurationUid: null, packageUid: null, approval: null,
};
const toast = (message) => {
  const element = document.querySelector('#toast');
  element.textContent = message;
  element.classList.add('show');
  setTimeout(() => element.classList.remove('show'), 2600);
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

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('.nav-item,.panel').forEach((element) => element.classList.remove('active'));
  button.classList.add('active');
  const panel = document.querySelector(`#${button.dataset.panel}`);
  panel.classList.add('active');
  if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    panel.animate(
      [{opacity: 0, transform: 'translateY(12px)'}, {opacity: 1, transform: 'translateY(0)'}],
      {duration: 360, easing: 'cubic-bezier(.22,1,.36,1)'}
    );
  }
}));

async function health() {
  try {
    const value = await api('/api/health');
    document.querySelector('#authority-state').textContent = value.authority.toUpperCase();
    document.querySelector('#health-canonical').textContent = value.canonical;
    document.querySelector('#health-projection').textContent = value.projection;
    document.querySelector('#health-manifest').textContent = value.manifest;
    document.querySelector('#health-workspaces').textContent = value.open_workspaces;
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
      const uid = document.createElement('code');
      uid.textContent = item.revision_uid || item.entity_uid || item.uid || '';
      const kind = document.createElement('span');
      kind.textContent = item.kind || '';
      row.append(title, uid, kind);
      results.append(row);
    });
    if (!value.items.length) results.textContent = 'No exact matches.';
  } catch (error) { toast(error.message); }
});

document.querySelector('#context-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  try {
    const value = await api('/api/context/plan', {method: 'POST', body: JSON.stringify(data)});
    document.querySelector('#context-output').textContent = JSON.stringify(value, null, 2);
  } catch (error) { toast(error.message); }
});

document.querySelector('#sign-form [name="package_uid"]').addEventListener('change', async (event) => {
  try {
    const value = await api(`/api/review-package/${encodeURIComponent(event.target.value)}`);
    document.querySelector('#sign-package').textContent = value.package_hash;
    document.querySelector('#sign-model').textContent = value.effective_model_hash;
    document.querySelector('#sign-scope').textContent = value.candidate_scope.join(', ');
    document.querySelector('#sign-role').textContent = `${value.stages.map((stage) => `${stage.stage}: ${stage.role}`).join(', ')} / ${value.signature_expiry_minutes} min`;
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
    document.querySelector('#sign-output').textContent = JSON.stringify(value, null, 2);
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
const show = (selector, value) => {
  document.querySelector(selector).textContent = JSON.stringify(value, null, 2);
};
const selectPanel = (name) => document.querySelector(`.nav-item[data-panel="${name}"]`).click();

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
    document.querySelector('#workspace-state').textContent = 'EDITABLE';
    show('#workspace-output', value);
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
    show('#workspace-output', value);
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
    document.querySelector('#workspace-state').textContent = 'SUBMITTED';
    document.querySelector('#sign-form [name="package_uid"]').value = runtimeState.packageUid;
    document.querySelector('#sign-form [name="package_uid"]').dispatchEvent(new Event('change'));
    show('#workspace-output', value);
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
    runtimeState.approval = null;
    show('#sign-output', value);
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
    document.querySelector('#sign-form [name="package_uid"]').value = runtimeState.packageUid;
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
  } catch (error) { toast(error.message); }
});

document.querySelector('#refresh-tasks').addEventListener('click', async () => {
  try {
    const value = await api('/api/tasks');
    document.querySelector('#task-results').innerHTML = value.map((task) => `<div class="result-item"><b>${task.task_type}</b><code>${task.state} / ${task.progress}%</code></div>`).join('') || '<p>Queue empty.</p>';
  } catch (error) { toast(error.message); }
});

document.querySelector('#gc-plan').addEventListener('click', async () => {
  try {
    const value = await api('/api/maintenance/gc', {method: 'POST', body: '{}'});
    document.querySelector('#maintenance-output').textContent = JSON.stringify(value, null, 2);
  } catch (error) { toast(error.message); }
});

document.querySelector('#lock-button').addEventListener('click', async () => {
  await api('/api/lock', {method: 'POST', body: '{}'});
  location.href = '/locked';
});

health();
