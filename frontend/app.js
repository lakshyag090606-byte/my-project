const API = "http://localhost:5000/api";
const $ = s => document.querySelector(s);
let onlyPending = false, templates = [], drafts = {};
let selSigns = new Set(), affect = "calm", currentResp = null, lastPlayed = null;

async function api(path, method = "GET", body) {
  let r, data;
  try {
    r = await fetch(API + path, { method, headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    data = await r.json();
  } catch {
    $("#error").hidden = false; $("#error").textContent = "Cannot reach the backend on port 5000. Is it running?";
    $("#status").textContent = "server offline"; throw new Error("offline");
  }
  if (!r.ok) { $("#error").hidden = false; $("#error").textContent = data.error || "Request failed"; throw new Error(data.error); }
  $("#error").hidden = true; $("#status").textContent = "server connected";
  return data;
}

function tab(name) {
  $("#patient").hidden = name !== "patient"; $("#doctor").hidden = name !== "doctor";
  $("#tab-patient").classList.toggle("on", name === "patient"); $("#tab-doctor").classList.toggle("on", name === "doctor");
  if (name === "doctor") loadInbox();
}
$("#tab-patient").onclick = () => tab("patient"); $("#tab-doctor").onclick = () => tab("doctor");

// ---- patient ----
$("#camBtn").onclick = async () => {
  try { $("#cam").srcObject = await navigator.mediaDevices.getUserMedia({ video: true }); $("#camBtn").hidden = true; }
  catch { $("#error").hidden = false; $("#error").textContent = "Camera unavailable or permission denied. You can still use the sign picker."; }
};
async function init() {
  const v = await api("/vocabulary");
  templates = await api("/templates");
  v.signs.forEach(s => {
    const b = document.createElement("button"); b.className = "chip"; b.textContent = `${s.emoji} ${s.gloss}`;
    b.onclick = () => { selSigns.has(s.gloss) ? selSigns.delete(s.gloss) : selSigns.add(s.gloss); b.classList.toggle("on"); };
    $("#signs").append(b);
  });
  v.affects.forEach(a => {
    const b = document.createElement("button"); b.className = "chip" + (a === affect ? " on" : ""); b.textContent = a.replace("_", " ");
    b.onclick = () => { affect = a; [...$("#affects").children].forEach(c => c.classList.toggle("on", c === b)); };
    $("#affects").append(b);
  });
}
$("#sendBtn").onclick = async () => {
  try {
    const r = await api("/patient/interpret", "POST", { signs: [...selSigns], affect });
    $("#sentInfo").textContent = `Sent (message #${r.id}). Waiting for staff…`;
    selSigns.clear(); document.querySelectorAll("#signs .on").forEach(c => c.classList.remove("on"));
  } catch {}
};
async function pollReply() {
  try {
    const r = await api("/patient/response/latest");
    if (r && r.id !== lastPlayed) { lastPlayed = r.id; currentResp = r; play(r.glosses); }
  } catch {}
}
function play(glosses) {
  $("#confirm").hidden = true;
  $("#glossStrip").innerHTML = glosses.map(g => `<span class="gloss">${g}</span>`).join("");
  const els = [...document.querySelectorAll(".gloss")]; let i = 0;
  const t = setInterval(() => {
    els.forEach(e => e.classList.remove("now"));
    if (i >= els.length) { clearInterval(t); els.forEach(e => e.style.opacity = 1); $("#confirm").hidden = false; return; }
    els[i++].classList.add("now");
  }, 900);
}
document.querySelectorAll("#confirm button").forEach(b => b.onclick = async () => {
  try {
    await api(`/patient/confirm/${currentResp.id}`, "POST", { status: b.dataset.s });
    if (b.dataset.s === "repeat") { lastPlayed = null; play(currentResp.glosses); }
    else { $("#confirm").hidden = true; $("#glossStrip").textContent = "Reply confirmed: " + b.textContent; }
  } catch {}
});

// ---- doctor ----
async function loadInbox() {
  if ($("#doctor").hidden) return;
  loadStats();
  if (document.activeElement?.type === "text") return; // don't rebuild while typing
  let msgs; try { msgs = await api("/doctor/inbox" + (onlyPending ? "?pending=1" : "")); } catch { return; }
  $("#inbox").innerHTML = msgs.length ? "" : "No messages yet.";
  msgs.forEach(m => {
    const d = document.createElement("div"); d.className = `msg ${m.urgency}`;
    d.innerHTML = `<span class="badge ${m.urgency}">${m.urgency}</span> <b>#${m.id}</b> · ${m.created_at.slice(11)}
      <p>${m.summary}</p><p class="note">Signs: ${m.signs.join(", ")}</p>
      ${m.flags.map(f => `<div class="flag">⚠ ${f}</div>`).join("")}
      <p class="note">Review: ${m.review_status}${m.override_text ? " – " + m.override_text : ""}</p>
      ${m.response ? `<p class="note">Your reply: "${m.response.text}" → ${m.response.glosses.join(" ")} (patient: ${m.response.patient_status})${m.response.unmapped.length ? " · not signed: " + m.response.unmapped.join(", ") : ""}</p>` : ""}
      <div class="row"><button data-a="confirm">Confirm</button><button data-a="query">Ask patient to re-sign</button><button data-a="override">Override</button></div>
      <div class="row"><input type="text" placeholder="Type a reply or pick a quick reply below"><button class="primary">Send as sign</button></div>
      <div class="row">${templates.map((t, i) => `<button class="chip" data-t="${i}">${t}</button>`).join("")}</div>`;
    const inp = d.querySelector("input"); inp.value = drafts[m.id] || "";
    inp.oninput = () => drafts[m.id] = inp.value;
    d.querySelectorAll("[data-t]").forEach(b => b.onclick = () => { inp.value = drafts[m.id] = templates[b.dataset.t]; });
    d.querySelectorAll("[data-a]").forEach(b => b.onclick = async () => {
      let text; if (b.dataset.a === "override") { text = prompt("Correct interpretation:"); if (!text) return; }
      try { await api(`/doctor/review/${m.id}`, "POST", { action: b.dataset.a, override_text: text }); } catch {} loadInbox();
    });
    d.querySelector(".primary").onclick = async () => {
      try { await api("/doctor/respond", "POST", { message_id: m.id, text: inp.value }); delete drafts[m.id]; document.activeElement.blur(); loadInbox(); } catch {}
    };
    $("#inbox").append(d);
  });
}
init().catch(() => {});
setInterval(pollReply, 3000); setInterval(loadInbox, 4000);

async function loadStats() {
  try {
    const s = await api("/stats");
    $("#stats").innerHTML = `<div><b>${s.total}</b> messages</div><div><b>${s.awaiting_reply}</b> awaiting reply</div>
      <div class="${s.critical_open ? "alert" : ""}"><b>${s.critical_open}</b> critical open</div>
      <div><b>${s.avg_reply_seconds ?? "–"}</b> s avg reply</div>
      <div><b>${s.understood_rate == null ? "–" : Math.round(s.understood_rate * 100) + "%"}</b> understood</div>`;
  } catch {}
}
$("#pendingOnly").onchange = e => { onlyPending = e.target.checked; loadInbox(); };
$("#resetBtn").onclick = async () => { if (confirm("Delete all demo messages?")) { try { await api("/reset", "POST"); } catch {} loadInbox(); } };
$("#emergencyBtn").onclick = async () => {
  try { const r = await api("/patient/emergency", "POST"); $("#sentInfo").textContent = `Emergency alert sent (#${r.id}). Staff have been notified.`; } catch {}
};
