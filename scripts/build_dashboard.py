"""Static dashboard builder (GitHub Pages pattern from the controversy project).
Run:  python3 scripts/build_dashboard.py  ->  docs/index.html
"""
import sys, os, json, datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import store

ROOT = os.path.join(os.path.dirname(__file__), "..")
DB = os.path.join(ROOT, "data", "trust.db")

CSS = """
:root{--bg:#0e1116;--panel:#171c24;--line:#262d38;--fg:#e6e9ee;--mut:#8b94a1;
--pos:#3fb27f;--neg:#e05d5d;--warn:#d9a441;--acc:#5b8dd9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:20px;margin:0 0 4px}h2{font-size:14px;text-transform:uppercase;
letter-spacing:.08em;color:var(--mut);margin:32px 0 12px}
.sub{color:var(--mut);font-size:13px;margin-bottom:20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.kpi .v{font-size:26px;font-weight:650}.kpi .l{color:var(--mut);font-size:12px;margin-top:2px}
.badge{display:inline-block;font-size:10px;font-weight:700;letter-spacing:.06em;
padding:2px 7px;border-radius:99px;vertical-align:middle;margin-left:6px}
.b-prov{background:#3a2f14;color:var(--warn)} .b-low{background:#331b1b;color:var(--neg)}
.b-thin{background:#1b2733;color:var(--acc)} .b-ok{background:#14301f;color:var(--pos)}
.b-bad{background:#331b1b;color:var(--neg)}
.lenses{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px}
.lens{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px}
.bar{height:8px;background:#0a0d11;border-radius:99px;position:relative;margin:10px 0 4px}
.bar .fill{position:absolute;top:0;bottom:0;border-radius:99px}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{padding:9px 10px;text-align:left;border-bottom:1px solid var(--line);font-size:13px}
th{color:var(--mut);font-size:11px;text-transform:uppercase;letter-spacing:.05em;
cursor:pointer;user-select:none}
tr.co{cursor:pointer} tr.co:hover{background:#1c232e}
td.drill{background:#11151c;font-size:12px;color:var(--mut)}
td.drill a{color:var(--acc);text-decoration:none} td.drill a:hover{text-decoration:underline}
.pos{color:var(--pos)} .neg{color:var(--neg)} .mut{color:var(--mut)}
.note{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px;font-size:12.5px;color:var(--mut);margin-top:12px}
.btn{display:inline-block;background:var(--acc);color:#fff;font-weight:600;
font-size:13px;padding:7px 14px;border-radius:8px;text-decoration:none;
margin-left:12px;vertical-align:middle}
.btn:hover{filter:brightness(1.15)} .btn-note{font-size:11px;color:var(--mut)}
.anchors li{margin-bottom:6px;font-size:13px}
.anchors a{color:var(--acc);text-decoration:none}
@media(max-width:640px){.kpi .v{font-size:22px} th:nth-child(6),td:nth-child(6){display:none}}
"""

