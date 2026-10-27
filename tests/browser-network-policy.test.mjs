import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {globallyRoutableAddress,publicBrowserUrl,installBrowserNetworkPolicy}
 from '../services/browser-mcp/network-policy.mjs';

const publicResolve=async()=>[{address:'151.101.1.69',family:4},
 {address:'2606:4700:4700::1111',family:6}];
const privateResolve=async()=>[{address:'10.10.42.1',family:4}];
test('Private, local, reserved and metadata IPs cannot be directly requested',()=>{
 const blocked=[
  '127.0.0.1','10.3.4.5','172.16.0.1','172.31.1.1','192.168.1.1',
  '169.254.169.254','0.0.0.0','100.64.0.2','198.18.0.10',
  '192.0.2.2','198.51.100.10','203.0.113.8','224.1.2.3','255.255.255.255',
  '::1','::','fc00::1','fdab::2','fe80::a','ff02::1','2001:db8::1',
  '::ffff:127.0.0.1','::ffff:8.8.8.8'
 ];
 for(const address of blocked)assert.equal(globallyRoutableAddress(address),false,address);
 for(const address of ['8.8.8.8','1.1.1.1','151.101.1.69','2606:4700:4700::1111'])
   assert.equal(globallyRoutableAddress(address),true,address);
});
test('Allow only DNS-confirmed PUBLIC HTTP(S) browser requests',async()=>{
 for(const raw of ['https://en.wikipedia.org/wiki/Cyprus','https://github.com/conpol84/Firbo-production',
                   'https://www.espn.com/','http://example.com/']){
  assert.equal(await publicBrowserUrl(raw,{resolve:publicResolve}),true,raw);
 }
 for(const raw of [
  'http://127.0.0.1','http://0x7f000001/','http://0177.0.0.1/',
  'http://169.254.169.254/latest/meta-data','http://10.20.0.1:80/',
  'https://localhost/','https://HOST.DOCKER.INTERNAL:443/',
  'http://metadata.google.internal/','http://service.internal/',
  'https://private.local/','https://example.onion/',
  'file:///etc/passwd','ftp://example.com/file','data:text/html,secret',
  'http://user:password@public.example','https://example.com:3000/'
 ]){
  assert.equal(await publicBrowserUrl(raw,{resolve:publicResolve}),false,raw);
 }
 for(const raw of ['https://public.example/','http://dns-rebind.example/'])
  assert.equal(await publicBrowserUrl(raw,{resolve:privateResolve}),false,raw);
});
test('Mixed public/private DNS answers, failed DNS and bad host fail closed',async()=>{
 const mixed=async()=>[{address:'1.1.1.1',family:4},{address:'172.16.1.2',family:4}];
 const fail=async()=>{throw Error('resolver failed')};
 const large=async()=>Array.from({length:33},()=>({address:'8.8.8.8',family:4}));
 for(const resolve of [mixed,fail,large])
  assert.equal(await publicBrowserUrl('https://subdomain.example.com/',{resolve}),false);
 assert.equal(await publicBrowserUrl('not a url',{resolve:publicResolve}),false);
 assert.equal(await publicBrowserUrl('https://singlelabel',{resolve:publicResolve}),false);
 assert.equal(await publicBrowserUrl('http://[::ffff:127.0.0.1]/',{resolve:publicResolve}),false);
});
test('DNS is rechecked for every resource; a newly private answer is rejected',async()=>{
 let round=0;
 const resolve=async()=>++round===1?[{address:'1.1.1.1',family:4}]:[{address:'127.0.0.1',family:4}];
 assert.equal(await publicBrowserUrl('https://rebind.example/',{resolve}),true);
 assert.equal(await publicBrowserUrl('https://rebind.example/',{resolve}),false);
 assert.equal(round,2);
});
function contextFixture(){
 const direct={
  fetch(){return 'UNPROTECTED';},get(){return 'UNPROTECTED';},
  post(){return 'UNPROTECTED';},head(){return 'UNPROTECTED';},
  put(){return 'UNPROTECTED';},delete(){return 'UNPROTECTED';},
  patch(){return 'UNPROTECTED'}
 };
 return {
  request:direct,
  async route(pattern,fn){assert.equal(pattern,'**/*');this.intercept=fn;},
  async routeWebSocket(pattern,fn){assert.equal(pattern,'**/*');this.socketGuard=fn;},
 };
}
function requestRoute(url){
 const actual={aborted:null,continued:0};
 return {
  route:{
   request(){return{url(){return url}};},
   async abort(reason){actual.aborted=reason;},
   async continue(){actual.continued++;}
  },actual
 };
}
test('Installed Playwright route blocks internal network and preserves verified public pages',async()=>{
 const ctx=contextFixture();
 const resolved=[];
 const resolve=async host=>{resolved.push(host);return host==='private.example'
   ?[{address:'127.0.0.1',family:4}]
   :[{address:'151.101.1.69',family:4}];};
 await installBrowserNetworkPolicy(ctx,{resolve});
 const allowed=requestRoute('https://en.wikipedia.org/wiki/Cyprus');
 await ctx.intercept(allowed.route);
 assert.equal(allowed.actual.continued,1);
 assert.equal(allowed.actual.aborted,null);
 const denied=requestRoute('http://169.254.169.254/latest/meta-data/');
 await ctx.intercept(denied.route);
 assert.equal(denied.actual.continued,0);
 assert.equal(denied.actual.aborted,'blockedbyclient');
 const redirected=requestRoute('https://private.example/');
 await ctx.intercept(redirected.route);
 assert.equal(redirected.actual.aborted,'blockedbyclient');
 assert.deepEqual(resolved,['en.wikipedia.org','private.example']);
 for(const method of ['fetch','get','post','head','put','delete','patch']){
  await assert.rejects(ctx.request[method]('https://127.0.0.1'),/browser_direct_http_denied/);
 }
 let closed=false;
 ctx.socketGuard({close(){closed=true;}});
 assert.equal(closed,true);
});
test('Fail closed when browser cannot install every required networking hook',async()=>{
 await assert.rejects(installBrowserNetworkPolicy({route(){}},{}),/browser_egress_policy_unavailable/);
 await assert.rejects(installBrowserNetworkPolicy({route(){},routeWebSocket(){}},{}),
  /browser_api_request_policy_unavailable/);
});
test('Production browser Docker and service route install the policy before page creation',()=>{
 const src=readFileSync(new URL('../services/browser-mcp/server.mjs',import.meta.url),'utf8');
 const docker=readFileSync(new URL('../services/browser-mcp/Dockerfile',import.meta.url),'utf8');
 assert.match(src,/import \{ installBrowserNetworkPolicy \} from "\.\/network-policy\.mjs"/);
 assert.match(docker,/COPY server\.mjs create-session\.mjs network-policy\.mjs/);
 assert.match(src,/serviceWorkers: "block"/);
 const begin=src.indexOf('const context = await browser.newContext(');
 const guard=src.indexOf('await installBrowserNetworkPolicy(context)',begin);
 const page=src.indexOf('const page = await context.newPage()',begin);
 assert.ok(begin>=0&&guard>begin&&page>guard);
 assert.match(src,/acceptDownloads: false/);
 assert.match(src,/permissions: \[\]/);
});
