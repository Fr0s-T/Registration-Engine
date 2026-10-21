import {api, nav, esc, message} from './admin.js';

document.querySelector('#nav').innerHTML = nav('timetable');
let data, courses, editingOffering = null, editingSection = null;
const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
const tracks = [{id:'EN', label:'English'}, {id:'FR', label:'French'}];
const palette = [
  ['#dcecff','#2f79c6'], ['#e4f4e7','#397b47'], ['#fff0d9','#b56b16'],
  ['#eee8fb','#7252b2'], ['#fbe5e8','#b34f5d'], ['#dff4f2','#2f8179'],
];
const tm = minute => `${String(Math.floor(minute/60)).padStart(2,'0')}:${String(minute%60).padStart(2,'0')}`;
const timeValue = minute => tm(minute);

async function load() {
  [data, courses] = await Promise.all([api('/api/admin/timetable'), api('/api/admin/courses')]);
  year.value = data.active_term.academic_year_start;
  semester.value = data.active_term.semester;
  form.course_id.innerHTML = courses.map(c=>`<option value="${c.id}">${c.curriculum_version} · ${esc(c.code)} · ${esc(c.title)}</option>`).join('');
  render();
}

function filteredRows() {
  const selectedYear = document.querySelector('#year-filter').value;
  const curriculum = document.querySelector('#curriculum').value;
  return data.offerings.filter(o=>(!selectedYear||o.year==selectedYear)&&(!curriculum||o.curriculum_version===curriculum));
}

function layoutDayEvents(events) {
  const sorted = [...events].sort((a,b)=>a.meeting.start_minute-b.meeting.start_minute||a.meeting.end_minute-b.meeting.end_minute);
  const laneEnds = [];
  for (const event of sorted) {
    let lane = laneEnds.findIndex(end=>end<=event.meeting.start_minute);
    if (lane<0) { lane=laneEnds.length; laneEnds.push(event.meeting.end_minute); }
    else laneEnds[lane]=event.meeting.end_minute;
    event.lane=lane;
  }
  const laneCount=Math.max(1,laneEnds.length);
  return sorted.map(event=>({...event,laneCount}));
}

