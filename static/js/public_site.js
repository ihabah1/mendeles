
// ═══════════════════════════════════════════════════════════
// ENGINE CONNECTION v3 – SSE (Server-Sent Events)
// עדכון בזמן אמת: הדפדפן מתחבר פעם אחת ומקבל push מהשרת
// Fallback אוטומטי לנתוני DEMO כשהמנוע לא פעיל
// ═══════════════════════════════════════════════════════════
const ENGINE_BASE = '';   // reverse proxy – nginx מעביר /engine/ → :5001
// לפיתוח מקומי: const ENGINE_BASE = '';

let engineOnline = false;
let LIVE_FIXTURES = [];   // נתונים חיים מהמנוע – כל המשחקים
let _sseSource = null;    // EventSource פתוח

// ── SSE: חיבור לאירועים חיים ─────────────────────────────
function connectSSE() {
  if (_sseSource) { _sseSource.close(); }

  _sseSource = new EventSource(`${ENGINE_BASE}/engine/stream`);

  _sseSource.onopen = () => {
    engineOnline = true;
    updateEngineStatus();
    log('📡 SSE מחובר – מקבל עדכונים בזמן אמת');
  };

  // snapshot ראשוני – מגיע מיד עם החיבור
  _sseSource.addEventListener('snapshot', (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.fixtures && d.fixtures.length) {
        LIVE_FIXTURES = d.fixtures;
        renderGameList();
        log(`📥 snapshot: ${d.count} משחקים`);
      }
    } catch(err) { log('⚠️ שגיאה ב-snapshot: ' + err); }
  });

  // update – מגיע כשיש שינוי בנתונים
  _sseSource.addEventListener('update', (e) => {
    try {
      const d = JSON.parse(e.data);
      if (d.fixtures && d.fixtures.length) {
        const prevCount = LIVE_FIXTURES.length;
        LIVE_FIXTURES = d.fixtures;
        renderGameList();
        // אם המשחק הנוכחי נבחר – רענן גם את הניתוח שלו
        if (selId) {
          const updated = LIVE_FIXTURES.find(f => f.fixture_id === selId);
          if (updated) renderAnalysis(updated);
        }
        log(`🔄 SSE update: ${d.count} משחקים (${d.elapsed_sec || ''}s)`);
        // הצג אינדיקטור עדכון
        _showUpdateFlash();
      }
    } catch(err) { log('⚠️ שגיאה ב-update: ' + err); }
  });

  _sseSource.onerror = () => {
    engineOnline = false;
    updateEngineStatus();
    log('⚠️ SSE התנתק – מנסה שוב בעוד 10 שניות...');
    _sseSource.close();
    _sseSource = null;
    // reconnect אוטומטי
    setTimeout(connectSSE, 10000);
  };
}

// ── fallback polling אם SSE לא נתמך ─────────────────────
function startPollingFallback() {
  log('⚠️ EventSource לא נתמך – מופעל polling כל 60 שניות');
  setInterval(async () => {
    try {
      const r = await fetch(`${ENGINE_BASE}/engine/fixtures`);
      const d = await r.json();
      if (d.fixtures && d.fixtures.length) {
        LIVE_FIXTURES = d.fixtures;
        engineOnline = true;
        renderGameList();
        updateEngineStatus();
      }
    } catch { engineOnline = false; updateEngineStatus(); }
  }, 60000);
}

// ── אינדיקטור עדכון חי ───────────────────────────────────
function _showUpdateFlash() {
  const lbl = document.getElementById('engine-lbl');
  if (!lbl) return;
  const prev = lbl.textContent;
  lbl.textContent = '⟳ מתעדכן...';
  lbl.style.color = '#27ae60';
  setTimeout(() => { lbl.textContent = prev; lbl.style.color = ''; }, 1500);
}

