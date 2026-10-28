'use strict';

const app = document.querySelector('#app');
const statusNames = {
  not_run: 'Не проверено', passed: 'Успешно', failed: 'Ошибка', blocked: 'Заблокировано'
};
const statusOrder = ['failed', 'blocked', 'not_run', 'passed'];
const nav = [['overview', 'Обзор'], ['checks', 'Проверки'], ['team', 'Участники']];
let me = null;
let csrf = '';
let state = null;
let page = 'overview';
let projectId = null;
let modal = null;
let authMode = 'login';
let snapshot = '';
let search = '';
let statusFilter = 'all';
let checkSort = 'newest';
let memberSort = 'name_asc';
let refreshSeq = 0;
let pendingRefreshes = 0;
let saving = false;
let syncError = false;

const esc = value => String(value ?? '').replace(/[&<>"']/g, c =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const date = value => value ? new Date(value).toLocaleString('ru-RU', {dateStyle: 'short', timeStyle: 'short'}) : '—';
const badge = status => `<span class="badge ${esc(status)}"><span class="status-dot"></span>${esc(statusNames[status])}</span>`;
const roleName = role => role === 'admin' ? 'Администратор' : 'Пользователь';

function toast(message, error = false) {
  const el = document.createElement('div');
  el.className = error ? 'toast error' : 'toast';
  el.textContent = message;
  document.querySelector('#toast').append(el);
  setTimeout(() => el.remove(), 5000);
}

async function api(path, data) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  const options = {credentials: 'same-origin', signal: controller.signal};
  if (data !== undefined) {
    options.method = 'POST';
    options.headers = {'Content-Type': 'application/json', 'X-CSRF-Token': csrf};
    options.body = JSON.stringify(data);
  }
  try {
    const response = await fetch('/api/' + path, options);
    const body = await response.json();
    if (!response.ok) {
      const error = new Error(body.error || 'Не удалось выполнить действие');
      error.status = response.status;
      throw error;
    }
    return body;
  } catch (error) {
    if (!error.status) throw new Error('Нет связи с сервером. Проверьте, что приложение запущено.');
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function input(label, key, {type = 'text', max = 200, min, autocomplete = '', placeholder = ''} = {}) {
  return `<label class="field" for="field-${key}"><span>${esc(label)}</span><input id="field-${key}" name="${key}" type="${type}" maxlength="${max}" ${min ? `minlength="${min}"` : ''} autocomplete="${autocomplete}" placeholder="${esc(placeholder)}" required></label>`;
}

function textarea(label, key, value = '', required = true) {
  return `<label class="field" for="field-${key}"><span>${esc(label)}</span><textarea id="field-${key}" name="${key}" maxlength="5000" ${required ? 'required' : ''}>${esc(value)}</textarea></label>`;
}

function options(items, selected) {
  return items.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
}

function resetSession() {
  ++refreshSeq;
  me = null;
  csrf = '';
  state = null;
  projectId = null;
  modal = null;
  snapshot = '';
  page = 'overview';
  search = '';
  statusFilter = 'all';
  checkSort = 'newest';
  memberSort = 'name_asc';
  syncError = false;
  authMode = 'login';
  renderAuth();
}

function renderAuth() {
  const register = authMode === 'register';
  app.innerHTML = `<main class="authpage"><section class="authbox">
    <div class="brand">Тест<span>Лаб</span></div>
    <h1>${register ? 'Создать аккаунт' : 'Войти в ТестЛаб'}</h1>
    <p class="muted">Проверяйте проект вместе и делитесь результатами.</p>
    <form id="authForm">
      ${register ? input('Ваше имя', 'name', {max: 80, autocomplete: 'name'}) : ''}
      ${input('Электронная почта', 'email', {type: 'email', max: 254, autocomplete: 'username'})}
      ${input('Пароль', 'password', {type: 'password', max: 128, min: register ? 10 : undefined, autocomplete: register ? 'new-password' : 'current-password'})}
      ${register ? '<p class="field-help">Пароль — от 10 символов.</p>' : ''}
      <p id="authError" class="form-error" role="alert"></p>
      <button class="btn primary" type="submit">${register ? 'Зарегистрироваться' : 'Войти'}</button>
    </form>
    <button class="linkbtn" id="toggleAuth">${register ? 'Уже есть аккаунт? Войти' : 'Создать аккаунт'}</button>
    <p class="notice">После регистрации создайте свою группу или попросите участника добавить вас по электронной почте.</p>
  </section></main>`;
  document.querySelector('#toggleAuth').onclick = () => {
    authMode = register ? 'login' : 'register';
    renderAuth();
  };
  document.querySelector('#authForm').onsubmit = async event => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form));
    form.querySelectorAll('button,input').forEach(el => { el.disabled = true; });
    document.querySelector('#toggleAuth').disabled = true;
    document.querySelector('#authError').textContent = '';
    try {
      const result = await api(register ? 'register' : 'login', data);
      me = result.user;
      csrf = result.csrf;
      projectId = null;
      page = 'overview';
      await refresh(true);
    } catch (error) {
      document.querySelector('#authError').textContent = error.message;
    } finally {
      form.querySelectorAll('button,input').forEach(el => { el.disabled = false; });
      const toggle = document.querySelector('#toggleAuth');
      if (toggle) toggle.disabled = false;
    }
  };
}

