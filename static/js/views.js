function input(label, key, {type = 'text', max = 200, min, autocomplete = '', placeholder = ''} = {}) {
  return `<label class="field" for="field-${key}"><span>${esc(label)}</span><input id="field-${key}" name="${key}" type="${type}" maxlength="${max}" ${min ? `minlength="${min}"` : ''} autocomplete="${autocomplete}" placeholder="${esc(placeholder)}" required></label>`;
}

function textarea(label, key, value = '', required = true) {
  return `<label class="field" for="field-${key}"><span>${esc(label)}</span><textarea id="field-${key}" name="${key}" maxlength="5000" ${required ? 'required' : ''}>${esc(value)}</textarea></label>`;
}

function options(items, selected) {
  return items.map(([value, label]) => `<option value="${esc(value)}" ${value === selected ? 'selected' : ''}>${esc(label)}</option>`).join('');
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