function calendarFor(programYear, track, rows) {
  const yearRows = rows.filter(o=>o.year===programYear&&(o.language_track===track.id||o.language_track===null));
  const seenMeetings=new Set();
  const rawMeetings = yearRows.flatMap((offering,colorIndex)=>offering.sections.flatMap(section=>section.meetings
    .filter(meeting=>meeting.weekday<6).map(meeting=>({offering,section,meeting,colorIndex}))))
    .filter(item=>{const key=[item.offering.id,item.section.component,item.meeting.weekday,item.meeting.start_minute,item.meeting.end_minute].join(':');if(seenMeetings.has(key))return false;seenMeetings.add(key);return true});
  const meetings = days.flatMap((_,dayIndex)=>layoutDayEvents(rawMeetings.filter(item=>item.meeting.weekday===dayIndex)));
  const start = meetings.length ? Math.floor(Math.min(...meetings.map(x=>x.meeting.start_minute),480)/30)*30 : 480;
  const end = meetings.length ? Math.ceil(Math.max(...meetings.map(x=>x.meeting.end_minute),1080)/30)*30 : 1080;
  const pixelsPerMinute=.62, height=(end-start)*pixelsPerMinute;
  const labels=[]; for(let minute=start;minute<=end;minute+=60)labels.push(`<span class="calendar-time-label" style="top:${(minute-start)*pixelsPerMinute}px">${tm(minute)}</span>`);
  const columns=days.map((day,dayIndex)=>{
    const events=meetings.filter(x=>x.meeting.weekday===dayIndex).map(item=>{
      const [background,border]=palette[item.colorIndex%palette.length];
      const top=(item.meeting.start_minute-start)*pixelsPerMinute;
      const eventHeight=Math.max(42,(item.meeting.end_minute-item.meeting.start_minute)*pixelsPerMinute);
      const width=100/item.laneCount, left=item.lane*width;
      const shared=item.offering.language_track===null;
      const title=`${item.offering.code} — ${item.offering.title}\n${item.section.component} · ${item.section.code}\n${tm(item.meeting.start_minute)}–${tm(item.meeting.end_minute)}\n${item.section.instructor||'Instructor not recorded'}${item.section.room?` · ${item.section.room}`:''}\n${shared?'Shared / track not assigned':track.label}`;
      return `<div class="calendar-event" tabindex="0" title="${esc(title)}" style="top:${top}px;height:${eventHeight}px;left:calc(${left}% + 4px);width:calc(${width}% - 8px);--event-bg:${background};--event-border:${border}"><div class="event-heading"><strong>${esc(item.offering.code)}</strong><button type="button" data-edit-offering="${item.offering.id}" data-edit-section="${item.section.id}" title="Edit this section">Edit</button></div><span>${esc(item.section.component.split(':')[0])} · ${esc(item.section.code)}</span><small>${tm(item.meeting.start_minute)}–${tm(item.meeting.end_minute)}${shared?' · Shared':''}</small></div>`;
    }).join('');
    return `<div class="calendar-day-column" aria-label="${day}">${events}</div>`;
  }).join('');
  const unscheduled=yearRows.flatMap(offering=>offering.sections.filter(section=>!section.meetings.length).map(section=>({offering,section})));
  return `<section class="year-calendar card"><div class="year-calendar-header"><div class="year-number">${programYear}</div><div><span class="eyebrow">PROGRAM YEAR ${programYear}</span><h3>${track.label} track</h3><p>${yearRows.length} offering${yearRows.length===1?'':'s'} · ${meetings.length} scheduled meeting${meetings.length===1?'':'s'}</p></div><span class="track-badge track-${track.id.toLowerCase()}">${track.id}</span><div class="year-course-chips">${yearRows.map(o=>`<span class="${o.language_track===null?'shared-chip':''}">${esc(o.code)}${o.language_track===null?' · Shared':''}</span>`).join('')||'<span class="muted-chip">No active offerings</span>'}</div></div><div class="calendar-scroll"><div class="calendar-grid" style="--calendar-height:${height}px;--half-hour:${30*pixelsPerMinute}px"><div class="calendar-corner">Time</div>${days.map(d=>`<div class="calendar-day-heading">${d.slice(0,3)}</div>`).join('')}<div class="calendar-time-axis">${labels.join('')}</div>${columns}</div></div>${unscheduled.length?`<div class="unscheduled-row"><strong>Unscheduled</strong>${unscheduled.map(x=>`<button data-edit-offering="${x.offering.id}" data-edit-section="${x.section.id}">${esc(x.offering.code)} · ${esc(x.section.code)} · Edit</button>`).join('')}</div>`:''}</section>`;
}

function render() {
  const rows=filteredRows(), selectedYear=document.querySelector('#year-filter').value;
  const years=selectedYear?[+selectedYear]:[1,2,3,4,5];
  document.querySelector('#empty-timetable').classList.toggle('hidden', data.offerings.length!==0);
  document.querySelector('#year-calendars').innerHTML=years.flatMap(programYear=>tracks.map(track=>calendarFor(programYear,track,rows))).join('');
  const meetingCount=rows.reduce((n,o)=>n+o.sections.reduce((sum,s)=>sum+s.meetings.length,0),0);
  const syntheticCount=rows.filter(o=>o.synthetic_placeholder).length;
  document.querySelector('#calendar-summary').innerHTML=`<div><strong>${rows.length}</strong><span>offerings</span></div><div><strong>${meetingCount}</strong><span>meetings</span></div><div><strong>${syntheticCount}</strong><span>SYNTHETIC_PLACEHOLDER</span></div><div><strong>${years.length*2}</strong><span>track calendars</span></div>`;
}

function openAdd() {
  editingOffering=null; editingSection=null; form.reset(); form.language_track.value='EN';
  document.querySelector('#delete-offering').classList.add('hidden');
  document.querySelector('#offering-form-title').textContent='Add offering'; modal.classList.remove('hidden');
}