function render() {
  if (!me || !state) return;
  const active = document.activeElement;
  const focusId = active?.id;
  const selection = active?.tagName === 'INPUT' && active.type === 'search'
    ? [active.selectionStart, active.selectionEnd] : null;
  const selected = state.projects.find(project => project.id === state.project_id);
  app.innerHTML = `<div class="shell">
    <aside class="sidebar">
      <div class="brand">Тест<span>Лаб</span></div>
      <nav aria-label="Основная навигация">${nav.map(([id, label]) => `<button class="nav ${page === id ? 'active' : ''}" data-page="${id}" ${page === id ? 'aria-current="page"' : ''}>${label}</button>`).join('')}</nav>
      <div class="sidefoot"><strong>${esc(me.name)}</strong><span>${roleName(me.role)}</span><p>Одна группа.<br>Общие результаты.</p></div>
    </aside>
    <div class="main">
      <header class="topbar"><div><p class="eyebrow">Совместная проверка проекта</p><h1>${nav.find(([id]) => id === page)[1]}</h1></div>
        <button class="btn" id="logout">Выйти</button>
      </header>
      <main class="content">
        <div class="workspace-bar"><div>${selected ? `<label class="field compact" for="projectPicker"><span>Группа</span><select id="projectPicker">${state.projects.map(project => `<option value="${project.id}" ${project.id === projectId ? 'selected' : ''}>${esc(project.name)}</option>`).join('')}</select></label>` : '<span class="muted">Вы пока не состоите в группе</span>'}</div>
          <div class="workspace-actions"><span class="sync-status ${syncError ? 'offline' : ''}" id="syncStatus" role="status">${syncError ? 'Нет связи. Подключаемся…' : 'Обновляется автоматически'}</span><button class="btn" data-open="project">+ Новая группа</button></div>
        </div>
        ${selected ? (page === 'checks' ? checksPage() : page === 'team' ? teamPage() : overview()) : emptyWorkspace()}
      </main>
    </div>
  </div>${modal ? modalHtml() : ''}`;
  bind();
  if (focusId && !modal) {
    const target = document.getElementById(focusId);
    target?.focus({preventScroll: true});
    if (selection && target) target.setSelectionRange(...selection);
  }
}

function emptyWorkspace() {
  return `<section class="panel empty"><div class="empty-symbol" aria-hidden="true">＋</div>
    <h2>Создайте группу для совместной работы</h2>
    <p>Нажмите «Новая группа», затем добавьте участников по почте. Чтобы вступить в существующую группу, передайте её участнику вашу почту: <strong>${esc(me.email)}</strong>.</p></section>`;
}

