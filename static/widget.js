(function(){var s=document.currentScript,id=+s.dataset.agent,base=new URL(s.src).origin;
var b=document.createElement('button');b.textContent='Chat with us';
b.setAttribute('style','position:fixed;right:20px;bottom:20px;z-index:99999;border:0;border-radius:99px;padding:12px 20px;background:#7c3aff;color:#fff;font:600 15px system-ui;cursor:pointer;box-shadow:0 8px 24px rgba(0,0,0,.3)');
var p=document.createElement('div');
p.setAttribute('style','position:fixed;right:20px;bottom:76px;width:min(340px,calc(100vw - 40px));height:420px;z-index:99999;background:#fff;color:#111;border-radius:16px;box-shadow:0 12px 40px rgba(0,0,0,.35);display:none;flex-direction:column;font:15px system-ui;overflow:hidden');
p.innerHTML='<div style="padding:12px 16px;background:#0a0f2c;color:#fff;font-weight:600">Support</div><div style="flex:1;overflow:auto;padding:12px"></div><form style="display:flex;gap:6px;padding:10px;border-top:1px solid #eee"><input style="flex:1;padding:9px;border:1px solid #ccc;border-radius:8px" placeholder="Type your question" aria-label="Question"><button style="border:0;background:#7c3aff;color:#fff;border-radius:8px;padding:0 14px">Send</button></form>';
var m=p.children[1],f=p.children[2],i=f.children[0];
function add(t,me){var d=document.createElement('div');d.textContent=t;d.setAttribute('style','margin:6px 0;padding:8px 12px;border-radius:12px;max-width:85%;'+(me?'background:#7c3aff;color:#fff;margin-left:auto':'background:#f0f0f5'));m.appendChild(d);m.scrollTop=1e9}
add('Hi! How can we help?');
f.onsubmit=function(e){e.preventDefault();var q=i.value.trim();if(!q)return;i.value='';add(q,1);
fetch(base+'/public/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agent_id:id,q:q})}).then(function(r){return r.json()}).then(function(d){add(d.answer||'Sorry, something went wrong.')}).catch(function(){add('Sorry, we could not reach support right now.')})};
b.onclick=function(){p.style.display=p.style.display=='flex'?'none':'flex'};
document.body.appendChild(p);document.body.appendChild(b)})();