function openEdit(offeringId,sectionId) {
  const offering=data.offerings.find(item=>item.id===offeringId);
  const section=offering?.sections.find(item=>item.id===sectionId);
  if(!offering||!section)return message('Offering section no longer exists.',true);
  editingOffering=offering; editingSection=section;
  document.querySelector('#delete-offering').classList.remove('hidden');
  form.course_id.value=offering.course_id; form.language_track.value=offering.language_track||'';
  form.section_code.value=section.code; form.component.value=section.component;
  form.bundle_key.value=section.bundle_key; form.campus.value=section.campus||''; form.room.value=section.room||'';
  form.instructor.value=section.instructor||''; form.notes.value=section.notes||'';
  const meeting=section.meetings[0]; form.weekday.value=meeting?.weekday??0;
  form.start.value=meeting?timeValue(meeting.start_minute):''; form.end.value=meeting?timeValue(meeting.end_minute):'';
  document.querySelector('#offering-form-title').textContent=`Edit ${offering.code} · ${section.code}`;
  modal.classList.remove('hidden');
}

document.querySelector('#year-filter').onchange=render;
document.querySelector('#curriculum').onchange=render;
document.querySelector('#term').onclick=async()=>{
  try{const result=await api('/api/admin/active-term',{method:'PUT',body:JSON.stringify({academic_year_start:+year.value,semester:semester.value})});await load();message(`Active term switched. ${result.offerings_available} saved offering${result.offerings_available===1?' is':'s are'} available for this semester.`)}catch(error){message(error.message,true)}
};

const modal=document.querySelector('#modal'),form=document.querySelector('#form');
document.querySelector('#add').onclick=openAdd;
document.querySelector('#empty-add').onclick=openAdd;
document.querySelector('#generate-placeholders').onclick=async()=>{if(!confirm('Regenerate only Year 1–2 synthetic placeholders? Imported and manually maintained offerings will be preserved.'))return;try{const result=await api('/api/admin/timetable/generate-year-1-2',{method:'POST'});await load();message(`${result.message}: ${result.generated_offerings} offerings.`)}catch(error){message(error.message,true)}};
document.querySelector('#cancel').onclick=()=>modal.classList.add('hidden');
document.querySelector('#delete-offering').onclick=async()=>{
  if(!editingOffering||!confirm(`Remove ${editingOffering.code} and all of its sections from the active timetable?`))return;
  try{await api(`/api/admin/offerings/${editingOffering.id}`,{method:'DELETE'});modal.classList.add('hidden');await load();message('Offering removed from the active timetable.')}catch(error){message(error.message,true)}
};
const mins=time=>{const[hours,minutes]=time.split(':').map(Number);return hours*60+minutes};
form.onsubmit=async event=>{
  event.preventDefault();const values=Object.fromEntries(new FormData(form));
  const changedSection={code:values.section_code,component:values.component,bundle_key:values.bundle_key,campus:values.campus||null,room:values.room||null,instructor:values.instructor||null,notes:values.notes||null,meetings:[{weekday:+values.weekday,start_minute:mins(values.start),end_minute:mins(values.end)}]};
  const body={course_id:+values.course_id,language_track:values.language_track||null,verification_status:editingOffering?.verification_status||'UNVERIFIED',sections:editingOffering?editingOffering.sections.map(section=>section.id===editingSection.id?changedSection:{code:section.code,component:section.component,bundle_key:section.bundle_key,campus:section.campus,room:section.room,instructor:section.instructor,notes:section.notes,meetings:section.meetings.map(({weekday,start_minute,end_minute})=>({weekday,start_minute,end_minute}))}):[changedSection]};
  try{await api(editingOffering?`/api/admin/offerings/${editingOffering.id}`:'/api/admin/offerings',{method:editingOffering?'PUT':'POST',body:JSON.stringify(body)});modal.classList.add('hidden');await load();message(editingOffering?'Offering updated.':'Offering saved.')}catch(error){message(error.message,true)}
};

document.body.onclick=event=>{
  const button=event.target.closest('[data-edit-offering]');
  if(button)openEdit(+button.dataset.editOffering,+button.dataset.editSection);
};
load().catch(error=>message(error.message,true));
