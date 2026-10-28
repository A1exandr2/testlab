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