JS = """
const D = window.__DATA__;
function esc(s){return (s||'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function dirCls(v){return v==null?'mut':(v>=50?'pos':'neg')}
function lensCard(l){
  const v=l.value==null?'—':((l.value+2)/4*100).toFixed(1);
  const pct=l.value==null?50:((l.value+2)/4*100);
  const col=pct>=50?'var(--pos)':'var(--neg)';
  const srcs=(l.sources||[]).map(s=>`<span class="mut">${esc(s.source)}</span> w=${(100*s.w).toFixed(0)}%`).join(' · ');
  return `<div class="lens"><div><b>${esc(l.lens)}</b>
    <span class="badge b-prov">PROVISIONAL</span>${l.published?'':' <span class="badge b-bad">LOW COVERAGE</span>'}</div>
    <div class="v" style="font-size:24px;font-weight:650" class="${dirCls(pct)}">${v}<span class="mut" style="font-size:12px"> /100 · n_eff ${l.n_eff??'—'}</span></div>
    <div class="bar"><div class="fill" style="left:0;width:${pct}%;background:${col}"></div></div>
    <div class="mut" style="font-size:11px">${srcs||'no sources reported'}</div></div>`;
}
function spark(hist){
  if(!hist||hist.length<2) return '';
  const W=200,H=36;
  const xs=hist.map((p,i)=>i/(hist.length-1)*W);
  const ys=hist.map(p=>H-3-(p.v/100)*(H-6));
  const last=hist[hist.length-1].v, col=last>=50?'var(--pos)':'var(--neg)';
  return `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="vertical-align:middle"><polyline points="${xs.map((x,i)=>x.toFixed(1)+','+ys[i].toFixed(1)).join(' ')}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
}
function trend(){
  const t=D.trend||{composite:[],lenses:{}};
  const days=[...new Set([...(t.composite||[]).map(p=>p.day),
    ...Object.values(t.lenses||{}).flat().map(p=>p.day)])].sort();
  if(days.length<2){
    document.getElementById('trend').innerHTML='<div class="note">Trend charts populate as daily runs accumulate (currently '+days.length+' day'+(days.length===1?'':'s')+'). The 06:00 UTC cron adds one point per day.</div>';
    return;
  }
  const W=680,H=200,pad=34;
  const X=i=>pad+i/(days.length-1)*(W-2*pad);
  const Y=v=>H-pad-((v||0)/100)*(H-2*pad);
  const colors={public:'#5b8dd9',media:'#d9a441',business:'#3fb27f',technical:'#b07fd9'};
  const idx=Object.fromEntries(days.map((d,i)=>[d,i]));
  let s=`<svg viewBox="0 0 ${W} ${H}" style="width:100%;background:var(--panel);border:1px solid var(--line);border-radius:10px">`;
  const c=t.composite||[];
  if(c.length>1){
    s+=`<polygon points="${c.map(p=>X(idx[p.day])+','+Y(p.hi)).join(' ')} ${c.slice().reverse().map(p=>X(idx[p.day])+','+Y(p.lo)).join(' ')}" fill="#5b8dd9" opacity="0.15"/>`;
    s+=`<polyline points="${c.map(p=>X(idx[p.day])+','+Y(p.v)).join(' ')}" fill="none" stroke="#e6e9ee" stroke-width="2.5"/>`;
  }
  for(const [lens,pts] of Object.entries(t.lenses||{})){
    const pp=pts.filter(p=>p.day in idx);
    if(pp.length>1) s+=`<polyline points="${pp.map(p=>X(idx[p.day])+','+Y(p.v)).join(' ')}" fill="none" stroke="${colors[lens]||'#888'}" stroke-width="1.5"/>`;
  }
  s+=`<text x="${pad}" y="${Y(100)-6}" fill="#8b94a1" font-size="10">100</text>`;
  s+=`<text x="${pad}" y="${Y(0)+12}" fill="#8b94a1" font-size="10">0</text>`;
  s+=`<text x="${X(0)}" y="${H-6}" fill="#8b94a1" font-size="10">${days[0]}</text>`;
  s+=`<text x="${X(days.length-1)-60}" y="${H-6}" fill="#8b94a1" font-size="10">${days[days.length-1]}</text>`;
  s+='</svg>';
  const legend=['<span style="color:#e6e9ee">— composite (90% band)</span>']
    .concat(Object.keys(t.lenses||{}).map(l=>`<span style="color:${colors[l]||'#888'}">— ${l}</span>`)).join(' · ');
  const tl=(t.gdelt_tone||[]).filter(r=>r.tone!=null);
  let tlHtml='';
  const tlDays=[...new Set(tl.map(r=>r.day))].sort();
  if(tlDays.length>=2){
    const W2=680,H2=110,pad2=34;
    const vals=tl.map(r=>r.tone), lo=Math.min(...vals), hi=Math.max(...vals);
    const span=(hi-lo)||1, mid=(hi+lo)/2;
    const X2=i=>pad2+i/(tlDays.length-1)*(W2-2*pad2);
    const Y2=v=>H2-pad2+10-((v-lo)/span)*(H2-2*pad2-20);
    const idx2=Object.fromEntries(tlDays.map((d,i)=>[d,i]));
    const bySrc={};
    tl.forEach(r=>{(bySrc[r.source]=bySrc[r.source]||[]).push(r);});
    const tcol={gdelt:'#d9a441',gdelt_biz:'#3fb27f'};
    let s2=`<svg viewBox="0 0 ${W2} ${H2}" style="width:100%;background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-top:8px">`;
    for(const [src,rows] of Object.entries(bySrc)){
      const pp=rows.filter(r=>r.day in idx2).sort((a,b)=>a.day<b.day?-1:1);
      if(pp.length>1) s2+=`<polyline points="${pp.map(r=>X2(idx2[r.day])+','+Y2(r.tone)).join(' ')}" fill="none" stroke="${tcol[src]||'#888'}" stroke-width="1.5"/>`;
    }
    s2+=`<text x="${pad2}" y="${Y2(hi)+3}" fill="#8b94a1" font-size="10">${hi.toFixed(1)}</text>`;
    s2+=`<text x="${pad2}" y="${Y2(lo)+10}" fill="#8b94a1" font-size="10">${lo.toFixed(1)}</text>`;
    s2+=`<text x="${X2(0)}" y="${H2-4}" fill="#8b94a1" font-size="10">${tlDays[0]}</text>`;
    s2+=`<text x="${X2(tlDays.length-1)-60}" y="${H2-4}" fill="#8b94a1" font-size="10">${tlDays[tlDays.length-1]}</text>`;
    s2+='</svg>';
    const tleg=Object.keys(bySrc).map(s=>`<span style="color:${tcol[s]||'#888'}">— ${s==='gdelt'?'all media':'financial press'}</span>`).join(' · ');
    tlHtml='<div class="mut" style="font-size:12px;margin-top:8px"><b>GDELT tone</b> (raw GKG files, full coverage — word-list measure with a known negative lean: read day-to-day change, never the level) '+tleg+'</div>'+s2;
  } else if(tl.length===1){
    tlHtml='<div class="mut" style="font-size:12px;margin-top:4px">GDELT native tone (word-list — use day-to-day change, never the level): latest '
      +tl[tl.length-1].tone+' on '+(tl[tl.length-1].n||0).toLocaleString()+' articles</div>';
  }
  document.getElementById('trend').innerHTML=s+'<div class="mut" style="font-size:12px;margin-top:6px">'+legend+'</div>'+tlHtml;
}
function render(){
  trend();
  const c=D.composite||{};
  document.getElementById('kpis').innerHTML=`
    <div class="kpi"><div class="v">${c.value??'—'}<span class="mut" style="font-size:13px"> /100</span>
      <span class="badge b-prov">PROVISIONAL</span></div>
      <div class="l">Field composite (societal view) · 90% band ${c.lo??'—'}–${c.hi??'—'}</div></div>
    <div class="kpi"><div class="v">${D.investor?.value??'—'}</div>
      <div class="l">Investor view composite</div></div>
    <div class="kpi"><div class="v">${D.survey_gap?D.survey_gap.gap.toFixed(1):'—'}</div>
      <div class="l">Survey gap: discourse vs ${esc(D.survey_gap?.anchor_id||'')} (${esc(D.survey_gap?.anchor_geo||'')}, ${D.survey_gap?.anchor_value??'—'})<br><b>INDICATIVE — uncalibrated, b=0 priors</b></div></div>
    <div class="kpi"><div class="v">${D.n_items}</div>
      <div class="l">Items scored ${esc(D.day)}</div></div>`;
  document.getElementById('lenses').innerHTML=D.lenses.map(lensCard).join('');
  const tb=document.getElementById('cobody');
  tb.innerHTML=D.companies.map((co,i)=>`
    <tr class="co" data-i="${i}"><td><b>${esc(co.name)}</b>${co.private?' <span class="mut" title="private company">◦</span>':''}</td>
    <td class="${dirCls(co.score)}">${co.score?.toFixed(1)??'—'}</td>
    <td class="${co.rel_to_field>=0?'pos':'neg'}">${co.rel_to_field==null?'—':(co.rel_to_field>0?'+':'')+co.rel_to_field.toFixed(1)}</td>
    <td>${co.n_eff}${co.low_confidence?' <span class="badge b-low">LOW CONF</span>':''}</td>
    <td>${co.n_lenses}</td><td class="mut">${esc(co.top_topic||'')}</td></tr>
    <tr class="dr" style="display:none"><td colspan="6" class="drill" id="dr${i}"></td></tr>`).join('');
  tb.querySelectorAll('tr.co').forEach(tr=>tr.onclick=()=>{
    const i=tr.dataset.i, co=D.companies[i], row=tr.nextElementSibling;
    const open=row.style.display!=='none';
    tb.querySelectorAll('tr.dr').forEach(r=>r.style.display='none');
    if(open) return;
    const items=(co.top_items||[]).map(it=>`<div>• <a href="${esc(it.url)}" target="_blank" rel="noopener">${esc(it.title||'(no title)')}</a>
      <span class="mut"> — ${esc(it.source)}, dir ${it.direction>0?'+':''}${it.direction}, ${esc(it.dimension||'')}</span></div>`).join('');
    document.getElementById('dr'+i).innerHTML=(spark(co.history)?'<div style="margin-bottom:6px">'+spark(co.history)+' <span class="mut" style="font-size:11px">score history</span></div>':'')+(items||'<span class="mut">No scored items in window.</span>');
    row.style.display='';
  });
  document.getElementById('srcstatus').innerHTML='<table><tr><th>Source</th><th>Lens</th><th>Status</th><th>Items</th><th>Detail</th></tr>'+
    D.sources.map(s=>`<tr><td>${esc(s.source)}</td><td class="mut">${esc(s.lens)}</td>
    <td>${s.status==='ok'?'<span class="badge b-ok">OK</span>':'<span class="badge b-bad">'+esc(s.status.toUpperCase())+'</span>'}</td>
    <td>${s.n_items}</td><td class="mut">${esc(s.detail||'')}</td></tr>`).join('')+'</table>';
  document.getElementById('anchors').innerHTML='<ul class="anchors">'+D.anchors.map(a=>
    `<li><b>${a.value}</b> — ${esc(a.provider)}, ${esc(a.wave)} (${esc(a.geo)}, fieldwork to ${esc(a.fieldwork_end)})
     · <span class="mut">${esc(a.metric_family)}</span> · <a href="${esc(a.url)}" target="_blank" rel="noopener">source</a></li>`).join('')+'</ul>';
}
document.addEventListener('DOMContentLoaded',render);
"""

