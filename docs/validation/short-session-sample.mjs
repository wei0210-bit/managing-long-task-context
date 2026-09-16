// Read-only, bounded structural sampling. No evidence resolvers or business actions.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const sources = [
  {name: '8D', root: '/Users/zhaowei/Desktop/David/project.nosync/.prime/context', prefix: '8D'},
  {name: 'MLTC', root: '/Users/zhaowei/Desktop/David/project.nosync/managing-long-task-context/.prime/context', prefix: ''},
  {name: 'SEO-GEO', root: '/Users/zhaowei/Desktop/David/project.nosync/n8n/SEO GEO/.prime/context', prefix: ''},
];
const MAX_FILE = 16 * 1024 * 1024, MAX_TOTAL = 64 * 1024 * 1024;
const knownTypes = new Set(['contract-published','item-recorded','item-updated','item-externalized','checkpoint-recorded','truth-source-dirtied','truth-source-observed']);
const digest = b => crypto.createHash('sha256').update(b).digest('hex');
let bytesRead = 0;
function readFile(p) {
  const before = fs.lstatSync(p);
  if (!before.isFile() || before.isSymbolicLink()) throw Error('NOT_REGULAR_FILE');
  if (before.size > MAX_FILE || bytesRead + before.size > MAX_TOTAL) throw Error('SAMPLE_LIMIT');
  const fd = fs.openSync(p, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
  try {
    const opened = fs.fstatSync(fd);
    if (opened.ino !== before.ino || opened.dev !== before.dev) throw Error('SOURCE_CHANGED');
    const raw = Buffer.alloc(before.size + 1);
    let n = 0;
    while (n < raw.length) {const k = fs.readSync(fd, raw, n, raw.length-n, null); if (!k) break; n += k;}
    bytesRead += n;
    const after = fs.fstatSync(fd), named = fs.lstatSync(p);
    if (n !== before.size || after.size !== before.size || after.mtimeMs !== before.mtimeMs || named.ino !== before.ino || named.dev !== before.dev) throw Error('SOURCE_CHANGED');
    const data = raw.subarray(0,n);
    return {text: new TextDecoder('utf-8',{fatal:true}).decode(data), bytes: n, sha256: digest(data)};
  } finally {fs.closeSync(fd);}
}
const report = {schema:'structural-sample/v1', sampled_at:new Date().toISOString(), scope:sources, limits:{max_file_bytes:MAX_FILE,max_total_bytes:MAX_TOTAL}, tasks:[], source_manifest:[], errors:[], business_content_included:false};
for (const source of sources) {
  let dirs;
  try {dirs=fs.readdirSync(source.root,{withFileTypes:true}).filter(d=>d.isDirectory()&&d.name.startsWith(source.prefix)).sort((a,b)=>a.name.localeCompare(b.name));}
  catch {report.errors.push({project:source.name,code:'ROOT_UNREADABLE'});continue;}
  if(dirs.length>500){report.errors.push({project:source.name,code:'DIRECTORY_LIMIT'});continue;}
  for (const dir of dirs) {
    const row={project:source.name,task:dir.name,files:{},events:null,event_types:{},max_event_bytes:null,snapshot_items:null,criteria:null,mutable_records:null,errors:[]};
    for (const name of ['task-contract.json','events.jsonl','snapshot.json']) {
      const p=path.join(source.root,dir.name,name);
      try {
        const value=readFile(p);
        row.files[name]={bytes:value.bytes,sha256:value.sha256};
        report.source_manifest.push({path:p,bytes:value.bytes,sha256:value.sha256});
        if(name==='events.jsonl'){
          const lines=value.text.split('\n').filter(x=>x.trim());
          row.events=lines.length;row.max_event_bytes=0;
          for(const line of lines){
            row.max_event_bytes=Math.max(row.max_event_bytes,Buffer.byteLength(line));
            const e=JSON.parse(line), type=knownTypes.has(e.event_type)?e.event_type:'other';
            row.event_types[type]=(row.event_types[type]??0)+1;
          }
        } else {
          const o=JSON.parse(value.text);
          if(name==='snapshot.json'){
            row.snapshot_items=o.items&&typeof o.items==='object'?Object.keys(o.items).length:null;
            row.mutable_records=o.items&&typeof o.items==='object'?Object.values(o.items).filter(i=>i?.mutable===true).length:null;
          } else row.criteria=Array.isArray(o.acceptance_criteria)?o.acceptance_criteria.length:null;
        }
      } catch(e) {row.errors.push({file:name,code:['NOT_REGULAR_FILE','SAMPLE_LIMIT','SOURCE_CHANGED'].includes(e.message)?e.message:e.code==='ENOENT'?'MISSING':'UNREADABLE_OR_INVALID'});}
    }
    report.tasks.push(row);
  }
}
// Repeat fingerprints without printing contents. This is a read observation, not a cross-file transaction.
for(const entry of report.source_manifest){
  try{const now=readFile(entry.path);if(now.sha256!==entry.sha256)report.errors.push({path:entry.path,code:'SOURCE_CHANGED_AFTER_SAMPLE'});}
  catch{report.errors.push({path:entry.path,code:'RECHECK_FAILED'});}
}
report.bytes_read_including_recheck=bytesRead;
report.whole_project_consistency='not_proven';
if(process.argv.includes('--summary')){
  const max=(rows,fn)=>Math.max(0,...rows.map(fn));
  const projects=sources.map(s=>{
    const rows=report.tasks.filter(t=>t.project===s.name);
    return {project:s.name,candidate_directories:rows.length,managed_tasks:rows.filter(t=>Object.keys(t.files).length>0).length,event_logs:rows.filter(t=>t.events!==null).length,
      max_events:max(rows,t=>t.events??0),max_log_bytes:max(rows,t=>t.files['events.jsonl']?.bytes??0),
      max_event_bytes:max(rows,t=>t.max_event_bytes??0),max_snapshot_items:max(rows,t=>t.snapshot_items??0),
      max_snapshot_bytes:max(rows,t=>t.files['snapshot.json']?.bytes??0),max_contract_bytes:max(rows,t=>t.files['task-contract.json']?.bytes??0),
      max_criteria:max(rows,t=>t.criteria??0),error_count:rows.reduce((n,t)=>n+t.errors.length,0)};
  });
  const top=sources.map(s=>report.tasks.filter(t=>t.project===s.name&&t.events!==null).sort((a,b)=>b.events-a.events)[0]).filter(Boolean);
  console.log(JSON.stringify({...report,projects,tasks:top,source_manifest:undefined,
    source_manifest_sha256:digest(Buffer.from(JSON.stringify(report.source_manifest))),
    sampled_files:report.source_manifest.length,
    task_errors:report.tasks.filter(t=>t.errors.length).map(t=>({project:t.project,task:t.task,errors:t.errors}))},null,2));
}else console.log(JSON.stringify(report,null,2));
