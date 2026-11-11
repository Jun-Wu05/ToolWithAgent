"""Keep the static time band aligned with the sanitized session Run fixture."""
from pathlib import Path
import re

path = Path(__file__).resolve().parent / "index.html"
source = path.read_text(encoding="utf-8")
if '<script src="run-fixture.js"></script>' not in source:
    source = source.replace('<script src="fixture.js"></script>', '<script src="run-fixture.js"></script><script src="fixture.js"></script>')
source = source.replace('11 次执行', '6 次执行')
band = r"""const runs=window.fixtureRuns;const start=Date.parse(runs[0].queued_at);const end=Math.max(...runs.map(r=>Date.parse(r.finished_at||r.started_at||r.queued_at)));const span=end-start;const localTime=s=>new Date(s).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});const band='<div class="band"><div class="times"><span>'+localTime(start)+'</span><span>'+localTime(end)+'</span></div><div class="track">'+runs.map(r=>{const left=(Date.parse(r.queued_at)-start)/span*100;const width=Math.max(.7,(Date.parse(r.finished_at||r.started_at||r.queued_at)-Date.parse(r.queued_at))/span*100);return '<i style="left:'+left+'%;width:'+width+'%;background:'+(r.status==='failed'?'var(--danger)':'var(--action)')+'"></i>'}).join('')+'</div></div>';const eventRow="""
source, count = re.subn(r"const band=.*?;const eventRow=", lambda _: band, source, count=1, flags=re.S)
if count != 1:
    raise RuntimeError("Static time band marker not found")
path.write_text(source, encoding="utf-8")