def build(day=None):
    con = store.connect(DB)
    day = day or con.execute(
        "SELECT COALESCE((SELECT MAX(day) FROM composite_daily), "
        "(SELECT MAX(day) FROM items))").fetchone()[0]
    comp = con.execute("SELECT value, lo, hi FROM composite_daily WHERE day=? AND view='societal'",
                       (day,)).fetchone()
    inv = con.execute("SELECT value FROM composite_daily WHERE day=? AND view='investor'",
                      (day,)).fetchone()
    lenses = []
    for lens, value, se, n_eff, cov, pub in con.execute(
            "SELECT lens, value, se, n_eff, coverage, published FROM lens_daily WHERE day=?",
            (day,)):
        srcs = []
        wrows = con.execute(
            "SELECT source, se FROM series WHERE day=? AND lens=? AND target='field'",
            (day, lens)).fetchall()
        if wrows:
            import combine as cmb
            _, _, meta = cmb.blend_lens([dict(source=s, wmean=0, se=se2, n_eff=1)
                                         for s, se2 in wrows])
            srcs = [{"source": s, "w": meta["weights"].get(s, 0)} for s, _ in wrows]
        lenses.append({"lens": lens, "value": value, "se": se, "n_eff": n_eff,
                       "coverage": cov, "published": pub, "sources": srcs})
    companies = []
    import yaml
    with open(os.path.join(ROOT, "config", "companies.yaml")) as f:
        meta_co = {c["id"]: c for c in yaml.safe_load(f)["companies"]}
    co_hist = {}
    for cid2, d2, s2 in con.execute(
            "SELECT company_id, day, score FROM company_daily ORDER BY day"):
        co_hist.setdefault(cid2, []).append({"day": d2, "v": s2})
    for r in con.execute("""SELECT company_id, score, rel_to_field, n_eff, n_lenses,
            low_confidence, top_topic FROM company_daily WHERE day=?
            ORDER BY n_eff DESC""", (day,)):
        cid = r[0]
        tops = [{"title": t[0], "url": t[1], "source": t[2], "direction": t[3],
                 "dimension": t[4]} for t in con.execute("""
            SELECT i.title, i.url, i.source, i.direction, i.dimension
            FROM items i JOIN item_companies ic ON ic.item_id=i.item_id
            WHERE ic.company_id=? AND i.relevance>=0.5
            ORDER BY ABS(i.direction) DESC, i.reach DESC LIMIT 8""", (cid,))]
        companies.append({"id": cid, "name": meta_co.get(cid, {}).get("name", cid),
                          "private": meta_co.get(cid, {}).get("private", False),
                          "score": r[1], "rel_to_field": r[2], "n_eff": r[3],
                          "n_lenses": r[4], "low_confidence": r[5],
                          "top_topic": r[6], "top_items": tops,
                          "history": co_hist.get(cid, [])})
    sources = [{"source": r[0], "lens": r[1], "status": r[2], "detail": r[3], "n_items": r[4]}
               for r in con.execute("""SELECT s.source, p.lens, s.status, s.detail, s.n_items
                   FROM source_status s LEFT JOIN (SELECT DISTINCT source, lens FROM items) p
                   ON p.source=s.source WHERE s.day=?""", (day,))]
    # lens for sources with no items: fall back to parameters
    import yaml as _y
    with open(os.path.join(ROOT, "config", "parameters.yaml")) as f:
        plens = {k: v["lens"] for k, v in _y.safe_load(f)["sources"].items()}
    for s in sources:
        s["lens"] = s["lens"] or plens.get(s["source"], "")
    anchors = [{"provider": r[0], "wave": r[1], "fieldwork_end": r[2], "geo": r[3],
                "metric_family": r[4], "value": r[5], "url": r[6]}
               for r in con.execute("""SELECT provider, wave, fieldwork_end, geo,
                   metric_family, value, url FROM anchors ORDER BY fieldwork_end DESC""")]
    n_items = con.execute("SELECT COUNT(*) FROM items WHERE day=?", (day,)).fetchone()[0]
    # history for trend charts
    hist_c = [{"day": r[0], "v": r[1], "lo": r[2], "hi": r[3]} for r in con.execute(
        "SELECT day, value, lo, hi FROM composite_daily WHERE view='societal' ORDER BY day")]
    hist_l = {}
    for l2, d2, v2 in con.execute(
            "SELECT lens, day, value FROM lens_daily WHERE value IS NOT NULL ORDER BY day"):
        hist_l.setdefault(l2, []).append({"day": d2, "v": round((v2 + 2) / 4 * 100, 1)})
    tone_hist = [{"day": r[0], "source": r[1],
                  "tone": round(r[2], 2) if r[2] is not None else None, "n": r[3]}
                 for r in con.execute(
        "SELECT day, source, avg_tone, article_count FROM timeline_daily ORDER BY day")]
    pub_val = next((l["value"] for l in lenses if l["lens"] == "public"), None)
    import combine as c2
    sgap = c2.survey_gap(c2.to_100(pub_val), [dict(a, metric_family=a["metric_family"],
                     fieldwork_end=a["fieldwork_end"]) for a in anchors]) if pub_val is not None else None
    data = {"day": day, "n_items": n_items,
            "composite": {"value": comp[0], "lo": comp[1], "hi": comp[2]} if comp else None,
            "investor": {"value": inv[0]} if inv else None,
            "survey_gap": sgap, "lenses": lenses, "companies": companies,
            "sources": sources, "anchors": anchors,
            "trend": {"composite": hist_c, "lenses": hist_l, "gdelt_tone": tone_hist}}
    built_at = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Trust Tracker — {day}</title><style>{CSS}</style></head><body><div class="wrap">
