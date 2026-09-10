#!/usr/bin/env node
/**
 * capture_fingerprint.js — 从已登录浏览器抓取"真机设备指纹"并 pin 到本地
 *
 * 为什么需要：
 *   xhshow 默认每请求随机生成一套设备指纹（x-s-common 的 x8/x9 每次都变），
 *   等于"同一 a1 每请求自称一台新设备"，是极易被风控聚类的异常。
 *   本脚本抓取该浏览器真实使用的 x8（b1 blob）并落盘，让签名器复用它 ——
 *   这样我们的请求与真机浏览器共享同一设备身份。
 *
 * 用法:
 *   node capture_fingerprint.js [输出路径] [CDP端口]
 * 默认输出: <脚本目录>/device_fingerprint.json
 *
 * 副作用: 会往目标页注入 XHR 钩子并 reload 一次以捕获真实请求头；
 *         用完关闭该 tab 即可清除（或让它留在浏览器里，reload 后钩子即被重装）。
 */
const fs = require('fs');
const path = require('path');

const OUT = process.argv[2] || path.join(__dirname, 'device_fingerprint.json');
const CDP = process.argv[3] || '19223';
const CUSTOM = 'ZmserbBoHQtNP+wOcza/LpngG8yJq42KWYj0DSfdikx3VT16IlUAFM97hECvuRX5';
const STD = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';

function decodeCustomB64(s) {
  let mapped = '';
  for (const ch of s) {
    if (ch === '=') { mapped += '='; continue; }
    const i = CUSTOM.indexOf(ch);
    mapped += i < 0 ? ch : STD[i];
  }
  return Buffer.from(mapped, 'base64').toString('utf8');
}

const HOOK = `(function(){
  if (window.__fpHooked) return; window.__fpHooked = true;
  window.__fpHits = [];
  var oSet = XMLHttpRequest.prototype.setRequestHeader;
  var oOpen = XMLHttpRequest.prototype.open;
  var oSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function(m,u){ this.__u = u; this.__h = {}; return oOpen.apply(this, arguments); };
  XMLHttpRequest.prototype.setRequestHeader = function(k,v){ try{ this.__h[k]=v; }catch(e){} return oSet.apply(this, arguments); };
  XMLHttpRequest.prototype.send = function(){
    try {
      var u = String(this.__u || '');
      if (/\\/api\\/sns\\//.test(u)) {
        for (var k in this.__h) {
          if (/^x-s-common$/i.test(k)) window.__fpHits.push(String(this.__h[k]));
        }
      }
    } catch(e){}
    return oSend.apply(this, arguments);
  };
})();`;

let WebSocket;
for (const p of [
  path.join(__dirname, '..', 'node_modules', 'ws'),          // 项目内依赖（npm i）
  'ws',
  path.join(process.env.HOME || '', '.openclaw-vovo/workspace/tools/xiaohongshu/node_modules/ws'),
]) { try { WebSocket = require(p); break; } catch (e) { /* next */ } }
if (!WebSocket) { console.error('need ws'); process.exit(1); }

(async () => {
  const list = await (await fetch(`http://127.0.0.1:${CDP}/json/list`)).json();
  const tab = list.find(t => t.type === 'page' && (t.url || '').includes('xiaohongshu.com'));
  if (!tab) { console.error('未找到小红书页面：先 `xhs cookies` 或 brs 打开并登录小红书'); process.exit(1); }

  const ws = new WebSocket(`ws://127.0.0.1:${CDP}/devtools/page/${tab.id}`, { maxPayload: 100 * 1024 * 1024 });
  await new Promise((res, rej) => { ws.on('open', res); ws.on('error', rej); });
  let seq = 1;
  const cmd = (m, p) => new Promise(res => {
    const id = seq++;
    const h = raw => { const x = JSON.parse(raw); if (x.id === id) { ws.off('message', h); res(x); } };
    ws.on('message', h); ws.send(JSON.stringify({ id, method: m, params: p }));
  });

  await cmd('Page.enable', {});
  await cmd('Page.addScriptToEvaluateOnNewDocument', { source: HOOK });
  console.log('已注入捕获钩子，reload 页面…');
  await cmd('Page.reload', { ignoreCache: false });
  await new Promise(r => setTimeout(r, 11000));

  const r = await cmd('Runtime.evaluate', { expression: 'JSON.stringify(window.__fpHits||[])', returnByValue: true });
  const hits = JSON.parse((r.result.result && r.result.result.value) || '[]');
  if (!hits.length) {
    console.error('未捕获到 x-s-common；页面可能未登录或未发出 API 请求');
    ws.close(); process.exit(1);
  }
  const struct = JSON.parse(decodeCustomB64(hits[0]));
  const uaRes = await cmd('Runtime.evaluate', { expression: 'navigator.userAgent', returnByValue: true });
  const realUa = (uaRes.result.result && uaRes.result.result.value) || undefined;
  const pin = { x8: struct.x8, x9: struct.x9, ua: realUa, captured_at: new Date().toISOString(), source: 'real-browser' };
  fs.writeFileSync(OUT, JSON.stringify(pin, null, 2), { mode: 0o600 });
  console.log(`已捕获 ${hits.length} 次 x-s-common`);
  console.log(`x8(b1 blob) 长度=${String(struct.x8).length}  x9=${struct.x9}`);
  console.log(`真机 UA=${String(realUa).slice(0, 70)}`);
  console.log(`wrote ${OUT} (chmod 600)`);
  ws.close();
})();
