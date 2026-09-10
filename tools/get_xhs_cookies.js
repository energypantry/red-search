#!/usr/bin/env node
/**
 * get_xhs_cookies.js — 从 Agent Browser Runtime 的已登录 Chrome 里提取小红书 cookies
 *
 * 用法:
 *   node get_xhs_cookies.js [输出路径] [CDP端口]
 * 默认: 输出 /tmp/xhs_cookies.json (chmod 600)，CDP 端口 19223
 *
 * 前置: browser runtime 在线，且有一个已登录 www.xiaohongshu.com 的页面。
 * 注意: 输出含活体会话凭据（web_session 等），用完即删，不要提交/外传。
 */
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || '/tmp/xhs_cookies.json';
const CDP = process.argv[3] || '19223';

let WebSocket;
for (const p of [
  path.join(__dirname, '..', 'node_modules', 'ws'),          // 项目内依赖（npm i）
  'ws',
  path.join(process.env.HOME || '', '.openclaw-vovo/workspace/tools/xiaohongshu/node_modules/ws'),
]) {
  try { WebSocket = require(p); break; } catch (e) { /* next */ }
}
if (!WebSocket) {
  console.error('need ws: npm i ws   (或复用 xiaohongshu/node_modules/ws)');
  process.exit(1);
}

(async () => {
  const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
  const tab = list.find(t => t.type === 'page' && (t.url || '').includes('xiaohongshu.com'));
  if (!tab) { console.error('未找到小红书页面，先用 brs 打开一个已登录页面'); process.exit(1); }

  const ws = new WebSocket(`ws://127.0.0.1:${CDP}/devtools/page/${tab.id}`, { maxPayload: 50 * 1024 * 1024 });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let seq = 1;
  const cmd = (m, p) => new Promise(res => {
    const id = seq++;
    const h = raw => { const x = JSON.parse(raw); if (x.id === id) { ws.off('message', h); res(x); } };
    ws.on('message', h); ws.send(JSON.stringify({ id, method: m, params: p }));
  });

  await cmd('Network.enable', {});
  const r = await cmd('Network.getAllCookies', {});
  const xhs = ((r.result && r.result.cookies) || [])
    .filter(c => /xiaohongshu\.com$/.test(c.domain.replace(/^\./, '')));

  const obj = {};
  for (const c of xhs) obj[c.name] = c.value;
  fs.writeFileSync(OUT, JSON.stringify(obj), { mode: 0o600 });

  const need = ['a1', 'web_session', 'webId', 'gid', 'xsecappid'];
  console.log(`wrote ${OUT} (chmod 600)  cookies=${xhs.length}`);
  console.log('names:', Object.keys(obj).sort().join(', '));
  console.log('required:', need.map(n => `${n}=${n in obj ? 'Y' : 'N'}`).join(' '));
  ws.close();
})();