<h1>AI Trust Tracker <a class="btn" href="https://github.com/ahow/ai-trust-tracker/actions/workflows/daily.yml" target="_blank" rel="noopener">&#10227; Update data now</a></h1>
<div class="sub">Data day {day} · built {built_at} · rubric v0-lexicon (PRIOR) · bias terms b=0 (PRIOR) · all series PROVISIONAL until survey calibration<br>
<span class="btn-note">The button opens GitHub Actions &rarr; "Run workflow" (sign-in required). A static page cannot run the pipeline itself; the run takes ~5 min and the bot commits the refreshed dashboard automatically.</span></div>
<div id="kpis" class="kpis"></div>
<h2>Lenses</h2><div id="lenses" class="lenses"></div>
<h2>Trend</h2><div id="trend"></div>
<div class="note">Media, Business and Technical lenses have no survey anchor — they are
<b>discourse indices</b>, provisional until per-lens anchors exist. Public is the only lens
that can currently claim a survey-anchored level. Non-coverage note: with X excluded, the
Public lens lacks a right-leaning US platform; its band is permanently wider, not corrected.</div>
<h2>Companies</h2>
<table><thead><tr><th>Company</th><th>Score /100</th><th>Δ vs field</th><th>n_eff (7d)</th>
<th>Lenses</th><th>Top topic</th></tr></thead><tbody id="cobody"></tbody></table>
<h2>Source status</h2><div id="srcstatus"></div>
<h2>Survey anchors</h2><div id="anchors"></div>
<div class="note"><b>Method.</b> One rubric across all sources (v0-lexicon, deterministic;
LLM rubric replaces it after κ≥0.7 validation). Direction −2..+2 rescaled to 0–100.
Within-lens: inverse-variance weights, 40% source cap. Composite: stated lens weights
(societal default). Bands widened ×2 while bias terms are uncalibrated priors.
Company scores need n_eff≥50 over 7 days and ≥2 lenses, else LOW CONF — shown, not hidden.
GDELT data comes from raw GKG files since v0.3.0 (DOC API unusable); media/business volume
and tone break comparability at the switchover, and backfilled days cover media+business
lenses only. Full parameter register in docs/PARAMETER_REGISTER.md.</div>
</div><script>window.__DATA__={json.dumps(data)};</script><script>{JS}</script>
</body></html>"""
    out = os.path.join(ROOT, "docs", "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(html)
    print(f"dashboard -> {out} ({len(html):,} bytes)")
    return out

if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