// ── DEMO FALLBACK ─────────────────────────────────────────
const DEMO_GAMES = {
  toto16:[
    {fixture_id:1001,round:'סבב 28',home_name:'מכבי חיפה',away_name:'הפועל ב"ש',match_date:'2026-05-20',match_time:'19:00',p1:58,px:22,p2:20,score_home:72,score_away:55,home_form:['W','W','D','W','L'],away_form:['L','D','L','W','D'],h2h:[{date:'12.1',score:'2-0',result:'W'},{date:'5.10',score:'1-1',result:'D'},{date:'3.4',score:'3-1',result:'W'}],home_win_pct:68,away_win_pct:31,home_xg:1.9,away_xg:0.8,squad_str_home:74,squad_str_away:62,fatigue_home:0.9,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:24,wind_kmh:10,rain_mm:0},factors:[{type:'good',icon:'🏠',text:'<strong>יתרון ביתי חזק</strong> – 8 ניצחונות מ-10 בבית'},{type:'warn',icon:'⚠️',text:'<strong>עומס משחקים</strong> – UEFA ביום חמישי, 2 ימי מנוחה'},{type:'neutral',icon:'📊',text:'<strong>xG</strong> – חיפה 1.9 · ב"ש 0.8'}],value_pick:'1',confidence:'high',recommendation:'נצחון ביתי (58%) – בטוח יחסית'},
    {fixture_id:1002,round:'סבב 28',home_name:'מכבי ת"א',away_name:'בית"ר י-ם',match_date:'2026-05-20',match_time:'21:00',p1:65,px:18,p2:17,score_home:81,score_away:58,home_form:['W','W','W','D','W'],away_form:['D','L','D','W','L'],h2h:[{date:'8.2',score:'3-2',result:'W'},{date:'15.11',score:'0-0',result:'D'},{date:'2.9',score:'1-0',result:'W'}],home_win_pct:72,away_win_pct:28,home_xg:2.3,away_xg:0.9,squad_str_home:85,squad_str_away:65,fatigue_home:1.0,fatigue_away:0.95,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:26,wind_kmh:8,rain_mm:0},factors:[{type:'good',icon:'⭐',text:'<strong>מומנטום גבוה</strong> – 4 ניצחונות ב-5 האחרונים'},{type:'neutral',icon:'🔴',text:'<strong>הרכב מלא</strong>'},{type:'warn',icon:'⚠️',text:'<strong>בית"ר עם מוטיבציה</strong> – נלחמת על הישארות'}],value_pick:'1',confidence:'high',recommendation:'נצחון ביתי (65%) – בטוח יחסית'},
    {fixture_id:1003,round:'סבב 28',home_name:'הפועל ת"א',away_name:'עירוני קריות',match_date:'2026-05-21',match_time:'19:30',p1:44,px:28,p2:28,score_home:60,score_away:63,home_form:['D','W','L','D','W'],away_form:['W','W','D','L','W'],h2h:[{date:'20.3',score:'1-1',result:'D'},{date:'10.12',score:'2-1',result:'W'},{date:'5.8',score:'0-2',result:'L'}],home_win_pct:49,away_win_pct:52,home_xg:1.1,away_xg:1.3,squad_str_home:66,squad_str_away:70,fatigue_home:0.85,fatigue_away:1.0,missing_home:['בלם מוביל (ספק)'],missing_away:[],weather:{condition:'Cloudy',temp_c:22,wind_kmh:18,rain_mm:0},factors:[{type:'neutral',icon:'⚖️',text:'<strong>משחק מאוזן</strong> – ניתוח מציע כפול X2'},{type:'good',icon:'🔥',text:'<strong>עירוני בפורמה</strong> – 3 ניצחונות ב-4 האחרונים'},{type:'warn',icon:'🏥',text:'<strong>הפועל ת"א</strong> – בלם מוביל ספק להגעה'}],value_pick:'X2',confidence:'medium',recommendation:'כפול X2 – מכסה 56% מהמקרים'},
    {fixture_id:1004,round:'סבב 28',home_name:'אשדוד',away_name:'הפועל חיפה',match_date:'2026-05-21',match_time:'20:00',p1:35,px:30,p2:35,score_home:48,score_away:65,home_form:['L','D','W','D','L'],away_form:['W','D','W','W','D'],h2h:[{date:'1.3',score:'0-1',result:'L'},{date:'15.10',score:'1-1',result:'D'},{date:'20.7',score:'2-0',result:'W'}],home_win_pct:38,away_win_pct:55,home_xg:0.9,away_xg:1.4,squad_str_home:58,squad_str_away:71,fatigue_home:1.0,fatigue_away:0.92,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:28,wind_kmh:12,rain_mm:0},factors:[{type:'warn',icon:'📉',text:'<strong>אשדוד בירידה</strong> – 2 ניצחונות מ-10'},{type:'good',icon:'🚀',text:'<strong>הפועל חיפה בעלייה</strong>'},{type:'neutral',icon:'📊',text:'<strong>xG</strong> – 0.9 מול 1.4'}],value_pick:'X2',confidence:'medium',recommendation:'כפול X2 – מכסה 65% מהמקרים'},
    {fixture_id:1005,round:'סבב 28',home_name:'בני סכנין',away_name:'מ.ס. אשדוד',match_date:'2026-05-22',match_time:'19:00',p1:38,px:32,p2:30,score_home:55,score_away:52,home_form:['W','L','W','D','W'],away_form:['D','W','L','D','W'],h2h:[{date:'25.2',score:'2-1',result:'W'},{date:'10.11',score:'0-0',result:'D'},{date:'18.8',score:'1-2',result:'L'}],home_win_pct:45,away_win_pct:50,home_xg:1.2,away_xg:1.1,squad_str_home:63,squad_str_away:61,fatigue_home:1.0,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:30,wind_kmh:9,rain_mm:0},factors:[{type:'neutral',icon:'⚖️',text:'<strong>משחק מאוזן</strong>'},{type:'good',icon:'🏠',text:'<strong>סכנין בבית</strong> – 6 ניצחונות ביתיים'},{type:'neutral',icon:'📊',text:'<strong>xG מאוזן</strong> – 1.2 מול 1.1'}],value_pick:'X',confidence:'medium',recommendation:'תיקו (32%) – שקול כפול X1'},
    {fixture_id:1006,round:'סבב 28',home_name:'הפועל ירושלים',away_name:'עירוני נס ציונה',match_date:'2026-05-22',match_time:'20:30',p1:52,px:26,p2:22,score_home:69,score_away:50,home_form:['W','W','D','W','W'],away_form:['L','D','L','W','D'],h2h:[{date:'14.3',score:'2-0',result:'W'},{date:'5.12',score:'1-0',result:'W'},{date:'8.9',score:'0-1',result:'L'}],home_win_pct:60,away_win_pct:35,home_xg:1.7,away_xg:0.8,squad_str_home:72,squad_str_away:58,fatigue_home:1.0,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:25,wind_kmh:11,rain_mm:0},factors:[{type:'good',icon:'🔥',text:'<strong>מומנטום מצוין</strong> – 4 ניצחונות ב-5'},{type:'good',icon:'⭐',text:'<strong>H2H חיובי</strong> – 2 ניצחונות רצופים'},{type:'neutral',icon:'📅',text:'<strong>מנוחה מלאה</strong> – 5 ימי הכנה'}],value_pick:'1X',confidence:'high',recommendation:'כפול 1X – מכסה 78% מהמקרים'}
  ],
  toto_zahav:[
    {fixture_id:2001,round:'סבב 5',home_name:'מכבי חיפה',away_name:'מכבי ת"א',match_date:'2026-05-25',match_time:'20:00',p1:40,px:25,p2:35,score_home:58,score_away:72,home_form:['W','D','W','L','W'],away_form:['W','W','W','D','W'],h2h:[{date:'10.3',score:'1-2',result:'L'},{date:'20.11',score:'1-1',result:'D'},{date:'15.7',score:'2-0',result:'W'}],home_win_pct:45,away_win_pct:60,home_xg:1.5,away_xg:1.8,squad_str_home:74,squad_str_away:85,fatigue_home:1.0,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:26,wind_kmh:10,rain_mm:0},factors:[{type:'neutral',icon:'⚖️',text:'<strong>דרבי מאוזן</strong>'},{type:'good',icon:'🏠',text:'<strong>חיפה בבית</strong>'},{type:'warn',icon:'⭐',text:'<strong>מכבי ת"א</strong> – 4 ניצחונות רצופים'}],value_pick:'X2',confidence:'medium',recommendation:'כפול X2 – מכסה 60% מהמקרים'}
  ],
  toto_layb:[
    {fixture_id:3001,round:'לייב',home_name:'מכבי חיפה',away_name:'הפועל ת"א',match_date:'2026-05-16',match_time:'19:45',p1:55,px:22,p2:23,score_home:68,score_away:52,home_form:['W','W','D','W','W'],away_form:['D','L','W','D','L'],h2h:[{date:'2.4',score:'2-0',result:'W'},{date:'18.12',score:'1-1',result:'D'},{date:'25.9',score:'3-2',result:'W'}],home_win_pct:62,away_win_pct:30,home_xg:2.1,away_xg:0.9,squad_str_home:74,squad_str_away:64,fatigue_home:1.0,fatigue_away:0.9,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:23,wind_kmh:8,rain_mm:0},factors:[{type:'good',icon:'🔴',text:'<strong>לייב</strong> – בזמן אמת'},{type:'good',icon:'🏠',text:'<strong>חיפה בבית</strong> – פייבוריטית'},{type:'neutral',icon:'📊',text:'<strong>נתוני לייב</strong> מתעדכנים'}],value_pick:'1',confidence:'high',recommendation:'נצחון ביתי (55%)'}
  ],
  toto4:[
    {fixture_id:4001,round:'סבב 12',home_name:'מכבי חיפה',away_name:'מכבי ת"א',match_date:'2026-05-23',match_time:'20:00',p1:40,px:26,p2:34,score_home:58,score_away:72,home_form:['W','D','W','L','W'],away_form:['W','W','W','D','W'],h2h:[{date:'10.3',score:'1-2',result:'L'},{date:'20.11',score:'1-1',result:'D'}],home_win_pct:45,away_win_pct:60,home_xg:1.5,away_xg:1.9,squad_str_home:74,squad_str_away:85,fatigue_home:1.0,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:27,wind_kmh:12,rain_mm:0},factors:[{type:'neutral',icon:'⚖️',text:'<strong>דרבי מאוזן</strong>'},{type:'good',icon:'🏠',text:'<strong>חיפה בבית</strong>'},{type:'warn',icon:'⭐',text:'<strong>מכבי ת"א בפורמה</strong>'}],value_pick:'X2',confidence:'medium',recommendation:'כפול X2 – מכסה 60%'},
    {fixture_id:4002,round:'סבב 12',home_name:'בית"ר י-ם',away_name:'הפועל ב"ש',match_date:'2026-05-23',match_time:'21:00',p1:50,px:27,p2:23,score_home:67,score_away:52,home_form:['D','W','W','D','W'],away_form:['L','D','L','D','W'],h2h:[{date:'5.2',score:'2-1',result:'W'},{date:'8.10',score:'0-0',result:'D'}],home_win_pct:58,away_win_pct:36,home_xg:1.6,away_xg:0.8,squad_str_home:72,squad_str_away:61,fatigue_home:1.0,fatigue_away:1.0,missing_home:[],missing_away:[],weather:{condition:'Clear',temp_c:25,wind_kmh:9,rain_mm:0},factors:[{type:'good',icon:'🔥',text:'<strong>בית"ר בפורמה</strong>'},{type:'good',icon:'🏟️',text:'<strong>טדי – מבצר</strong>'},{type:'neutral',icon:'📊',text:'<strong>xG 1.6 מול 0.8</strong>'}],value_pick:'1X',confidence:'high',recommendation:'כפול 1X – מכסה 77%'}
  ]
};

