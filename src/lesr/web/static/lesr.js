const csrf = document.querySelector('meta[name="csrf-token"]').content;
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
  if (!response.ok) throw new Error(body.detail || body.error?.message || 'Request failed');
  return body;
}

document.querySelectorAll('.nav-item').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('.nav-item,.panel').forEach((element) => element.classList.remove('active'));
  button.classList.add('active');
  document.querySelector(`#${button.dataset.panel}`).classList.add('active');
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
    document.querySelector('#query-results').innerHTML = value.items.map((item) => `<button class="result-item"><b>${item.human_key || item.resource_type || 'RESOURCE'}</b><code>${item.revision_uid || item.entity_uid || item.uid || ''}</code><span>${item.kind || ''}</span></button>`).join('') || '<p>No exact matches.</p>';
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
    document.querySelector('#sign-output').textContent = JSON.stringify(value, null, 2);
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
