const $ = id => document.getElementById(id);
const QUARTER_HOUR = 15 * 60 * 1000;
const DAY = 24 * 60 * 60 * 1000;
const state = {email:"",user:null,reservations:[],viewDate:startOfDay(new Date()),selection:null,confirmSelection:null,refreshTimer:null,provisioningTimer:null,provisioningNoticeAt:0,cancelEvent:null};

function startOfDay(value){const date=new Date(value);date.setHours(0,0,0,0);return date}
function addDays(value,days){const date=new Date(value);date.setDate(date.getDate()+days);return startOfDay(date)}
function sameDay(a,b){return startOfDay(a).getTime()===startOfDay(b).getTime()}
function naturalDay(date){const diff=Math.round((startOfDay(date)-startOfDay(new Date()))/DAY);if(diff===0)return"Today";if(diff===1)return"Tomorrow";if(diff===-1)return"Yesterday";return new Intl.DateTimeFormat(undefined,{weekday:"long"}).format(date)}
function fullDate(date){return new Intl.DateTimeFormat(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"}).format(date)}
function shortDate(date){return new Intl.DateTimeFormat(undefined,{month:"long",day:"numeric",year:"numeric"}).format(date)}
function time(date){return new Intl.DateTimeFormat(undefined,{hour:"numeric",minute:"2-digit"}).format(date)}
function compactDay(date){return new Intl.DateTimeFormat(undefined,{weekday:"short",month:"short",day:"numeric"}).format(date)}
function reservationRange(start,end){return sameDay(start,end)?`${time(start)} — ${time(end)}`:`${time(start)} ${compactDay(start)} — ${time(end)} ${compactDay(end)}`}
function durationLabel(minutes){const hours=Math.floor(minutes/60),remainder=minutes%60;return hours&&remainder?`${hours} hr ${remainder} min`:hours?`${hours} hr${hours===1?"":"s"}`:`${remainder} min`}
function initialSelection(date=state.viewDate){const now=new Date(),start=new Date(date);start.setHours(sameDay(date,now)?now.getHours():9,sameDay(date,now)?now.getMinutes()+1:0,0,0);return{start,end:new Date(start.getTime()+60*60*1000)}}
function overlapReservation(start,end){return state.reservations.find(r=>start<new Date(r.end_time)&&end>new Date(r.start_time))}
function activeMine(){return state.reservations.find(reservation=>reservation.mine&&new Date(reservation.end_time)>new Date())}
function isPast(start,end){return end<=new Date()}

function announce(title,message,type="success",timeout=0){
  const notice=$("notice");$("notice-title").textContent=title;$("notice-message").textContent=message;
  notice.className=`notice ${type}`;notice.scrollIntoView({behavior:"smooth",block:"nearest"});
  clearTimeout(announce.timer);if(timeout)announce.timer=setTimeout(()=>notice.classList.add("hidden"),timeout);
}
function loginNotice(message=""){const el=$("login-notice");el.textContent=message;el.classList.toggle("hidden",!message)}
function busy(button,on,label){if(!button.dataset.label)button.dataset.label=button.textContent;button.disabled=on;button.textContent=on?label:button.dataset.label}
async function api(path,options={}){const response=await fetch(path,options);let data={};try{data=await response.json()}catch{}if(!response.ok&&response.status!==202){if(response.status===401)showLogin();throw new Error(data.detail||"Something went wrong. Try again.")}return{response,data}}

function showLogin(){state.user=null;clearInterval(state.refreshTimer);$("workspace").classList.add("hidden");$("user-menu").classList.add("hidden");$("login").classList.remove("hidden")}
function showApp(user){
  state.user=user;state.viewDate=startOfDay(new Date());state.selection=initialSelection(state.viewDate);$("user-name").textContent=user.display_name||user.username;$("user-email").textContent=user.email;
  $("admin-link").classList.toggle("hidden",!user.is_admin);
  $("login").classList.add("hidden");$("user-menu").classList.remove("hidden");$("workspace").classList.remove("hidden");updateSelection();loadReservations();
  clearInterval(state.refreshTimer);state.refreshTimer=setInterval(()=>{if(!document.hidden)loadReservations(true)},30000);
}

function renderDayStrip(){
  const strip=$("day-strip");strip.replaceChildren();const today=startOfDay(new Date());const distance=Math.round((state.viewDate-today)/DAY);const first=addDays(today,Math.floor(distance/7)*7);
  for(let i=0;i<7;i++){
    const date=addDays(first,i);const button=document.createElement("button");button.type="button";button.className="day-chip";
    if(sameDay(date,state.viewDate))button.classList.add("active");if(sameDay(date,today))button.classList.add("today");
    button.setAttribute("aria-label",fullDate(date));button.setAttribute("aria-current",sameDay(date,state.viewDate)?"date":"false");
    const label=document.createElement("span");label.textContent=naturalDay(date);const number=document.createElement("strong");number.textContent=new Intl.DateTimeFormat(undefined,{day:"numeric"}).format(date);
    button.append(label,number);button.addEventListener("click",()=>changeDay(date));strip.append(button);
  }
}

function renderTimeline(){
  const timeline=$("timeline");timeline.replaceChildren();const dayStart=startOfDay(state.viewDate),dayEnd=addDays(dayStart,1),now=new Date();
  const grid=document.createElement("div");grid.className="timeline-grid";for(let index=0;index<96;index++){const cell=document.createElement("span");cell.className=`quarter-cell${(index+1)%4===0?" hour":""}`;grid.append(cell)}timeline.append(grid);
  const trackLabel=document.createElement("span");trackLabel.className="calendar-track-label";trackLabel.textContent="GPU availability";timeline.append(trackLabel);
  const dayBoundaries=document.createElement("div");dayBoundaries.className="day-boundaries";const boundaryStart=document.createElement("span"),boundaryEnd=document.createElement("span");boundaryStart.textContent=compactDay(dayStart);boundaryEnd.textContent=compactDay(dayEnd);dayBoundaries.append(boundaryStart,boundaryEnd);timeline.append(dayBoundaries);
  const labels=document.createElement("div");labels.className="hour-labels";for(let hour=0;hour<=24;hour++){const label=document.createElement("span");label.className=`hour-label${hour%2===0?" major":""}`;label.style.left=`${hour/24*100}%`;label.textContent=hour===24?"12 AM":hour===0?"12 AM":hour<12?`${hour} AM`:hour===12?"12 PM":`${hour-12} PM`;labels.append(label)}timeline.append(labels);
  function appendSpan(rawStart,rawEnd,className,description){if(rawStart>=dayEnd||rawEnd<=dayStart)return null;const start=new Date(Math.max(rawStart,dayStart)),end=new Date(Math.min(rawEnd,dayEnd)),fromPrevious=rawStart<dayStart,intoNext=rawEnd>dayEnd;const block=document.createElement("div");block.className=`${className}${fromPrevious?" continues-from-previous":""}${intoNext?" continues-into-next":""}`;block.style.left=`${(start-dayStart)/(dayEnd-dayStart)*100}%`;block.style.width=`${(end-start)/(dayEnd-dayStart)*100}%`;block.title=description;block.setAttribute("aria-label",description);timeline.append(block);return block}
  state.reservations.forEach(reservation=>{const rawStart=new Date(reservation.start_time),rawEnd=new Date(reservation.end_time),description=reservation.mine?`Your reservation, ${reservationRange(rawStart,rawEnd)}`:`Unavailable, ${reservationRange(rawStart,rawEnd)}`;appendSpan(rawStart,rawEnd,`availability-block${reservation.mine?" mine":""}`,description)});
  if(sameDay(dayStart,now)){const minutes=now.getHours()*60+now.getMinutes();const past=document.createElement("div");past.className="past-block";past.style.width=`${minutes/1440*100}%`;timeline.append(past);const marker=document.createElement("div");marker.className="now-marker";marker.style.left=`${minutes/1440*100}%`;timeline.append(marker)}
  if(state.selection&&!activeMine()&&state.selection.start<dayEnd&&state.selection.end>dayStart){const conflict=selectionError(),description=`Selected: ${reservationRange(state.selection.start,state.selection.end)} · ${durationLabel((state.selection.end-state.selection.start)/60000)}`,block=appendSpan(state.selection.start,state.selection.end,`selection-block${conflict?" conflict":""}`,description);requestAnimationFrame(()=>{block.classList.add("updated");const scroller=timeline.parentElement,target=block.offsetLeft+block.offsetWidth/2-scroller.clientWidth/2;scroller.classList.remove("reveal-scrollbar");scroller.classList.add("is-auto-scrolling");scroller.scrollTo({left:Math.max(0,target),behavior:"smooth"});clearTimeout(scroller.autoTimer);scroller.autoTimer=setTimeout(()=>scroller.classList.remove("is-auto-scrolling"),500)});setTimeout(()=>block.classList.remove("updated"),220)}
}

function renderCalendar(){
  $("day-context").textContent=naturalDay(state.viewDate);$("calendar-date").textContent=fullDate(state.viewDate);$("return-today").classList.toggle("hidden",sameDay(state.viewDate,new Date()));
  renderDayStrip();renderTimeline();renderMyReservations();updateBookingLock();
}
function changeDay(date){const oldStart=state.selection?.start;state.viewDate=startOfDay(date);const start=new Date(state.viewDate);start.setHours(oldStart?.getHours()??9,oldStart?.getMinutes()??0,0,0);const duration=state.selection?state.selection.end-state.selection.start:60*60*1000;state.selection={start,end:new Date(start.getTime()+duration)};updateSelection();document.querySelector(".schedule").scrollIntoView({behavior:"smooth",block:"start"})}
async function loadReservations(quiet=false){try{const{data}=await api("/reservations");state.reservations=data;renderCalendar()}catch(error){if(!quiet)announce("Schedule could not be loaded",error.message,"error")}}

function selectionError(){if(!state.selection)return"";const{start,end}=state.selection;if(start<=new Date())return"This time has already passed.";if(overlapReservation(start,end))return"Part of this session overlaps an unavailable time.";if(end-start>3*60*60*1000)return"Reservations can be up to three hours.";return""}
function updateSelection(){
  const{start,end}=state.selection,minutes=Math.round((end-start)/60000),invalidReason=selectionError();setStartTimeControls(start);$("duration-value").textContent=durationLabel(minutes);$("composer-date").textContent=sameDay(start,end)?`${naturalDay(start)} · ${shortDate(start)}`:`Crosses midnight · ${compactDay(start)} → ${compactDay(end)}`;$("composer-range").textContent=reservationRange(start,end);$("composer-status").textContent=invalidReason||"Available to reserve";$("composer-summary").classList.toggle("conflict",Boolean(invalidReason));$("selection-error").classList.toggle("hidden",!invalidReason);$("selection-error").textContent=invalidReason;$("confirm-booking").disabled=Boolean(invalidReason);$("duration-down").disabled=minutes<=15;$("duration-up").disabled=minutes>=180;renderCalendar();
}
function openCancel(reservation){state.cancelEvent=reservation;$("cancel-dialog").showModal()}
function renderMyReservations(){const list=$("my-reservations"),dayStart=startOfDay(state.viewDate),dayEnd=addDays(dayStart,1);list.replaceChildren();const mine=state.reservations.filter(r=>r.mine&&new Date(r.start_time)<dayEnd&&new Date(r.end_time)>dayStart);list.classList.toggle("hidden",!mine.length);if(!mine.length)return;const label=document.createElement("span");label.textContent="Your reservations";list.append(label);mine.forEach(reservation=>{const button=document.createElement("button"),start=new Date(reservation.start_time),end=new Date(reservation.end_time);button.type="button";button.className="reservation-pill";button.textContent=`${reservationRange(start,end)} · Manage`;button.addEventListener("click",()=>openCancel(reservation));list.append(button)})}
function updateBookingLock(){const reservation=activeMine(),locked=Boolean(reservation);$("reservation-limit").classList.toggle("hidden",!locked);document.querySelector(".booking-composer").classList.toggle("locked",locked);["start-time-text","period-am","period-pm"].forEach(id=>$(id).disabled=locked);$("duration-down").disabled=locked||((state.selection.end-state.selection.start)/60000<=15);$("duration-up").disabled=locked||((state.selection.end-state.selection.start)/60000>=180);$("confirm-booking").disabled=locked||Boolean(selectionError());if(locked){const start=new Date(reservation.start_time),end=new Date(reservation.end_time);$("composer-summary").classList.remove("conflict");$("composer-date").textContent=sameDay(start,end)?`Reserved · ${shortDate(start)}`:`Reserved across midnight · ${compactDay(start)} → ${compactDay(end)}`;$("composer-range").textContent=reservationRange(start,end);$("composer-status").textContent="Your reservation is confirmed";$("selection-error").classList.add("hidden")}}

function setStartTimeControls(date){const hour=date.getHours();$("start-time-text").value=`${String(hour%12||12).padStart(2,"0")}:${String(date.getMinutes()).padStart(2,"0")}`;document.querySelectorAll(".period-toggle button").forEach(button=>button.classList.toggle("active",button.dataset.period===(hour>=12?"PM":"AM")));$("start-time-text").closest(".time-entry").classList.remove("invalid")}
function applyTypedTime(){const match=$("start-time-text").value.trim().match(/^(\d{1,2}):([0-5]\d)$/);if(!match||Number(match[1])<1||Number(match[1])>12){$("start-time-text").closest(".time-entry").classList.add("invalid");return false}let hour=Number(match[1])%12;if($("period-pm").classList.contains("active"))hour+=12;const start=new Date(state.viewDate),duration=state.selection.end-state.selection.start;start.setHours(hour,Number(match[2]),0,0);state.selection={start,end:new Date(start.getTime()+duration)};updateSelection();return true}
$("start-time-text").addEventListener("input",event=>{event.target.value=event.target.value.replace(/[^0-9:]/g,"").slice(0,5);if(/^\d{1,2}:[0-5]\d$/.test(event.target.value))applyTypedTime()});$("start-time-text").addEventListener("blur",()=>{if(!applyTypedTime())setStartTimeControls(state.selection.start)});$("start-time-text").addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();applyTypedTime();event.target.blur()}if(event.key==="ArrowUp"||event.key==="ArrowDown"){event.preventDefault();const duration=state.selection.end-state.selection.start;state.selection.start=new Date(state.selection.start.getTime()+(event.key==="ArrowUp"?60000:-60000));state.selection.end=new Date(state.selection.start.getTime()+duration);state.viewDate=startOfDay(state.selection.start);updateSelection()}});document.querySelectorAll(".period-toggle button").forEach(button=>button.addEventListener("click",()=>{document.querySelectorAll(".period-toggle button").forEach(item=>item.classList.toggle("active",item===button));applyTypedTime();$("start-time-text").focus()}));
function changeDuration(delta){const current=(state.selection.end-state.selection.start)/60000,next=Math.max(15,Math.min(180,current+delta));state.selection.end=new Date(state.selection.start.getTime()+next*60000);updateSelection()}
$("duration-down").addEventListener("click",()=>changeDuration(-15));$("duration-up").addEventListener("click",()=>changeDuration(15));
$("previous-day").addEventListener("click",()=>changeDay(addDays(state.viewDate,-7)));$("next-day").addEventListener("click",()=>changeDay(addDays(state.viewDate,7)));$("return-today").addEventListener("click",()=>changeDay(new Date()));
const timelineScroller=$("timeline-scroller");function revealTimelineScrollbar(){if(timelineScroller.classList.contains("is-auto-scrolling"))return;timelineScroller.classList.add("reveal-scrollbar");clearTimeout(timelineScroller.revealTimer);timelineScroller.revealTimer=setTimeout(()=>timelineScroller.classList.remove("reveal-scrollbar"),1100)}timelineScroller.addEventListener("wheel",revealTimelineScrollbar,{passive:true});timelineScroller.addEventListener("pointerenter",revealTimelineScrollbar);timelineScroller.addEventListener("pointerdown",revealTimelineScrollbar);timelineScroller.addEventListener("keydown",revealTimelineScrollbar);
$("dismiss-notice").addEventListener("click",()=>$("notice").classList.add("hidden"));