// ── STATE ────────────────────────────────────────────────────
let curType = 'toto16';
let selId   = null;

// ── ENGINE API ───────────────────────────────────────────────
function getGames(type) {
  if (engineOnline && LIVE_FIXTURES.length) {
    return LIVE_FIXTURES;
  }
  return DEMO_GAMES[type] || [];
}

function updateEngineStatus() {
  const dot = document.getElementById('engine-dot');
  const lbl = document.getElementById('engine-lbl');
  if (!dot) return;
  if (engineOnline) {
    dot.style.display = '';
    if (lbl) lbl.style.display = '';
    dot.style.background = '#27ae60';
    lbl.textContent = '📡 מנוע חי – עדכון אוטומטי';
  } else {
    dot.style.background = '#e8a030';
    if (lbl) { lbl.style.display = 'none'; } if (dot) { dot.style.display = 'none'; }
  }
}

function log(msg) { console.log(`[Mandeles] ${msg}`); }

// ── XSS helper ──────────────────────────────────────────────
function _esc(s) {
  if (typeof s !== 'string') return s;
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#039;');
}

// ── NAV ──────────────────────────────────────────────────────
function switchProduct(p) {
  ['product-lotto','product-toto','about','legal','accessibility'].forEach(
    id => document.getElementById(id).style.display = 'none');
  document.getElementById('product-'+p).style.display = 'block';
  document.querySelectorAll('.main-tab').forEach(t => {
    t.classList.toggle('active', t.id==='tab-'+p);
    t.setAttribute('aria-selected', t.id==='tab-'+p);
  });
  if (p === 'toto') renderGameList();
  window.scrollTo(0,0); closeNav();
}
function showPage(p) {
  ['product-lotto','product-toto','about','legal','accessibility'].forEach(
    id => document.getElementById(id).style.display='none');
  document.getElementById(p).style.display='block';
  const el = document.getElementById(p+'-main')||document.getElementById(p);
  if (el) el.focus();
  window.scrollTo(0,0); closeNav();
}
function toggleNav() {
  const l=document.getElementById('nav-list'),b=document.querySelector('.nav-menu-btn');
  const o=l.classList.toggle('open'); b.setAttribute('aria-expanded',o);
}
function closeNav() {
  document.getElementById('nav-list').classList.remove('open');
  document.querySelector('.nav-menu-btn').setAttribute('aria-expanded','false');
}