function overview() {
  const m = state.metrics;
  const percent = m.total ? Math.round(100 * m.passed / m.total) : 0;
  let offset = 25;
  const colors = {passed: '#239a75', failed: '#d95568', blocked: '#d99a31', not_run: '#a3aec3'};
  const segments = ['passed', 'failed', 'blocked', 'not_run'].map(status => {
    const part = m.total ? 100 * m[status] / m.total : 0;
    const segment = `<circle cx="21" cy="21" r="15.915494309" fill="none" stroke="${colors[status]}" stroke-width="4" stroke-dasharray="${part} ${100-part}" stroke-dashoffset="${offset}"></circle>`;
    offset -= part;
    return segment;
  }).join('');
  return `<section class="intro"><div><h2>Всё о проверках вашей группы</h2><p class="muted">Добавляйте проверки, отмечайте результат и следите за прогрессом вместе.</p></div><button class="btn primary" data-open="check">+ Добавить проверку</button></section>
    <div class="metrics">${[['all','Все проверки',m.total], ...Object.entries(statusNames).map(([key,label]) => [key,label,m[key]])].map(([key,label,value]) => `<button class="metric ${key}" data-show-status="${key}" title="Показать проверки: ${label}"><span>${label}</span><strong>${value}</strong><small>Показать список →</small></button>`).join('')}</div>
    <section class="panel progress-panel"><div class="progress-copy"><p class="eyebrow">Результаты группы</p><h2>${m.total ? `${percent}% проверок выполнены успешно` : 'Начните с первой проверки'}</h2><p class="muted">${m.total ? 'Диаграмма показывает текущий результат каждой проверки. Изменения участников появляются автоматически.' : 'Создайте проверку, опишите шаги и ожидаемый результат. Затем откройте её и сохраните результат.'}</p>
      <div class="legend">${Object.entries(statusNames).map(([key,label]) => `<div><span class="legend-dot ${key}"></span><span>${label}</span><strong>${m[key]}</strong></div>`).join('')}</div>
    </div><div class="chart"><svg viewBox="0 0 42 42" role="img" aria-label="Успешно ${m.passed} из ${m.total}; ошибок ${m.failed}; заблокировано ${m.blocked}; не проверено ${m.not_run}"><circle cx="21" cy="21" r="15.915494309" fill="none" stroke="#edf1f7" stroke-width="4"></circle>${segments}<text x="21" y="21" text-anchor="middle" class="chart-value">${percent}%</text><text x="21" y="25" text-anchor="middle" class="chart-label">успешно</text></svg></div></section>`;
}

function sortedChecks() {
  const needle = search.trim().toLocaleLowerCase('ru');
  const items = state.checks.filter(check => (!needle || check.title.toLocaleLowerCase('ru').includes(needle))
    && (statusFilter === 'all' || check.status === statusFilter));
  return items.sort((a,b) => {
    if (checkSort === 'oldest') return a.id - b.id;
    if (checkSort === 'title_asc') return a.title.localeCompare(b.title, 'ru') || a.id - b.id;
    if (checkSort === 'title_desc') return b.title.localeCompare(a.title, 'ru') || a.id - b.id;
    if (checkSort === 'status') return statusOrder.indexOf(a.status)-statusOrder.indexOf(b.status) || b.id-a.id;
    return b.id - a.id;
  });
}

function checkList() {
  const items = sortedChecks();
  if (!items.length) return `<div class="empty"><h3>${state.checks.length ? 'Ничего не найдено' : 'Проверок пока нет'}</h3><p>${state.checks.length ? 'Измените название в поиске или выберите другой результат.' : 'Нажмите «Добавить проверку», чтобы начать.'}</p></div>`;
  return `<div class="tablewrap"><table class="table"><thead><tr><th scope="col">Проверка</th><th scope="col">Результат</th><th scope="col">Последнее изменение</th><th scope="col">Действие</th></tr></thead><tbody>${items.map(check => `<tr><td><strong>${esc(check.title)}</strong><p class="cell-sub">${esc(check.steps.length > 95 ? check.steps.slice(0,95)+'…' : check.steps)}</p></td><td>${badge(check.status)}</td><td><span>${esc(check.updated_by || check.creator)}</span><p class="cell-sub">${date(check.updated_at || check.created_at)}</p></td><td><button class="btn small" data-check="${check.id}" aria-label="Открыть проверку: ${esc(check.title)}">Открыть</button></td></tr>`).join('')}</tbody></table></div>`;
}

