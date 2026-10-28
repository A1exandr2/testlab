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
