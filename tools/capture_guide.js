#!/usr/bin/env node
// Capture the real UI in an isolated demo database, then rebuild the PDF.
// Run from the project directory: node tools/capture_guide.js
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const net = require('node:net');
const {spawn, spawnSync} = require('node:child_process');

const project = path.resolve(__dirname, '..');
const guideRoot = path.resolve(process.env.TESTLAB_GUIDE_DIR || path.join(project, 'docs', 'user-guide', 'generated'));
const output = path.join(guideRoot, 'Скриншоты');
const temporary = fs.mkdtempSync(path.join(os.tmpdir(), 'testlab-guide-'));
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let server, chrome, session;
let sequence = 0;
const requests = new Map();

async function port() {
  const listener = net.createServer();
  await new Promise((resolve,reject) => {
    listener.once('error',reject);
    listener.listen(0,'127.0.0.1',resolve);
  });
  const value = listener.address().port;
  await new Promise(resolve => listener.close(resolve));
  return value;
}

function command(method, params = {}, sessionId) {
  const id = ++sequence;
  return new Promise((resolve,reject) => {
    const timer = setTimeout(() => {
      requests.delete(id);
      reject(new Error('Браузер не ответил: '+method));
    },15000);
    requests.set(id, {resolve, reject, timer});
    chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId ? {sessionId} : {})})+'\0');
  });
}

async function evaluate(expression) {
  const response = await command('Runtime.evaluate', {expression, awaitPromise:true, returnByValue:true},session);
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text);
  }
  return response.result?.value;
}

async function waitFor(expression) {
  for (let i=0;i<80;i++) {
    if (await evaluate(expression)) return;
    await sleep(100);
  }
  throw new Error('Не открылся ожидаемый экран: '+expression);
}

async function click(selector) {
  await evaluate(`document.querySelector(${JSON.stringify(selector)}).click()`);
}

async function fill(selector, value) {
  await evaluate(`(() => {const el=document.querySelector(${JSON.stringify(selector)});el.value=${JSON.stringify(value)};el.dispatchEvent(new Event('input',{bubbles:true}));})()`);
}

async function snapshot(filename) {
  await evaluate('(async()=>{document.querySelector("#toast")?.replaceChildren();window.scrollTo(0,0);await document.fonts.ready;await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));})()');
  const result = await command('Page.captureScreenshot',{format:'png',captureBeyondViewport:false},session);
  fs.writeFileSync(path.join(output,filename),Buffer.from(result.data,'base64'));
  console.log('Снимок: '+filename);
}

async function login(email,password) {
  await waitFor('!!document.querySelector("#authForm")');
  await fill('#field-email',email);
  await fill('#field-password',password);
  await evaluate('document.querySelector("#authForm").requestSubmit()');
  await waitFor('!!document.querySelector(".sidebar")');
}

async function logout() {
  await click('#logout');
  await waitFor('!!document.querySelector("#authForm")');
}

async function page(name) {
  await click(`[data-page="${name}"]`);
}

