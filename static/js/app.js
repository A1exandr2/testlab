function toast(message, error = false) {
  const el = document.createElement('div');
  el.className = error ? 'toast error' : 'toast';
  el.textContent = message;
  document.querySelector('#toast').append(el);
  setTimeout(() => el.remove(), 5000);
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