// ── LOTTO CHECK ───────────────────────────────────────────────
async function checkLotto() {
  const ins  = document.querySelectorAll('.num-input');
  const nums = Array.from(ins).map(i=>parseInt(i.value)).filter(n=>!isNaN(n)&&n>=1&&n<=37);
  const r    = document.getElementById('lotto-result');
  if (nums.length!==6) { r.className='status rejected show'; r.textContent='⚠️ נא להזין 6 מספרים תקינים'; return; }
  if (new Set(nums).size!==6) { r.className='status rejected show'; r.textContent='⚠️ כל המספרים חייבים להיות שונים'; return; }
  r.className='status loading show'; r.textContent='⏳ בודק במאגר...';
  try {
    const res = await fetch('/api/check', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({numbers: nums}),
      signal: AbortSignal.timeout(3000)
    });
    const d = await res.json();
    r.className = 'status '+(d.status==='approved'?'approved':'rejected')+' show';
    r.textContent = (d.status==='approved'?'✅ ':'❌ ') + d.message;
  } catch {
    const ok = nums.reduce((a,b)=>a+b,0)%3!==0;
    r.className='status '+(ok?'approved':'rejected')+' show';
    r.textContent = ok ? '✅ הצירוף עבר את הסינון! ' : '❌ הצירוף לא עמד בקריטריונים ';
  }
}
document.querySelectorAll('.num-input').forEach((inp,i,arr) => {
  inp.addEventListener('input', () => {
    if (parseInt(inp.value)<1) inp.value=1;
    if (parseInt(inp.value)>37) inp.value=37;
    if (String(inp.value).length>=2 && i<arr.length-1) arr[i+1].focus();
  });
});

// ── GAME TYPE ─────────────────────────────────────────────────
function selectGameType(type, btn) {
  curType=type; selId=null;
  document.querySelectorAll('.game-type-btn').forEach(b => {
    b.classList.remove('active'); b.setAttribute('aria-pressed','false');
  });
  btn.classList.add('active'); btn.setAttribute('aria-pressed','true');
  renderGameList();
  document.getElementById('analysis-content').innerHTML =
    '<div class="empty-state"><span class="es-icon">⚽</span><p>בחר משחק לניתוח</p></div>';
}

// ── GAME LIST ─────────────────────────────────────────────────
function renderGameList() {
  const games = getGames(curType);
  const list  = document.getElementById('game-list');
  if (!games.length) {
    list.innerHTML='<p style="color:var(--muted);font-size:.83rem;padding:8px">⏳ טוען נתונים...</p>';
    return;
  }
  list.innerHTML = games.map(g => {
    const id   = g.fixture_id;
    const home = g.home_name;
    const away = g.away_name;
    const date = g.match_date ? g.match_date.slice(5).split('-').reverse().join('.') + ' | ' + (g.match_time||'20:00') : '';
    const scoreBar = g.score_home != null
      ? `<div style="display:flex;gap:4px;margin-top:4px;align-items:center">
           <div style="font-size:.65rem;color:var(--muted)">ציון</div>
           <div style="background:rgba(39,174,96,.15);color:#6adba6;font-size:.65rem;font-weight:700;padding:1px 6px;border-radius:4px">${Math.round(g.score_home)}</div>
           <div style="font-size:.65rem;color:var(--muted)">–</div>
           <div style="background:rgba(231,76,60,.12);color:#f07070;font-size:.65rem;font-weight:700;padding:1px 6px;border-radius:4px">${Math.round(g.score_away)}</div>
         </div>` : '';
    return `
    <div class="game-item ${selId===id?'selected':''}" role="listitem" tabindex="0"
      onclick="selectGame(${id})" onkeydown="if(event.key==='Enter'||event.key===' ')selectGame(${id})"
      aria-label="${home} נגד ${away}">
      <div class="gi-teams">
        <span class="gi-round">${g.round||''}</span>
        <div class="gi-home">${home}</div>
        <div class="gi-vs">נגד</div>
        <div class="gi-away">${away}</div>
        <div style="font-size:.69rem;color:var(--muted);margin-top:3px">📅 ${date}</div>
        ${scoreBar}
      </div>
      <div class="odds-pills">
        <span class="odd-pill odd-1">1·${g.p1}%</span>
        <span class="odd-pill odd-x">X·${g.px}%</span>
        <span class="odd-pill odd-2">2·${g.p2}%</span>
      </div>
    </div>`;
  }).join('');
}

function selectGame(id) {
  selId = id;
  document.querySelectorAll('.game-item').forEach(el=>el.classList.remove('selected'));
  const games = getGames(curType);
  const idx   = games.findIndex(g=>g.fixture_id===id);
  if (idx>=0) document.querySelectorAll('.game-item')[idx].classList.add('selected');
  renderAnalysis(id);
  document.getElementById('analysis-section').scrollIntoView({behavior:'smooth',block:'start'});
}