function checksPage() {
  return `<section class="panel"><div class="sectionhead"><div><h2>Проверки группы</h2><p class="muted">Откройте проверку, выполните шаги и сохраните результат.</p></div><button class="btn primary" data-open="check">+ Добавить проверку</button></div>
    <div class="list-tools"><label class="field" for="checkSearch"><span>Поиск по названию</span><input id="checkSearch" type="search" value="${esc(search)}" placeholder="Введите название"></label>
      <label class="field" for="statusFilter"><span>Результат</span><select id="statusFilter">${options([['all','Все результаты'],...Object.entries(statusNames)],statusFilter)}</select></label>
      <label class="field" for="checkSort"><span>Сортировка</span><select id="checkSort">${options([['newest','Сначала новые'],['oldest','Сначала старые'],['title_asc','Название: А–Я'],['title_desc','Название: Я–А'],['status','Сначала ошибки']],checkSort)}</select></label></div>
    <p class="list-count muted" id="checkCount">Показано ${sortedChecks().length} из ${state.checks.length}</p><div id="checkList">${checkList()}</div></section>`;
}

function sortedMembers() {
  return [...state.users].sort((a,b) => {
    if (memberSort === 'newest') return b.joined_at.localeCompare(a.joined_at) || b.id-a.id;
    if (memberSort === 'oldest') return a.joined_at.localeCompare(b.joined_at) || a.id-b.id;
    if (memberSort === 'name_desc') return b.name.localeCompare(a.name,'ru') || a.id-b.id;
    return a.name.localeCompare(b.name,'ru') || a.id-b.id;
  });
}

function teamPage() {
  return `<section class="panel"><div class="sectionhead"><div><h2>Участники группы</h2><p class="muted">Любой участник группы может добавить зарегистрированного пользователя по электронной почте.</p></div><button class="btn primary" data-open="member">+ Добавить участника</button></div>
    <div class="team-tools"><span class="muted">Всего участников: ${state.users.length}</span><label class="field compact" for="memberSort"><span>Сортировка</span><select id="memberSort">${options([['name_asc','Имя: А–Я'],['name_desc','Имя: Я–А'],['newest','Сначала новые'],['oldest','Сначала старые']],memberSort)}</select></label></div>
    <div class="tablewrap"><table class="table"><thead><tr><th scope="col">Имя</th><th scope="col">Электронная почта</th><th scope="col">Роль</th><th scope="col">Дата добавления</th></tr></thead><tbody>${sortedMembers().map(user => `<tr><td><strong>${esc(user.name)}</strong>${user.id === me.id ? '<span class="you">Вы</span>' : ''}</td><td>${esc(user.email)}</td><td><span class="role-badge ${user.role === 'admin' ? 'admin' : ''}">${roleName(user.role)}</span></td><td>${date(user.joined_at)}</td></tr>`).join('')}</tbody></table></div></section>`;
}