$("confirm-booking").addEventListener("click",()=>{
  const invalidReason=selectionError();if(invalidReason){announce("Check your reservation",invalidReason,"error");return}
  const{start,end}=state.selection;state.confirmSelection={start:new Date(start),end:new Date(end)};
  $("confirm-date").textContent=sameDay(start,end)?fullDate(start):`${fullDate(start)} → ${fullDate(end)}`;$("confirm-time").textContent=`${reservationRange(start,end)} · ${durationLabel((end-start)/60000)}`;
  $("confirm-dialog").showModal();
});
$("edit-booking").addEventListener("click",()=>$("confirm-dialog").close());
$("submit-booking").addEventListener("click",async()=>{
  const button=$("submit-booking"),selection=state.confirmSelection;if(!selection)return;busy(button,true,"Reserving…");
  try{
    await api("/reservations",{method:"POST",headers:{"Content-Type":"application/json","Idempotency-Key":crypto.randomUUID()},body:JSON.stringify({start_time:selection.start.toISOString(),end_time:selection.end.toISOString()})});
    $("confirm-dialog").close();
    state.provisioningNoticeAt=Date.now();announce("Reservation confirmed",`${reservationRange(selection.start,selection.end)}. Preparing SSH access.`,"loading");await loadReservations(true);pollProvisioning();
  }catch(error){$("confirm-dialog").close();announce("Reservation not completed",error.message,"error");await loadReservations(true)}finally{busy(button,false)}
});
async function pollProvisioning(){clearTimeout(state.provisioningTimer);try{const{data}=await api("/me");if(data.provisioning_state==="ready"){const remaining=Math.max(0,900-(Date.now()-state.provisioningNoticeAt));state.provisioningTimer=setTimeout(()=>announce("SSH access sent","Check your email.","success"),remaining);return}if(data.provisioning_state==="failed"){announce("Setup failed","Contact an administrator.","error");return}state.provisioningTimer=setTimeout(pollProvisioning,3000)}catch(error){announce("Setup status unavailable",error.message,"error")}}

