'use strict';
const $ = (selector) => document.querySelector(selector);
const state = {data: null, view: 'runs', selected: null, request: 0, dirty: false};
const views = {runs: ['실행 결과', '실행 조건부터 검증 결과까지, 기록을 따라 확인하세요.'], patterns: ['메모리 패턴', '상수·위치·seed 패턴과 검사 순서를 정의하세요.'], profiles: ['실험 프리셋', '패턴과 실행 조건을 저장하고 같은 실험을 다시 실행하세요.']};
const metrics = {temperature_c: ['GPU 온도', '°C'], power_w: ['소비 전력', 'W'], sm_clock_mhz: ['SM 클록', 'MHz'], memory_clock_mhz: ['메모리 클록', 'MHz'], memory_used_mib: ['사용 메모리', 'MiB'], gpu_util_percent: ['GPU 사용률', '%'], memory_util_percent: ['메모리 사용률', '%']};
function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
function add(parent, ...children) { children.forEach(child => parent.append(child)); return parent; }
function badge(status) { const known = ['PASS','FAIL','ERROR','RUNNING'].includes(status); return el('span', 'badge ' + (known ? status.toLowerCase() : ''), known ? status : 'UNKNOWN'); }
function bytes(n) { return Number.isFinite(n) ? `${(n / 1048576).toLocaleString('en-US', {maximumFractionDigits: 3})} MiB` : '기록 없음'; }
function duration(n) { return Number.isFinite(n) ? `${n.toFixed(3)} s` : '미완료'; }
function date(value) { const d = new Date(value); return Number.isNaN(d.getTime()) ? '시각 없음' : d.toLocaleString('ko-KR', {month:'2-digit', day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}); }
function notice(message) { $('#notice').hidden = !message; $('#notice').textContent = message || ''; }
async function api(path, options={}) { const response = await fetch(path, options); const result = await response.json(); if (!response.ok) throw new Error(result.error || `HTTP ${response.status}`); return result; }
async function refresh(keep=true) { try { state.data = await api('/api/state'); loadingControls(false); if (!keep) state.selected = null; render(); notice(state.data.runs.unreadable ? `${state.data.runs.unreadable}개 기록 파일을 읽지 못했습니다. 정상 기록은 계속 조회할 수 있습니다.` : ''); } catch(error) { notice(error.message); } }
function entries() { return state.view === 'runs' ? state.data.runs.entries : state.data[state.view]; }
function key(item) { return state.view === 'runs' ? item.id : item.filename; }
function render() {
  $('#page-title').textContent = views[state.view][0]; $('#page-caption').textContent = views[state.view][1];
  document.querySelectorAll('nav button').forEach(button => button.classList.toggle('active', button.dataset.view === state.view));
  $('#new-document').hidden = state.view === 'runs'; $('#overview').replaceChildren();
  const runs = state.data.runs.entries;
  [['전체 실행', runs.length, ''], ['PASS', runs.filter(x=>x.status==='PASS').length, 'pass'], ['FAIL · 불일치', runs.filter(x=>x.status==='FAIL').length, 'fail'], ['ERROR · 실행 오류', runs.filter(x=>x.status==='ERROR').length, 'error']].forEach(([name,value,tone])=>add($('#overview'), add(el('article'), el('small','',name),el('strong',tone,value))));
  const query = $('#search').value.toLowerCase();
  const items = entries().filter(item=>JSON.stringify(item).toLowerCase().includes(query));
  if (!items.some(x=>key(x)===state.selected)) state.selected = items.length ? key(items[0]) : null;
  renderList(items);
  const item = items.find(x=>key(x)===state.selected);
  if (item) show(item); else $('#detail').replaceChildren(el('div','empty',state.view==='runs'?'저장된 실험 기록이 없습니다. CLI로 실험을 실행한 뒤 새로고침하세요.':'새 문서를 만들어 실험 조건을 저장하세요.'));
}
function renderList(items) {
  $('#list').replaceChildren();
  if (!items.length) $('#list').append(el('div','empty','표시할 항목이 없습니다.'));
  items.forEach(item=>{
    const button=el('button','list-row'+(key(item)===state.selected?' selected':''));
    if (state.view==='runs') {
      add(button,add(el('div','row-top'),badge(item.status),el('span','',date(item.started_utc))),el('span','row-title',`${bytes(item.config.allocation_bytes)} · ${item.config.iterations ?? '—'}회 반복`),el('span','row-meta',`${item.config.injection_enabled?'오류 주입':'정상 검사'} · ${duration(item.elapsed)}`));
    } else {
      add(button,el('span','row-title',item.document?.name || item.filename),el('span','row-meta',item.filename));
      if (item.error) button.append(el('div','row-meta','입력 오류 · 확인 필요'));
      else button.append(el('div','row-meta',state.view==='patterns'?`${item.resolved.pattern_mode || 'constant'} · ${item.resolved.patterns.length}개 패턴`:`${bytes(item.resolved.count*4)} · ${item.resolved.iterations}회 반복`));
    }
    button.onclick=()=>{if(state.dirty && !confirm('저장하지 않은 편집을 버릴까요?')) return; state.dirty=false; state.selected=key(item); renderList(items); show(item);}; $('#list').append(button);
  });
}
async function show(item) {
  if(state.view!=='runs') { state.request++; return editor(item); }
  const request=++state.request;
  $('#detail').replaceChildren(el('div','empty','실행 기록을 불러오는 중…'));
  try {const data=await api('/api/run?id='+encodeURIComponent(item.id)); if(request===state.request) renderRun(data);}
  catch(error){if(request===state.request) $('#detail').replaceChildren(el('div','form-error',error.message));}
}
function renderRun(data) {
  const report=data.report, config=report.config || {}, panel=$('#detail'); panel.replaceChildren();
  const title=config.injection_enabled?'오류 주입 검증':'정상 메모리 검증';
  add(panel,add(el('div','detail-title'),add(el('div'),el('h2','',title),el('div','subtle',`${date(report.started_utc)} · ${report.reason || '완료 여부 미확인'}`)),badge(report.status)),el('div','run-id',report.run_id));
  const cards=el('div','metrics'); [['할당 크기',bytes(config.allocation_bytes)],['완료한 패턴 검사',report.reported_completed_patterns ?? '기록 없음'],['전체 실행 시간',duration(report.process_elapsed_seconds)]].forEach(([label,value])=>add(cards,add(el('div','metric'),el('small','',label),el('strong','',value)))); panel.append(cards);
  const facts=el('dl','facts'); const commit=report.provenance?.git_head?.stdout?.trim();
  const fields=[['패턴 방식',config.pattern_mode || 'constant'],['검사 동작',config.access_mode || 'read'],['GPU 검사 / 묶음',`${config.gpu_passes ?? 1}회`],['주입 검사 회차',config.inject_pass ?? 1],['반복 / 기록 한도',`${config.iterations ?? '—'}회 / ${config.max_records ?? '—'}건`],['CPU 대조',config.reference_mode || '기록 없음'],['종료 코드',report.child_exit_code ?? '기록 없음'],['코드 버전',commit ? commit.slice(0,12)+(report.provenance?.git_status?.stdout?.trim()?' · 작업 변경 포함':''):'기록 없음']];
  fields.forEach(([name,value])=>add(facts,el('dt','',name),el('dd','',value))); panel.append(facts);
  const chips=el('div','chip-list'); (config.patterns || []).forEach(value=>chips.append(el('span','chip',value))); if(!chips.childNodes.length) chips.append(el('span','subtle','이전 기록에는 패턴 목록 필드가 없습니다. 원시 로그에서 확인하세요.')); panel.append(chips);
  const deviceMap=new Map(); data.samples.forEach(sample=>(sample.devices||[]).forEach(device=>deviceMap.set(device.uuid,device)));
  const heading=el('div','section-title'); heading.append(el('span','','GPU 모니터링'));
  const select=el('select'); select.setAttribute('aria-label','모니터링 지표'); Object.entries(metrics).forEach(([value,[name,unit]])=>{const option=el('option','',`${name} (${unit})`);option.value=value;select.append(option);}); heading.append(select);panel.append(heading);
  const deviceSelect=el('select');deviceSelect.setAttribute('aria-label','GPU 장비');deviceMap.forEach((device,id)=>{const option=el('option','',`${device.name} · ${id.slice(-8)}`);option.value=id;deviceSelect.append(option);});
  if(deviceMap.size>1) heading.append(deviceSelect);
  const chart=el('div','chart'); panel.append(chart);
  const status=report.telemetry?.status || '기록 없음'; const gpu=[...deviceMap.values()][0];
  panel.append(el('div','note',`${gpu?.name || 'GPU 조회 정보 없음'} · 수집 상태 ${status} · ${data.samples.length}개 샘플${data.telemetry_truncated?' · 조회량 제한으로 일부 표시':''}${data.malformed_samples?' · 읽지 못한 샘플 '+data.malformed_samples+'개':''}`));
  panel.append(el('div','note','누락된 값은 0으로 바꾸지 않습니다. 그래프는 조회 시점의 관측값이며 커널별 측정이 아닙니다.'));
  const redraw=()=>drawChart(chart,data.samples,select.value,deviceSelect.value,status);select.onchange=redraw;deviceSelect.onchange=redraw;redraw();
  panel.append(el('div','section-title','원시 기록과 실행 당시 설정'));
  const tabs=el('div','log-tools'), output=el('pre'), logNote=el('div','note');
  const sources=[['stdout.txt','검사 로그'],['stderr.txt','오류 출력'],['resolved_config.json','최종 설정'],['inputs/profile.json','프리셋 원본'],['inputs/patterns.json','패턴 원본'],['report','run.json']];
  sources.forEach(([name,label],index)=>{const button=el('button','',label);button.onclick=()=>{tabs.querySelectorAll('button').forEach(x=>x.classList.remove('active'));button.classList.add('active'); const value=name==='report'?{text:JSON.stringify(report,null,2),available:true}:data.logs[name];output.textContent=value?.text || (value?.available?'출력 없음':'해당 파일 없음');logNote.textContent=value?.truncated?'파일이 커서 앞부분만 표시합니다. 전체 기록은 결과 폴더에서 확인하세요.':'';};tabs.append(button);if(index===0)button.click();}); add(panel,tabs,output,logNote);
}
function svg(tag, attrs={}, text) {const node=document.createElementNS('http://www.w3.org/2000/svg',tag);Object.entries(attrs).forEach(([k,v])=>node.setAttribute(k,String(v)));if(text!==undefined)node.textContent=text;return node;}
function drawChart(container,samples,metric,uuid,status) {
  container.replaceChildren();
  const points=samples.map(sample=>{const device=(sample.devices||[]).find(x=>x.uuid===uuid);const item=device?.metrics?.[metric];return {x:sample.elapsed_seconds,y:item?.status==='AVAILABLE'&&Number.isFinite(item.value)?item.value:null};}).filter(p=>Number.isFinite(p.x));
  const valid=points.filter(p=>p.y!==null); if(!valid.length){container.append(el('div','empty',`표시할 관측값이 없습니다. 수집 상태: ${status}`));return;}
  const [name,unit]=metrics[metric];const W=640,H=190,L=52,R=19,T=17,B=35;
  const ymin=Math.min(...valid.map(p=>p.y)),ymax=Math.max(...valid.map(p=>p.y)),pad=Math.max((ymax-ymin)*.15,1),low=Math.max(0,ymin-pad),high=ymax+pad;
  const xmax=Math.max(...points.map(p=>p.x),1);const x=v=>L+v/xmax*(W-L-R),y=v=>T+(high-v)/(high-low)*(H-T-B);
  const root=svg('svg',{viewBox:`0 0 ${W} ${H}`,role:'img','aria-label':`${name} 관측값, ${valid.length}개 샘플`});
  for(let i=0;i<4;i++){const value=low+(high-low)*i/3,py=y(value);root.append(svg('line',{x1:L,x2:W-R,y1:py,y2:py,stroke:'#dfe8ed','stroke-width':1}),svg('text',{x:L-8,y:py+4,'text-anchor':'end',fill:'#708694','font-size':10},value.toFixed(1)));}
  let segment=[];const flush=()=>{if(segment.length>1)root.append(svg('polyline',{points:segment.join(' '),fill:'none',stroke:'#0b9193','stroke-width':2}));segment=[];};
  points.forEach(point=>{if(point.y===null){flush();return;}segment.push(`${x(point.x)},${y(point.y)}`);});flush();
  valid.forEach(point=>{const dot=svg('circle',{cx:x(point.x),cy:y(point.y),r:3.5,fill:'#087f82'});dot.append(svg('title',{},`${point.x.toFixed(3)}s · ${point.y} ${unit}`));root.append(dot);});
  root.append(svg('text',{x:L,y:H-9,fill:'#708694','font-size':10},'0 s'),svg('text',{x:W-R,y:H-9,'text-anchor':'end',fill:'#708694','font-size':10},`${xmax.toFixed(2)} s`));container.append(root);
}
function field(form,label,name,value,options={}) {const wrap=el('label','field'+(options.full?' full':''));wrap.append(el('span','',label));const input=el(options.textarea?'textarea':'input',options.textarea&&name==='values'?'pattern-values':'');input.name=name;if(!options.textarea)input.type=options.type||'text';input.value=value ?? '';if(options.type==='number')input.step='any';wrap.append(input);form.append(wrap);return input;}
function editor(item) {
  state.dirty=false;const kind=state.view, isPattern=kind==='patterns';
  const doc=(item?.document && !Array.isArray(item.document) && typeof item.document==='object' ? item.document : null) || (isPattern?{schema_version:1,name:'새 메모리 패턴',description:'',values:['12345678','87654321']}:{schema_version:1,name:'새 실험 프리셋',description:'',...state.data.defaults,pattern_file:'../patterns/'+(state.data.patterns.find(p=>!p.error)?.filename||'default.json')});
  const panel=$('#detail');panel.replaceChildren();add(panel,el('h2','',isPattern?'패턴 정의':'실험 조건'),el('div','subtle',isPattern?'상수는 같은 값, index는 위치 XOR 값, seeded는 위치와 seed로 재현 가능한 값을 만듭니다.':'패턴 파일과 실행 조건을 저장합니다. 실행은 복사한 명령으로 터미널에서 진행하세요.'));
  if(item?.error)panel.append(el('div','form-error',item.error));
  const form=el('form');form.id='document-form';const grid=el('div','form-grid');form.append(grid);
  const filename=field(grid,'파일명','filename',item?.filename || (isPattern?'new-pattern.json':'new-profile.json'));
  field(grid,'이름','name',doc.name);field(grid,'설명','description',doc.description || '',{full:true,textarea:true});
  if(isPattern){
    const wrap=el('label','field full');wrap.append(el('span','','패턴 방식'));const select=el('select');select.name='mode';
    for(const mode of ['constant','index','seeded']){const option=el('option','',mode);option.value=mode;select.append(option);}
    select.value=doc.mode || 'constant';wrap.append(select);grid.append(wrap);
    field(grid,'32비트 값 / seed · 줄바꿈 또는 쉼표로 구분','values',(Array.isArray(doc.values)?doc.values:[]).join('\n'),{full:true,textarea:true});}
  else {
    const wrap=el('label','field full');wrap.append(el('span','','메모리 패턴'));const select=el('select');select.name='pattern_file';state.data.patterns.filter(p=>!p.error).forEach(p=>{const option=el('option','',`${p.document.name} · ${p.filename}`);option.value='../patterns/'+p.filename;select.append(option);});select.value=doc.pattern_file;wrap.append(select);grid.append(wrap);
    const accessWrap=el('label','field full');accessWrap.append(el('span','','검사 동작'));
    const access=el('select');access.name='access_mode';
    for(const [value,label] of [['read','반복 읽기'],['invert','검사 사이 비트 반전 · 최소 2회']]){const option=el('option','',label);option.value=value;access.append(option);}
    access.value=doc.access_mode || 'read';accessWrap.append(access);grid.append(accessWrap);
    [['원소 수 (32비트)','count'],['상세 기록 한도','max_records'],['반복 횟수','iterations'],['GPU 검사 / 묶음','gpu_passes'],['주입 검사 회차','inject_pass'],['제한 시간 (초)','timeout_seconds'],['조회 간격 (초)','sample_interval']].forEach(([label,name])=>field(grid,label,name,doc[name] ?? state.data.defaults[name],{type:'number'}));
    for(const [name,label] of [['injection_enabled','첫 반복·첫 패턴에 오류 주입'],['telemetry_enabled','GPU 지표 수집']]){const wrap=el('label','check');const input=el('input');input.type='checkbox';input.name=name;input.checked=doc[name] ?? state.data.defaults[name];add(wrap,input,el('span','',label));grid.append(wrap);}
  }
  const hint=el('div','form-hint',isPattern?'1~64개 · 1~8자리 16진수 · 0x 접두사 사용 가능':'예: 33,554,432개 원소 = 128 MiB. CPU 전체 대조는 유지됩니다.');
  const message=el('div');message.id='save-message';message.setAttribute('role','status');
  const actions=el('div','actions'),save=el('button','primary','저장'),copy=el('button','secondary','실행 명령 복사');save.type='submit';copy.type='button';copy.disabled=!item?.command;
  add(actions,save,copy);add(form,hint,message,actions);panel.append(form);
  const command=el('pre');command.id='run-command';command.textContent=item?.command || '저장하면 실행 명령이 표시됩니다.';panel.append(el('div','section-title','터미널에서 실행'),command);
  form.addEventListener('input',()=>{state.dirty=true;copy.disabled=true;message.textContent='변경 사항을 저장하면 실행 명령을 복사할 수 있습니다.';message.className='note';});
  copy.onclick=async()=>{try{await navigator.clipboard.writeText(command.textContent);message.className='form-success';message.textContent='실행 명령을 복사했습니다.';}catch{message.className='note';message.textContent='아래 명령을 선택해 직접 복사하세요.';}};
  form.onsubmit=async(event)=>{event.preventDefault();save.disabled=true;message.textContent='';
    try {
      const data=new FormData(form);const document={schema_version:1,name:data.get('name'),description:data.get('description')};
      if(isPattern){document.mode=data.get('mode');document.values=data.get('values').trim()?data.get('values').trim().split(/[\s,]+/):[];}
      else{document.pattern_file=data.get('pattern_file');document.access_mode=data.get('access_mode');['count','max_records','iterations','gpu_passes','inject_pass','timeout_seconds','sample_interval'].forEach(k=>document[k]=Number(data.get(k)));['injection_enabled','telemetry_enabled'].forEach(k=>document[k]=form.elements[k].checked);}
      const name=filename.value;const result=await api('/api/document',{method:'POST',headers:{'Content-Type':'application/json','X-Workbench-Token':state.data.token},body:JSON.stringify({kind,filename:name,document,expected_sha256:item?.filename===name?item.sha256:null})});
      state.dirty=false;state.selected=result.filename;$('#search').value='';await refresh();$('#save-message').className='form-success';$('#save-message').textContent='저장했습니다. 실행 기록에는 이 설정의 사본이 남습니다.';
    } catch(error){message.className='form-error';message.textContent=error.message;} finally{save.disabled=false;}
  };
}
function abandon(){return !state.dirty || confirm('저장하지 않은 편집을 버릴까요?');}
document.querySelectorAll('nav button').forEach(button=>button.onclick=()=>{if(!abandon())return;state.dirty=false;state.view=button.dataset.view;state.selected=null;$('#search').value='';render();});
$('#refresh').onclick=()=>{if(abandon()){state.dirty=false;refresh();}};
$('#search').oninput=()=>{if(!state.dirty)render();};
$('#new-document').onclick=()=>{if(!abandon())return;state.selected=null;state.request++;renderList(entries());editor(null);};
window.addEventListener('beforeunload',event=>{if(state.dirty){event.preventDefault();event.returnValue='';}});
function loadingControls(disabled) { document.querySelectorAll('nav button, #search, #new-document').forEach(control => control.disabled = disabled); }
loadingControls(true);
refresh(false);