// ── ANALYSIS RENDER ───────────────────────────────────────────
function renderAnalysis(id) {
  const g = getGames(curType).find(x=>x.fixture_id===id);
  if (!g) return;

  const fd  = r => `<span class="form-dot fd-${r.toLowerCase()}" aria-label="${r==='W'?'ניצחון':r==='D'?'תיקו':'הפסד'}">${r}</span>`;
  const hf  = g.home_form || [];
  const af  = g.away_form || [];
  const hp  = g.home_win_pct || 0;
  const ap  = g.away_win_pct || 0;
  const xgh = +(g.home_xg||0).toFixed(2);
  const xga = +(g.away_xg||0).toFixed(2);
  const sh  = g.score_home != null ? Math.round(g.score_home) : null;
  const sa  = g.score_away != null ? Math.round(g.score_away) : null;
  const sq_h = g.squad_str_home != null ? Math.round(g.squad_str_home) : null;
  const sq_a = g.squad_str_away != null ? Math.round(g.squad_str_away) : null;
  const fat_h = g.fatigue_home != null ? Math.round(g.fatigue_home*100) : null;
  const fat_a = g.fatigue_away != null ? Math.round(g.fatigue_away*100) : null;
  const miss_h = (g.missing_home||[]).join(', ') || 'אין נעדרים ידועים';
  const miss_a = (g.missing_away||[]).join(', ') || 'אין נעדרים ידועים';
  const h2h   = g.h2h || [];
  const facts  = g.factors || [];
  const pick   = g.value_pick || '–';
  const conf   = g.confidence || 'low';
  const rec    = g.recommendation || '';
  const weather = g.weather || {};

  const confC = conf==='high'?'conf-high':conf==='medium'?'conf-med':'conf-low';
  const confT = conf==='high'?'ביטחון גבוה':conf==='medium'?'ביטחון בינוני':'ביטחון נמוך';
  const valC  = pick==='X'||pick.includes('X')?'value-hot':pick==='1'||pick==='2'?'value-neutral':'value-neutral';
  const valT  = `✦ המלצה: ${pick}`;

  const weatherIcon = weather.condition==='Rain'||weather.condition==='Thunderstorm'?'🌧️':
                      weather.condition==='Cloudy'?'☁️':'☀️';
  const weatherStr  = `${weatherIcon} ${weather.temp_c!=null?Math.round(weather.temp_c)+'°C':''} ${weather.condition||''}${weather.rain_mm>0?' | גשם '+weather.rain_mm+'mm':''}`;

  const scoreBlock = sh!=null ? `
    <div style="display:flex;gap:16px;margin-bottom:16px;flex-wrap:wrap">
      <div style="background:var(--navy);border:1px solid var(--navy-b);border-radius:10px;padding:12px 18px;text-align:center;min-width:120px">
        <div style="font-size:.7rem;color:var(--muted);margin-bottom:4px">ציון כולל 0–100</div>
        <div style="display:flex;align-items:center;justify-content:center;gap:10px">
          <div>
            <div style="font-size:1.6rem;font-weight:900;color:#6adba6;line-height:1">${sh}</div>
            <div style="font-size:.68rem;color:var(--muted)">${g.home_name}</div>
          </div>
          <div style="color:var(--muted);font-size:.8rem">–</div>
          <div>
            <div style="font-size:1.6rem;font-weight:900;color:#f07070;line-height:1">${sa}</div>
            <div style="font-size:.68rem;color:var(--muted)">${g.away_name}</div>
          </div>
        </div>
        <div style="font-size:.65rem;color:var(--muted);margin-top:5px">30% הסתברות + 20% הרכב + 20% מומנטום + 15% Elo + 10% מגרש + 5% עייפות</div>
      </div>
    </div>` : '';

  document.getElementById('analysis-content').innerHTML = `
    <div style="margin-bottom:12px">
      <div style="font-size:1rem;font-weight:700;color:var(--cream)">${g.home_name} <span style="color:var(--muted)">נ'</span> ${g.away_name}</div>
      <div style="font-size:.74rem;color:var(--muted);margin-top:2px">📅 ${g.match_date||''} ${g.match_time||''} · ${g.round||''} ${weatherStr?'| '+weatherStr:''}</div>
    </div>

    ${scoreBlock}

    <div class="analysis-grid">

      <!-- הסתברויות -->
      <div class="prob-section">
        <div class="prob-title">📊 הסתברות – מנוע פואסון + שחקנים + עייפות + מזג אוויר${engineOnline?' (נתונים חיים)':' (הדגמה)'}</div>
        <div class="prob-bar-wrap" role="img" aria-label="1:${g.p1}% תיקו:${g.px}% 2:${g.p2}%">
          <div class="prob-seg prob-1" style="width:${g.p1}%">${g.p1}%</div>
          <div class="prob-seg prob-x" style="width:${g.px}%">${g.px}%</div>
          <div class="prob-seg prob-2" style="width:${g.p2}%">${g.p2}%</div>
        </div>
        <div class="prob-labels"><span>1 – ${g.home_name}</span><span>X – תיקו</span><span>2 – ${g.away_name}</span></div>
        <span class="value-badge ${valC}">${valT}</span>
      </div>

      <!-- פורמה ביתי -->
      <div>
        <div class="prob-title">📈 פורמה – ${g.home_name}</div>
        <div class="form-dots">${hf.map(fd).join('')}</div>
        <div class="stat-rows" style="margin-top:11px">
          <div class="stat-row"><span class="stat-label">% ניצחונות בית</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${hp}%;background:var(--win)"></div></div><span class="stat-val">${hp}%</span></div>
          <div class="stat-row"><span class="stat-label">xG ממוצע</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${Math.min(xgh/3*100,100)}%;background:var(--gold)"></div></div><span class="stat-val">${xgh}</span></div>
          ${sq_h!=null?`<div class="stat-row"><span class="stat-label">חוזק הרכב</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${sq_h}%;background:#7c6cd8"></div></div><span class="stat-val">${sq_h}</span></div>`:''}
          ${fat_h!=null?`<div class="stat-row"><span class="stat-label">מצב גופני</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${fat_h}%;background:${fat_h>=90?'var(--win)':fat_h>=75?'var(--gold)':'var(--loss)'}"></div></div><span class="stat-val">${fat_h}%</span></div>`:''}
        </div>
        <div style="margin-top:8px;font-size:.73rem;color:var(--muted)">🏥 נעדרים: <span style="color:${miss_h==='אין נעדרים ידועים'?'#6adba6':'#f07070'}">${miss_h}</span></div>
      </div>

      <!-- פורמה אורחים -->
      <div>
        <div class="prob-title">📉 פורמה – ${g.away_name}</div>
        <div class="form-dots">${af.map(fd).join('')}</div>
        <div class="stat-rows" style="margin-top:11px">
          <div class="stat-row"><span class="stat-label">% ניצחונות חוץ</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${ap}%;background:var(--loss)"></div></div><span class="stat-val">${ap}%</span></div>
          <div class="stat-row"><span class="stat-label">xG ממוצע</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${Math.min(xga/3*100,100)}%;background:var(--muted)"></div></div><span class="stat-val">${xga}</span></div>
          ${sq_a!=null?`<div class="stat-row"><span class="stat-label">חוזק הרכב</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${sq_a}%;background:#7c6cd8"></div></div><span class="stat-val">${sq_a}</span></div>`:''}
          ${fat_a!=null?`<div class="stat-row"><span class="stat-label">מצב גופני</span><div class="stat-bar-bg"><div class="stat-bar-fill" style="width:${fat_a}%;background:${fat_a>=90?'var(--win)':fat_a>=75?'var(--gold)':'var(--loss)'}"></div></div><span class="stat-val">${fat_a}%</span></div>`:''}
        </div>
        <div style="margin-top:8px;font-size:.73rem;color:var(--muted)">🏥 נעדרים: <span style="color:${miss_a==='אין נעדרים ידועים'?'#6adba6':'#f07070'}">${miss_a}</span></div>
      </div>

      <!-- H2H -->
      <div>
        <div class="prob-title">⚔️ עימותים ישירים H2H</div>
        ${h2h.length ? `
        <table class="h2h-table" aria-label="היסטוריית עימותים">
          <thead><tr><th>תאריך</th><th>תוצאה</th><th>סיום</th></tr></thead>
          <tbody>${h2h.map(m=>`
            <tr>
              <td>${m.date||m.d||''}</td>
              <td>${m.score||m.sc||''}</td>
              <td><span class="h2h-result h2h-${(m.result||m.r||'d').toLowerCase()}">${(m.result||m.r)==='W'?'נצחון ביתי':(m.result||m.r)==='D'?'תיקו':'נצ. אורחים'}</span></td>
            </tr>`).join('')}
          </tbody>
        </table>` : '<p style="color:var(--muted);font-size:.8rem">אין נתוני H2H</p>'}
      </div>

      <!-- גורמי X -->
      <div>
        <div class="prob-title">🔎 גורמי X – שחקנים, עייפות, מזג אוויר, מגרש</div>
        <div class="xfactor-list">
          ${facts.length ? facts.map(f=>`
            <div class="xf-item ${f.type||f.t||'neutral'}" role="note">
              <span class="xf-icon" aria-hidden="true">${f.icon||f.i||'📌'}</span>
              <span class="xf-text">${typeof DOMPurify!=='undefined'?DOMPurify.sanitize(f.text||f.tx||'',{ALLOWED_TAGS:['strong','br']}):((f.text||f.tx||'').replace(/<(?!\/?(?:strong|br))[^>]+>/gi,''))}</span>
            </div>`).join('') :
            '<p style="color:var(--muted);font-size:.8rem">אין גורמים בולטים</p>'}
        </div>
      </div>

      <!-- המלצה -->
      <div class="prob-section">
        <div class="rec-card">
          <div class="rec-header">
            <span class="rec-title">🎯 המלצת המנוע</span>
            <span class="rec-confidence ${confC}">${confT}</span>
          </div>
          <div class="rec-body">
            <strong>הימור מומלץ: ${_esc(pick)}</strong><br><br>
            ${typeof DOMPurify!=='undefined'?DOMPurify.sanitize(rec,{ALLOWED_TAGS:['strong']}):_esc(rec)}
            ${sh!=null?`<br><br><span style="font-size:.74rem;color:var(--muted)">ציון כולל: ${g.home_name} <strong style="color:#6adba6">${sh}</strong> מול ${g.away_name} <strong style="color:#f07070">${sa}</strong></span>`:''}
          </div>
        </div>
      </div>

    </div>`;
}

// ── MODAL ─────────────────────────────────────────────────────
let lastF=null;
function openModal(){lastF=document.activeElement;const m=document.getElementById('pay-modal');m.classList.add('open');m.querySelector('.modal-close').focus();document.addEventListener('keydown',onKey)}
function closeModal(){document.getElementById('pay-modal').classList.remove('open');document.removeEventListener('keydown',onKey);if(lastF)lastF.focus()}
function onKey(e){if(e.key==='Escape')closeModal()}
document.getElementById('pay-modal').addEventListener('click',function(e){if(e.target===this)closeModal()});
function selPlan(el){document.querySelectorAll('.plan-card').forEach(c=>{c.classList.remove('sel');c.setAttribute('aria-pressed','false')});el.classList.add('sel');el.setAttribute('aria-pressed','true')}
document.querySelectorAll('.plan-card').forEach(c=>c.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();c.click()}}));
function pay(m){alert(m==='stripe'?'💳 מעביר ל-Stripe Checkout...\n(יש לחבר Stripe Checkout API בשרת)':'📱 מעביר ל-PayPal...\n(יש לחבר PayPal Orders API)')}

// ── A11Y ──────────────────────────────────────────────────────
function togA11y(){const p=document.getElementById('a11y-panel-el'),b=document.querySelector('.a11y-fab');const o=p.classList.toggle('open');b.setAttribute('aria-expanded',o)}
function togMode(cls,btn){document.body.classList.toggle(cls);const on=document.body.classList.contains(cls);btn.classList.toggle('on',on);btn.setAttribute('aria-pressed',on)}
if(window.matchMedia('(prefers-reduced-motion:reduce)').matches) document.body.classList.add('no-motion');

// ── עזרים ────────────────────────────────────────────────────
function getCookie(n){const m=document.cookie.match('(^|;)\\s*'+n+'\\s*=\\s*([^;]+)');return m?m.pop():null;}
function goToWallet(){window.location.href='/wallet.html';}
function goToProfile(){window.location.href='/profile.html';}
function goToLottoForm(){
  const token=localStorage.getItem('auth_token')||localStorage.getItem('fb_token');
  const isDemo=localStorage.getItem('demo_mode')==='1';
  if(!token&&!isDemo){
    window.location.href='/login/?redirect=/classic/lotto_form.html';
  } else {
    window.location.href='/classic/lotto_form.html';
  }
}
function goToAuth(redirect){window.location.href='/login/'+(redirect?'?redirect='+encodeURIComponent(redirect):'');}
function goPremium(){
  const user=localStorage.getItem('auth_token');
  if(user){const m=document.getElementById('pay-modal');m.classList.add('open');m.querySelector('.modal-close').focus();document.addEventListener('keydown',onKey);}
  else{goToAuth('/');}
}

// ══════════════════════════════════════════════════════════
// AUTH – תומך גם ב-Firebase token (auth_token) וגם ב-demo
// ══════════════════════════════════════════════════════════

// DEMO_USER: נתוני משתמש מדומה לצורך פיתוח/בדיקות
const DEMO_USER = {
  name: 'דמו',
  email: 'demo@mandeles.co.il',
  balance: 500,
  sets: Array.from({length:10},(_,i)=>({
    set_index:i+1,
    n1:i+1,n2:i+7,n3:i+13,n4:i+19,n5:i+25,n6:Math.min(i+31,37),
    strong:(i%7)+1,
    draw_date: new Date().toISOString().slice(0,10)
  }))
};

function _applyLoggedInUI(name, token, isDemoMode){
  const loginBtn=document.getElementById('nav-login-btn');
  if(!loginBtn) return;
  loginBtn.outerHTML=`
    ${isDemoMode?`<span style="font-size:.65rem;background:rgba(232,160,48,.15);border:1px solid rgba(232,160,48,.3);color:#e8c870;border-radius:5px;padding:3px 7px;flex-shrink:0">🧪 DEMO</span>`:''}
    <span class="wallet-badge" onclick="goToWallet()" title="ארנק">💳 ₪<span id="wallet-bal">${isDemoMode?DEMO_USER.balance.toFixed(2):'...'}</span></span>
    <button id="user-avatar" onclick="goToProfile()" aria-label="פרופיל">${_esc(name[0].toUpperCase())}</button>`;
  if(!isDemoMode) loadWalletBalance(token);
}

function checkAuth(){
  const loginBtn=document.getElementById('nav-login-btn');
  // בדוק DEMO mode
  if(localStorage.getItem('demo_mode')==='1'){
    _applyLoggedInUI(DEMO_USER.name, null, true);
    unlockPremium(DEMO_USER.sets);
    return;
  }
  // בדוק Firebase/JWT token — תומך גם ב-auth_token וגם ב-fb_token (legacy)
  const token = localStorage.getItem('auth_token') || localStorage.getItem('fb_token');
  if(!token){ if(loginBtn)loginBtn.style.display='flex'; return; }
  // אם יש token — נסה לאמת מול השרת
  fetch('/auth/me',{
    headers:{'Authorization':'Bearer '+token},
    signal: AbortSignal.timeout(3000)
  })
    .then(r=>{
      if(!r.ok){
        // שרת החזיר שגיאה — נסה להשתמש בנתוני Firebase ישירות
        _tryFirebaseToken(token, loginBtn);
        return null;
      }
      return r.json();
    })
    .then(u=>{
      if(!u) return;
      const name=u.name||u.phone||u.email||'U';
      _applyLoggedInUI(name, token, false);
      checkSubscription(token);
    })
    .catch(()=>{
      // השרת לא פעיל — נסה Firebase token ישירות
      _tryFirebaseToken(token, loginBtn);
    });
}

// כשהשרת לא פעיל — decode Firebase token ישירות (ללא אימות חתימה, לצרכי UI בלבד)
function _tryFirebaseToken(token, loginBtn){
  try{
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')));
    const name = payload.name || payload.email || payload.phone_number || 'משתמש';
    const exp  = payload.exp || 0;
    if(Date.now()/1000 > exp){ // פג תוקף
      localStorage.removeItem('auth_token'); localStorage.removeItem('fb_token');
      if(loginBtn) loginBtn.style.display='flex'; return;
    }
    _applyLoggedInUI(name, token, false);
    // שרת לא פעיל — אנחנו יכולים לפחות להציג שמחובר, אבל לא נפתח Premium ללא אימות
    log('⚠️ שרת auth לא פעיל — מציג UI מחובר ללא אימות מנוי');
  }catch(e){
    log('⚠️ token לא תקין: '+e.message);
    if(loginBtn) loginBtn.style.display='flex';
  }
}

async function loadWalletBalance(token){
  try{
    const r=await fetch('/auth/wallet/balance',{
      headers:{'Authorization':'Bearer '+token},
      signal: AbortSignal.timeout(3000)
    });
    if(!r.ok) return;
    const d=await r.json();
    const el=document.getElementById('wallet-bal');
    if(el)el.textContent=(d.balance||0).toFixed(2);
  }catch{}
}

// ── בדיקת מנוי ────────────────────────────────────────────
async function checkSubscription(token){
  try{
    const r=await fetch('/lotto/my-sets',{
      headers:{'Authorization':'Bearer '+token},
      signal: AbortSignal.timeout(3000)
    });
    if(!r.ok) return;
    const d=await r.json();
    const hasSub = d.sets && d.sets.length > 0;
    if(hasSub) unlockPremium(d.sets);
  }catch(e){ log('sub check: '+e.message); }
}

// ── כפתור DEMO מצב פיתוח ─────────────────────────────────
async function activateDemoMode(){
  // התחבר עם חשבון הדמו האמיתי מהשרת
  try{
    const r = await fetch('/auth/login/email', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({email:'demo@mandeles.co.il', password:'Demo1234!'})
    });
    const d = await r.json();
    if(d.token){
      localStorage.setItem('auth_token', d.token);
      localStorage.setItem('demo_mode', '1');
      window.location.reload();
    } else {
      // fallback — אם השרת לא עובד, השתמש ב-demo_mode רגיל
      localStorage.setItem('demo_mode','1');
      window.location.reload();
    }
  } catch(e){
    // השרת לא זמין — demo מקומי
    localStorage.setItem('demo_mode','1');
    window.location.reload();
  }
}
function deactivateDemoMode(){
  localStorage.removeItem('demo_mode');
  localStorage.removeItem('auth_token');
  localStorage.removeItem('fb_token');
  window.location.href='/';
}

function unlockPremium(sets){
  // החלף כל כפתור "רכוש לגישה" בכפתור "מלא טפסים"
  document.querySelectorAll('.btn-locked').forEach(btn=>{
    btn.outerHTML=`<button class="btn btn-primary" onclick="goToProfile()" style="width:100%;background:var(--win)">✅ מלא טפסים</button>`;
  });
  // הסתר lock badges
  document.querySelectorAll('.lock-badge').forEach(el=>{
    el.innerHTML='✅ פעיל';
    el.style.background='rgba(39,174,96,.15)';
    el.style.borderColor='rgba(39,174,96,.3)';
    el.style.color='var(--win)';
  });
  // עדכן כפתור hero
  const heroBtn=document.querySelector('.btn.btn-primary[onclick*="goPremium"]');
  if(heroBtn){
    heroBtn.textContent='⭐ לפרופיל שלי';
    heroBtn.onclick=goToProfile;
  }
  // הצג כמה סטים יש
  const lpTitle=document.getElementById('lp-title');
  if(lpTitle) lpTitle.textContent=`✅ יש לך ${sets.length} סטים — אסטרטגיות פעילות`;
  console.log(`✅ מנוי פעיל — ${sets.length} סטים`);
}

// ── סטטיסטיקות אתר ────────────────────────────────────────
function _setStats(wins,prize,members){
  const tw=document.getElementById('stat-total-wins');
  const tp=document.getElementById('stat-total-prize');
  const tm=document.getElementById('stat-members');
  if(tw)tw.textContent=Number(wins).toLocaleString('he-IL');
  if(tp)tp.textContent='₪'+Number(prize).toLocaleString('he-IL');
  if(tm)tm.textContent=Number(members).toLocaleString('he-IL');
}
async function loadSiteStats(){
  _setStats(0,0,0);  // מיד מציג 0 במקום "טוען..."
  try{
    const ctrl=new AbortController();
    setTimeout(()=>ctrl.abort(),4000);
    const r=await fetch('/api/stats',{signal:ctrl.signal});
    if(!r.ok)return;
    const d=await r.json();
    _setStats(d.total_wins||0,d.total_prize||0,d.active_members||0);
  }catch(e){
    console.log('stats:',e.name==='AbortError'?'timeout':e.message);
  }
}

// ── INIT ──────────────────────────────────────────────────────
(function() {
  // הצג כפתור DEMO אם השרת לא פעיל ואין טוקן
  const hasTok = localStorage.getItem('auth_token')||localStorage.getItem('fb_token')||localStorage.getItem('demo_mode');
  if(!hasTok){
    fetch('/auth/me',{signal:AbortSignal.timeout(1500)})
      .catch(()=>{ const b=document.getElementById('demo-btn'); if(b)b.style.display='block'; });
  }
  if(localStorage.getItem('demo_mode')==='1'){
    const b=document.getElementById('demo-btn');
    if(b){ b.textContent='🧪 יציאה מ-DEMO'; b.onclick=deactivateDemoMode; b.style.display='block'; }
  }
  // בדיקת auth + סטטיסטיקות

  // תמיכה ב-?tab= לניווט ישיר מדפים אחרים
  (function(){
    var tab = new URLSearchParams(window.location.search).get('tab');
    if(tab === 'toto') switchProduct('toto');
    else if(tab === 'about') showPage('about');
    else if(tab === 'legal') showPage('legal');
    else if(tab === 'accessibility') showPage('accessibility');
  })();

  checkAuth();
  loadSiteStats();
  // SSE / polling לנתוני טוטו
  if (typeof EventSource !== 'undefined') {
    connectSSE();
  } else {
    startPollingFallback();
  }
  renderGameList();
})();