async function main() {
  fs.mkdirSync(output,{recursive:true});
  const serverPort = await port();
  const url = 'http://127.0.0.1:'+serverPort;
  const serverLog = fs.openSync(path.join(temporary,'server.log'),'w');
  server = spawn('python3',['server.py','--port',String(serverPort)], {
    cwd:project,env:{...process.env,TESTLAB_DB:path.join(temporary,'demo.sqlite3')},
    stdio:['ignore',serverLog,serverLog]
  });
  let available=false;
  for(let i=0;i<80;i++) {
    try { if ((await fetch(url)).ok) {available=true;break;} } catch {}
    if (server.exitCode !== null) break;
    await sleep(150);
  }
  if(!available) throw new Error('Не удалось запустить демонстрационное приложение: '+fs.readFileSync(path.join(temporary,'server.log'),'utf8'));
  const browserLog=fs.openSync(path.join(temporary,'chrome.log'),'w');
  chrome=spawn('google-chrome',[
    '--headless=new','--remote-debugging-pipe','--no-first-run',
    '--no-default-browser-check','--disable-extensions','--disable-dev-shm-usage',
    '--hide-scrollbars','--user-data-dir='+path.join(temporary,'browser')
  ],{stdio:['ignore','ignore',browserLog,'pipe','pipe']});
  let buffer='';
  chrome.stdio[4].setEncoding('utf8');
  chrome.stdio[4].on('data',chunk=>{
    buffer+=chunk;
    let end;
    while((end=buffer.indexOf('\0'))>=0) {
      const raw=buffer.slice(0,end);buffer=buffer.slice(end+1);
      if(!raw)continue;
      const message=JSON.parse(raw);
      if(!message.id)continue;
      const item=requests.get(message.id);
      if(!item)continue;
      clearTimeout(item.timer);requests.delete(message.id);
      if(message.error)item.reject(new Error(message.error.message));
      else item.resolve(message.result);
    }
  });
  chrome.on('exit',()=>{
    for(const [id,item] of requests) {
      clearTimeout(item.timer);
      item.reject(new Error('Браузер закрылся: '+fs.readFileSync(path.join(temporary,'chrome.log'),'utf8').slice(-1200)));
      requests.delete(id);
    }
  });
  chrome.stdio[3].on('error',()=>{});
  await command('Browser.getVersion');
  const target=await command('Target.createTarget',{url:'about:blank'});
  session=(await command('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;
  await command('Page.enable',{},session);
  await command('Runtime.enable',{},session);
  await command('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false},session);
  await command('Page.navigate',{url},session);
  await waitFor('!!document.querySelector("#authForm")');
  await fill('#field-email','admin@testlab.local');
  await snapshot('01-login.png');
  await click('#toggleAuth');
  await fill('#field-name','Анна Смирнова');
  await fill('#field-email','anna@example.test');
  await fill('#field-password','User12345!');
  await snapshot('02-registration.png');
  await evaluate('document.querySelector("#authForm").requestSubmit()');
  await waitFor('!!document.querySelector(".sidebar")');
  await snapshot('03-waiting.png');
  await logout();
  await login('admin@testlab.local','Admin12345!');
  const primary=await evaluate('projectId');
  await evaluate(`(async()=>{
    const samples=[
      ['Вход с верным паролем','Введите почту и пароль. Нажмите «Войти».','Открывается обзор группы.','passed','Обзор открылся.'],
      ['Неверный пароль','Введите неправильный пароль. Нажмите «Войти».','Появляется сообщение об ошибке.','failed','Сообщение не появилось.'],
      ['Восстановление доступа','Откройте страницу восстановления доступа.','Открывается форма восстановления.','blocked','Тестовая страница временно недоступна.'],
      ['Переключение группы','Откройте список «Группа». Выберите другую группу.','Показаны проверки выбранной группы.','not_run','']
    ];
    for(const [title,steps,expected,status,actual] of samples){
      const result=await api('checks',{project_id:projectId,title,steps,expected});
      if(status!=='not_run')await api('checks/result',{project_id:projectId,check_id:result.id,status,actual});
    }
    await refresh(true);
  })()`);
  await snapshot('04-overview-admin.png');
  await click('[data-open="project"]');
  await fill('#field-name','Проверка новой версии');
  await snapshot('07-new-group.png');
  await evaluate('document.querySelector("#entityForm").requestSubmit()');
  await waitFor('!document.querySelector(".modal")');
  await snapshot('05-overview-empty.png');
  await evaluate(`refresh(true,${primary})`);
  await page('checks');
  await snapshot('09-checks.png');
  await evaluate(`document.querySelector('#statusFilter').value='failed';document.querySelector('#statusFilter').dispatchEvent(new Event('change'));`);
  await snapshot('10-filtered.png');
  await evaluate(`document.querySelector('#statusFilter').value='all';document.querySelector('#statusFilter').dispatchEvent(new Event('change'));`);
  await click('[data-open="check"]');
  await fill('#field-title','Создание группы');
  await fill('#field-steps','Нажмите «Новая группа». Введите название. Нажмите «Создать группу».');
  await fill('#field-expected','Новая группа появилась в списке и выбрана.');
  await snapshot('08-new-check.png');
  await click('#cancelModal');
  await evaluate(`openModal({type:'result',check:{...state.checks.find(check=>check.status==='failed')}})`);
  await snapshot('11-result.png');
  await click('#cancelModal');
  await page('team');
  await click('[data-open="member"]');
  await fill('#field-email','anna@example.test');
  await snapshot('13-add-member.png');
  await evaluate('document.querySelector("#entityForm").requestSubmit()');
  await waitFor('!document.querySelector(".modal") && state.users.length===2');
  await snapshot('12-team-admin.png');
  await logout();
  await login('anna@example.test','User12345!');
  await snapshot('06-overview-user.png');
  await page('team');
  await snapshot('14-team-user.png');
  const built=spawnSync('python3',[path.join(__dirname,'build_guide.py')],{stdio:'inherit'});
  if(built.status!==0)throw new Error('Снимки сохранены, но сборка PDF завершилась с ошибкой');
  console.log('Готово: все 14 снимков включены в руководство. Рабочие аккаунты и данные не изменялись.');
}

main().catch(error=>{
  console.error('Не удалось завершить съёмку: '+error.message);
  console.error('Ранее сохранённое руководство и снимки остаются в папке.');
  process.exitCode=1;
}).finally(async()=>{
  for(const child of [chrome,server]) {
    if(child && child.exitCode===null){child.kill('SIGTERM');await sleep(300);if(child.exitCode===null)child.kill('SIGKILL');}
  }
  await sleep(200);
  fs.rmSync(temporary,{recursive:true,force:true});
});