function modalHtml() {
  let title, body, submit;
  if (modal.type === 'project') {
    title = 'Новая группа';
    body = input('Название группы', 'name', {max: 100});
    submit = 'Создать группу';
  } else if (modal.type === 'member') {
    title = 'Добавить участника';
    body = '<p class="muted">Пользователь должен сначала зарегистрироваться. После добавления он увидит общие проверки.</p>' + input('Электронная почта пользователя', 'email', {type: 'email', max: 254});
    submit = 'Добавить участника';
  } else if (modal.type === 'check') {
    title = 'Новая проверка';
    body = input('Название проверки', 'title') + textarea('Шаги проверки', 'steps') + textarea('Ожидаемый результат', 'expected');
    submit = 'Добавить проверку';
  } else {
    const check = modal.check;
    title = check.title;
    body = `<div class="check-meta">${badge(check.status)}<span class="muted">Создал: ${esc(check.creator)}</span></div>
      ${check.preconditions ? `<div class="detail"><h3>Предусловия</h3><p>${esc(check.preconditions)}</p></div>` : ''}
      <div class="detail"><h3>Шаги проверки</h3><p>${esc(check.steps)}</p></div>
      <div class="detail"><h3>Ожидаемый результат</h3><p>${esc(check.expected)}</p></div>
      ${check.updated_by ? `<p class="field-help">Последний результат сохранил(а) ${esc(check.updated_by)} · ${date(check.updated_at)}</p>` : ''}
      <div class="result-form"><h3>Результат проверки</h3><label class="field" for="field-status"><span>Выберите результат</span><select id="field-status" name="status">${options(Object.entries(statusNames),check.status)}</select></label>${textarea('Комментарий (необязательно)', 'actual', check.actual, false)}</div>`;
    submit = 'Сохранить результат';
  }
  return `<div class="modalback" id="modalBack"><section class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle" tabindex="-1"><h2 id="modalTitle">${esc(title)}</h2>
    <form id="entityForm"><div class="formfields">${body}</div><p id="modalError" class="form-error" role="alert"></p><div class="actions"><button type="button" class="btn" id="cancelModal">${modal.type === 'result' ? 'Закрыть' : 'Отмена'}</button><button type="submit" class="btn primary">${submit}</button></div></form></section></div>`;
}

function openModal(value) {
  modal = value;
  render();
  document.querySelector('.modal input, .modal select, .modal textarea')?.focus({preventScroll: true});
}

function closeModal() {
  if (saving) return;
  modal = null;
  render();
}

function bindCheckButtons() {
  document.querySelectorAll('[data-check]').forEach(button => {
    button.onclick = () => {
      const check = state.checks.find(item => item.id === Number(button.dataset.check));
      if (check) openModal({type: 'result', check: {...check}});
    };
  });
}

function updateCheckList() {
  document.querySelector('#checkList').innerHTML = checkList();
  document.querySelector('#checkCount').textContent = `Показано ${sortedChecks().length} из ${state.checks.length}`;
  bindCheckButtons();
}

function bind() {
  document.querySelectorAll('[data-page]').forEach(button => {
    button.onclick = () => { page = button.dataset.page; render(); };
  });
  document.querySelectorAll('[data-open]').forEach(button => {
    button.onclick = () => openModal({type: button.dataset.open});
  });
  document.querySelectorAll('[data-show-status]').forEach(button => {
    button.onclick = () => {
      statusFilter = button.dataset.showStatus;
      search = '';
      page = 'checks';
      render();
    };
  });
  document.querySelector('#projectPicker')?.addEventListener('change', async event => {
    const nextProject = Number(event.target.value);
    const picker = event.target;
    const content = document.querySelector('.content');
    picker.disabled = true;
    content.inert = true;
    try {
      // Commit the selected group only after receiving its complete state.
      await refresh(true, nextProject);
    } catch (error) {
      picker.value = String(projectId);
      toast(error.message, true);
    } finally {
      picker.disabled = false;
      content.inert = false;
    }
  });
  document.querySelector('#logout').onclick = async event => {
    event.currentTarget.disabled = true;
    try { await api('logout', {}); resetSession(); }
    catch (error) { toast(error.message, true); document.querySelector('#logout').disabled = false; }
  };
  document.querySelector('#checkSearch')?.addEventListener('input', event => {
    search = event.target.value;
    updateCheckList();
  });
  document.querySelector('#statusFilter')?.addEventListener('change', event => {
    statusFilter = event.target.value;
    updateCheckList();
  });
  document.querySelector('#checkSort')?.addEventListener('change', event => {
    checkSort = event.target.value;
    updateCheckList();
  });
  document.querySelector('#memberSort')?.addEventListener('change', event => {
    memberSort = event.target.value;
    render();
  });
  bindCheckButtons();
  document.querySelector('#cancelModal')?.addEventListener('click', closeModal);
  document.querySelector('#modalBack')?.addEventListener('click', event => {
    if (event.target.id === 'modalBack') closeModal();
  });
  document.querySelector('#entityForm')?.addEventListener('submit', saveModal);
}

