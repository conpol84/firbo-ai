/** Restricted FIRBO Playwright egress policy.
 *
 * Defense in depth inside the existing self-hosted, read-only Docker browser.
 * Browser navigation/subresources are inspected at the Playwright route
 * boundary; APIRequestContext shortcuts and browser WebSockets are disabled.
 *
 * DNS is evaluated fresh on EVERY request and all answers must be public.
 * This reduces prompt-injection/SSRF exposure. It does NOT replace an OS-level
 * network firewall: DNS rebinding between lookup and Chromium connect, browser
 * bugs and other child-process traffic require separate container egress ACLs.
 */
import { BlockList, isIP } from 'node:net';
import { lookup } from 'node:dns/promises';

const blocked=new BlockList();
for(const [address,prefix] of [
 ['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],
 ['169.254.0.0',16],['172.16.0.0',12],['192.0.0.0',24],
 ['192.0.2.0',24],['192.168.0.0',16],['198.18.0.0',15],
 ['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',4],
 ['240.0.0.0',4],
]) blocked.addSubnet(address,prefix,'ipv4');
for(const [address,prefix] of [
 ['::',128],['::1',128],['::ffff:0:0',96],['64:ff9b:1::',48],
 ['100::',64],['2001:db8::',32],['2001:10::',28],
 ['fc00::',7],['fe80::',10],['ff00::',8],
]) blocked.addSubnet(address,prefix,'ipv6');

const denySuffixes=['.localhost','.local','.internal','.lan','.home','.test','.invalid','.onion'];
const forbidden=new Set(['localhost','localhost.localdomain','metadata.google.internal','metadata','host.docker.internal','gateway.docker.internal']);
const apiMethods=['fetch','get','post','put','patch','delete','head'];

export function globallyRoutableAddress(address){
 if(typeof address!=='string')return false;
 const normalized=address.replace(/^\[|\]$/g,'').toLowerCase();
 const family=isIP(normalized);
 if(family===4)return !blocked.check(normalized,'ipv4');
 if(family===6){
  // Only global IPv6 unicast space (2000::/3), with known special-use
  // subnets excluded. Mapped IPv4 is always denied.
  if(normalized.startsWith('::')||normalized.startsWith('0:'))return false;
  const head=parseInt(normalized.split(':')[0],16);
  return Number.isInteger(head)&&head>=0x2000&&head<=0x3fff
    &&!blocked.check(normalized,'ipv6');
 }
 return false;
}

export async function publicBrowserUrl(raw,{resolve=lookup}={}){
 if(typeof raw!=='string'||raw.length>2048)return false;
 let url;
 try{url=new URL(raw);}catch{return false;}
 if(!['https:','http:'].includes(url.protocol)
   ||url.username||url.password||url.hash.length>2048)return false;
 const host=url.hostname.replace(/^\[|\]$/g,'').toLowerCase().replace(/\.$/,'');
 if(!host||forbidden.has(host)||denySuffixes.some(s=>host.endsWith(s))
   ||(!host.includes('.')&&!isIP(host)))return false;
 const port=url.port;
 if(port && !['80','443'].includes(port))return false;
 if(isIP(host))return globallyRoutableAddress(host);
 let addresses;
 try{
  addresses=await resolve(host,{all:true,verbatim:true});
 }catch{return false;}
 return Array.isArray(addresses)&&addresses.length>0&&addresses.length<=32
   &&addresses.every(item=>item&&globallyRoutableAddress(item.address));
}

/**
 * Call on a NEW Playwright context before opening its first page.
 * If hooks cannot be installed, throw and close the context (fail-closed).
 */
export async function installBrowserNetworkPolicy(context,{resolve=lookup}={}){
 if(!context||typeof context.route!=='function'||typeof context.routeWebSocket!=='function')
   throw new Error('browser_egress_policy_unavailable');
 const api=context.request;
 if(!api)throw new Error('browser_api_request_policy_unavailable');
 // Playwright page.request and context.request share this APIRequestContext.
 // Keep a direct, unproxied API transport unavailable to model-generated JS.
 for(const method of apiMethods){
  Object.defineProperty(api,method,{
   value:async()=>{throw new Error('browser_direct_http_denied');},
   writable:false,configurable:false,
  });
 }
 await context.route('**/*',async route=>{
  let allowed=false;
  try{allowed=await publicBrowserUrl(route.request().url(),{resolve});}catch{allowed=false;}
  if(!allowed){await route.abort('blockedbyclient');return;}
  await route.continue();
 });
 // WebSockets are not HTTP routes. The locked V1 public read/research scope
 // needs no websocket transport; deny all, including internal ws:// targets.
 await context.routeWebSocket('**/*',ws=>ws.close());
}