$("email-form").addEventListener("submit",async event=>{event.preventDefault();const submittedAt=Date.now();state.email=$("email").value.trim();loginNotice();busy($("email-submit"),true,"Sending…");try{const{data}=await api("/auth/request-code",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:state.email})});if(!data.approved){const remaining=Math.max(0,2000-(Date.now()-submittedAt));if(remaining)await new Promise(resolve=>setTimeout(resolve,remaining));$("contact-admin").textContent=data.admin_contact||"";$("contact-admin-row").classList.toggle("hidden",!data.admin_contact);$("email-form").classList.add("hidden");$("access-request").classList.remove("hidden");return}$("email-form").classList.add("hidden");$("code-form").classList.remove("hidden");$("code").focus()}catch(error){loginNotice(error.message)}finally{busy($("email-submit"),false)}});
$("code-form").addEventListener("submit",async event=>{event.preventDefault();loginNotice();busy($("code-submit"),true,"Verifying…");try{await api("/auth/verify-code",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({email:state.email,code:$("code").value.trim()})});const{data}=await api("/me");showApp(data)}catch(error){loginNotice(error.message);$("code").select()}finally{busy($("code-submit"),false)}});
$("change-email").addEventListener("click",()=>{$("code-form").classList.add("hidden");$("email-form").classList.remove("hidden");$("code").value="";loginNotice();$("email").focus()});
$("retry-access").addEventListener("click",()=>{$("access-request").classList.add("hidden");$("email-form").classList.remove("hidden");$("email").focus()});
$("copy-admin-email").addEventListener("click",async()=>{const button=$("copy-admin-email"),email=$("contact-admin").textContent;if(!email)return;try{await navigator.clipboard.writeText(email);button.classList.add("copied");button.setAttribute("aria-label","Email copied");setTimeout(()=>{button.classList.remove("copied");button.setAttribute("aria-label","Copy administrator email")},1500)}catch{loginNotice("Could not copy the address. Select it and copy manually.")}});
$("logout").addEventListener("click",async()=>{busy($("logout"),true,"Signing out…");try{await fetch("/auth/logout",{method:"POST"})}finally{location.reload()}});
$("keep-reservation").addEventListener("click",()=>$("cancel-dialog").close());$("confirm-cancel").addEventListener("click",async()=>{const button=$("confirm-cancel");busy(button,true,"Cancelling…");try{await api(`/reservations/${state.cancelEvent.id}`,{method:"DELETE"});$("cancel-dialog").close();announce("Reservation cancelled","The time is available again.","success");await loadReservations(true)}catch(error){announce("Cancellation failed",error.message,"error")}finally{busy(button,false)}});
document.addEventListener("visibilitychange",()=>{if(!document.hidden&&state.user)loadReservations(true)});
(async()=>{try{const{data}=await api("/me");showApp(data)}catch{showLogin();$("email").focus()}})();
