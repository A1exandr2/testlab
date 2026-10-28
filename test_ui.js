// Exercise the real view/filter functions without a browser or third-party packages.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const app = {innerHTML: ''};
const sandbox = {
  document: {querySelector: () => app, addEventListener() {}},
  setInterval() {}, setTimeout() {}, clearTimeout() {}, console
};
vm.createContext(sandbox);
const source = fs.readFileSync(__dirname+'/app.js', 'utf8').replace(/^start\(\);$/m, '');
vm.runInContext(source, sandbox);
const run = code => vm.runInContext(code, sandbox);
run(`me={id:1,name:'Админ',role:'admin'};state={project_role:'admin',metrics:{total:4,passed:1,failed:1,blocked:1,not_run:1},checks:[
  {id:1,title:'Яблоко',steps:'Шаг',status:'passed',creator:'Автор',created_at:'2026-10-01'},
  {id:2,title:'Берёза',steps:'Шаг',status:'failed',creator:'Автор',created_at:'2026-10-02'},
  {id:3,title:'Апельсин',steps:'Шаг',status:'blocked',creator:'Автор',created_at:'2026-10-03'},
  {id:4,title:'<script>alert(1)</script>',steps:'Шаг',status:'not_run',creator:'Автор',created_at:'2026-10-04'}
],users:[{id:1,name:'Яна',email:'admin@example.test',role:'admin',joined_at:'2026-10-01'},{id:2,name:'Анна',email:'user@example.test',role:'member',joined_at:'2026-10-02'}]};`);
assert.equal(run('sortedChecks().map(c=>c.id).join()'), '4,3,2,1');
assert.equal(run("checkSort='oldest';sortedChecks().map(c=>c.id).join()"), '1,2,3,4');
assert.equal(run("search='бер';sortedChecks().map(c=>c.id).join()"), '2');
assert.equal(run("search='';statusFilter='passed';sortedChecks().map(c=>c.id).join()"), '1');
assert.equal(run("statusFilter='all';checkSort='status';sortedChecks().map(c=>c.id).join()"), '2,3,4,1');
assert.equal(run("checkSort='title_asc';search='е';sortedChecks().map(c=>c.id).join()"), '3,2');
assert.equal(run("checkSort='title_desc';sortedChecks().map(c=>c.id).join()"), '2,3');
assert.equal(run("search='';memberSort='name_asc';sortedMembers().map(c=>c.id).join()"), '2,1');
assert.equal(run("memberSort='newest';sortedMembers().map(c=>c.id).join()"), '2,1');
assert.ok(run('overview()').includes('25%'));
assert.equal((run('overview()').match(/data-show-status=/g)||[]).length, 5);
assert.ok(run('checkList()').includes('&lt;script&gt;'));
assert.ok(!run('checkList()').includes('<script>'));
assert.ok(run('teamPage()').includes('data-open="member"'));
assert.ok(run("me.role='user';state.project_role='member';teamPage()").includes('data-open="member"'));
assert.ok(run("me.email='user@example.test';emptyWorkspace()").includes('Нажмите «Новая группа»'));
assert.ok(run("search='нет такого названия';checkList()").includes('Ничего не найдено'));
console.log('UI: поиск, 5 сортировок проверок, сортировка участников, фильтр, диаграмма и права — OK');