async function saveModal(event) {
  event.preventDefault();
  if (saving) return;
  const form = event.currentTarget;
  const data = Object.fromEntries(new FormData(form));
  const type = modal.type;
  if (type !== 'project') data.project_id = projectId;
  if (type === 'result') data.check_id = modal.check.id;
  const path = {project: 'projects', member: 'members', check: 'checks', result: 'checks/result'}[type];
  saving = true;
  form.querySelectorAll('button,input,textarea,select').forEach(el => { el.disabled = true; });
  document.querySelector('#modalError').textContent = '';
  try {
    const result = await api(path, data);
    saving = false;
    modal = null;
    if (type === 'check') { page = 'checks'; search = ''; statusFilter = 'all'; }
    try {
      await refresh(true, type === 'project' ? result.id : projectId);
      toast({project: 'Группа создана', member: 'Участник добавлен', check: 'Проверка добавлена', result: 'Результат сохранён'}[type]);
    } catch (error) {
      render();
      toast('Данные сохранены. Список обновится после восстановления связи.', true);
    }
  } catch (error) {
    const errorField = document.querySelector('#modalError');
    if (errorField) errorField.textContent = error.message;
    else toast(error.message, true);
  } finally {
    saving = false;
    form.querySelectorAll('button,input,textarea,select').forEach(el => { el.disabled = false; });
  }
}

async function refresh(force = false, targetProject = projectId) {
  if (!me) return;
  const seq = ++refreshSeq;
  const userId = me.id;
  ++pendingRefreshes;
  try {
    const data = await api('state' + (targetProject ? '?project=' + targetProject : ''));
    if (!me || me.id !== userId || seq !== refreshSeq) return;
    const changedGroup = projectId !== data.project_id;
    if (data.user) me = data.user;
    state = data;
    projectId = data.project_id;
    if (changedGroup) { search = ''; statusFilter = 'all'; }
    syncError = false;
    const serialized = JSON.stringify(data);
    if (!modal && (force || serialized !== snapshot)) {
      snapshot = serialized;
      render();
    }
    const sync = document.querySelector('#syncStatus');
    if (sync) { sync.textContent = 'Обновляется автоматически'; sync.classList.remove('offline'); }
  } catch (error) {
    if (seq !== refreshSeq || !me || me.id !== userId) return;
    if (error.status === 403 && error.message.startsWith('Войдите')) {
      resetSession();
      return;
    }
    syncError = true;
    const sync = document.querySelector('#syncStatus');
    if (sync) { sync.textContent = 'Нет связи. Подключаемся…'; sync.classList.add('offline'); }
    if (force) throw error;
  } finally {
    --pendingRefreshes;
  }
}

async function start() {
  try {
    const result = await api('me');
    me = result.user;
    csrf = result.csrf;
    await refresh(true);
  } catch {
    renderAuth();
  }
}

document.addEventListener('keydown', event => {
  if (!modal) return;
  if (event.key === 'Escape') closeModal();
  if (event.key === 'Tab') {
    const fields = [...document.querySelectorAll('.modal button:not(:disabled), .modal input:not(:disabled), .modal textarea:not(:disabled), .modal select:not(:disabled)')];
    const first = fields[0], last = fields[fields.length-1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
});

document.addEventListener('visibilitychange', () => {
  if (me && !pendingRefreshes && document.visibilityState === 'visible') refresh();
});

start();
setInterval(() => {
  if (me && document.visibilityState === 'visible' && !saving && !pendingRefreshes) refresh();
}, 3000);
