/* In-app voice calls (WebRTC audio, signaling over HTTP polling). */
(function () {
  "use strict";

  const MotoRide = (window.MotoRide = window.MotoRide || {});
  const toast = (msg, type) => {
    if (MotoRide.showToast) MotoRide.showToast(msg, type);
    else alert(msg);
  };

  const state = {
    call: null, // {id, role, ...}
    pc: null,
    stream: null,
    phone: "", // customer phone (only for customer role)
    pollTimer: null,
    appliedCandidates: 0,
    answerApplied: false,
    pendingCandidates: [],
    callIdReady: false,
    ringTimer: null,
    audioCtx: null,
    connectedAt: 0,
    clockTimer: null,
    fallbackTel: "",
    watcherTimer: null,
    watcherDelay: 4000,
    busy: false,
  };

  // ---------- UI ----------
  const style = document.createElement("style");
  style.textContent = `
  #call-overlay{position:fixed;inset:0;z-index:99999;display:none;align-items:flex-end;justify-content:center;background:rgba(10,20,30,.55);padding:16px}
  #call-overlay.open{display:flex}
  .call-card{width:100%;max-width:420px;background:#0f2b3a;color:#fff;border-radius:24px;padding:24px 20px;text-align:center;box-shadow:0 20px 50px rgba(0,0,0,.4)}
  .call-avatar{width:72px;height:72px;border-radius:50%;background:#14b8a6;margin:0 auto 12px;display:flex;align-items:center;justify-content:center;font-size:34px}
  .call-card h3{margin:0 0 4px;font-size:1.2rem}
  .call-status{opacity:.85;margin-bottom:18px;min-height:1.3em}
  .call-actions{display:flex;gap:12px;justify-content:center;flex-wrap:wrap}
  .call-actions button{border:0;border-radius:999px;padding:14px 20px;font-weight:700;font-size:1rem;cursor:pointer;min-width:110px}
  .call-accept{background:#22c55e;color:#fff}.call-decline,.call-end{background:#ef4444;color:#fff}
  .call-mute{background:#334e5e;color:#fff}.call-mute.on{background:#f59e0b}
  .call-fallback{display:none;margin-top:14px;color:#7dd3fc;font-size:.95rem}
  .call-fallback.show{display:block}
  `;
  document.head.appendChild(style);

  const overlay = document.createElement("div");
  overlay.id = "call-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.innerHTML = `
    <div class="call-card">
      <div class="call-avatar">📞</div>
      <h3 id="call-title">Call</h3>
      <div class="call-status" id="call-status"></div>
      <audio id="call-remote-audio" autoplay playsinline></audio>
      <div class="call-actions">
        <button type="button" class="call-accept" id="call-accept-btn">Answer</button>
        <button type="button" class="call-mute" id="call-mute-btn">Mute</button>
        <button type="button" class="call-decline" id="call-decline-btn">Decline</button>
        <button type="button" class="call-end" id="call-end-btn">End</button>
      </div>
      <a class="call-fallback" id="call-fallback" href="#">Call by phone instead</a>
    </div>`;
  document.body.appendChild(overlay);

  const $ = (id) => document.getElementById(id);
  const els = {
    title: $("call-title"),
    status: $("call-status"),
    audio: $("call-remote-audio"),
    accept: $("call-accept-btn"),
    mute: $("call-mute-btn"),
    decline: $("call-decline-btn"),
    end: $("call-end-btn"),
    fallback: $("call-fallback"),
  };

  function showUI(mode, title, status) {
    overlay.classList.add("open");
    els.title.textContent = title || "Call";
    els.status.textContent = status || "";
    els.accept.style.display = mode === "incoming" ? "" : "none";
    els.decline.style.display = mode === "incoming" ? "" : "none";
    els.mute.style.display = mode === "active" ? "" : "none";
    els.end.style.display = mode === "outgoing" || mode === "active" ? "" : "none";
  }
  function setStatus(text) {
    els.status.textContent = text;
  }

  // ---------- API helper ----------
  async function api(path, opts) {
    const res = await fetch(path, {
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      /* ignore */
    }
    if (!res.ok) {
      const err = new Error(data.error || "Request failed");
      err.status = res.status;
      throw err;
    }
    return data;
  }
  const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body || {}) });

  // ---------- Ringtone ----------
  function startRing() {
    stopRing();
    try {
      const Ctx = window.AudioContext || window.webkitAudioContext;
      if (!Ctx) return;
      state.audioCtx = state.audioCtx || new Ctx();
      const beep = () => {
        const ctx = state.audioCtx;
        if (!ctx) return;
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = 880;
        gain.gain.value = 0.15;
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start();
        osc.stop(ctx.currentTime + 0.4);
        if (navigator.vibrate) navigator.vibrate([300, 150, 300]);
      };
      beep();
      state.ringTimer = setInterval(beep, 2000);
    } catch (e) {
      /* ignore */
    }
  }
  function stopRing() {
    if (state.ringTimer) clearInterval(state.ringTimer);
    state.ringTimer = null;
    if (navigator.vibrate) navigator.vibrate(0);
  }

  // ---------- WebRTC ----------
  async function getMic() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.RTCPeerConnection) {
      throw new Error("Calling is not supported on this browser (HTTPS required).");
    }
    try {
      return await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      throw new Error("Please allow microphone access to make calls.");
    }
  }

  async function createPeer(stream) {
    let iceServers = [{ urls: "stun:stun.l.google.com:19302" }];
    try {
      const cfg = await api("/api/calls/ice-config");
      if (cfg.iceServers && cfg.iceServers.length) iceServers = cfg.iceServers;
    } catch (e) {
      /* fall back to default */
    }
    const pc = new RTCPeerConnection({ iceServers });
    stream.getTracks().forEach((t) => pc.addTrack(t, stream));
    pc.ontrack = (ev) => {
      els.audio.srcObject = ev.streams[0];
      const p = els.audio.play();
      if (p && p.catch) p.catch(() => {});
    };
    pc.onicecandidate = (ev) => {
      if (!ev.candidate) return;
      const cand = ev.candidate.toJSON ? ev.candidate.toJSON() : ev.candidate;
      if (state.callIdReady && state.call) sendCandidate(cand);
      else state.pendingCandidates.push(cand);
    };
    pc.onconnectionstatechange = () => {
      if (pc !== state.pc) return;
      if (pc.connectionState === "connected") markConnected();
      else if (pc.connectionState === "failed") {
        failCall("Connection failed. Try again or use a normal phone call.");
      }
    };
    return pc;
  }

  function sendCandidate(cand) {
    if (!state.call) return;
    post(`/api/calls/${state.call.id}/candidate`, { candidate: cand, phone: state.phone }).catch(() => {});
  }

  function markConnected() {
    if (state.connectedAt) return;
    state.connectedAt = Date.now();
    showUI("active", els.title.textContent, "Connected 00:00");
    state.clockTimer = setInterval(() => {
      const s = Math.floor((Date.now() - state.connectedAt) / 1000);
      const mm = String(Math.floor(s / 60)).padStart(2, "0");
      const ss = String(s % 60).padStart(2, "0");
      setStatus(`Connected ${mm}:${ss}`);
    }, 1000);
  }

  function showFallback() {
    if (state.fallbackTel) {
      els.fallback.href = "tel:" + state.fallbackTel;
      els.fallback.classList.add("show");
    }
  }

  function cleanup(message, delay) {
    stopRing();
    if (state.pollTimer) clearInterval(state.pollTimer);
    if (state.clockTimer) clearInterval(state.clockTimer);
    state.pollTimer = state.clockTimer = null;
    if (state.pc) {
      try {
        state.pc.close();
      } catch (e) {
        /* ignore */
      }
    }
    if (state.stream) state.stream.getTracks().forEach((t) => t.stop());
    els.audio.srcObject = null;
    state.pc = null;
    state.stream = null;
    state.call = null;
    state.appliedCandidates = 0;
    state.answerApplied = false;
    state.pendingCandidates = [];
    state.callIdReady = false;
    state.connectedAt = 0;
    state.busy = false;
    els.mute.classList.remove("on");
    els.mute.textContent = "Mute";
    if (message) {
      overlay.classList.add("open");
      els.accept.style.display = els.decline.style.display = els.mute.style.display = els.end.style.display = "none";
      setStatus(message);
      setTimeout(() => {
        if (!state.call) overlay.classList.remove("open");
        els.fallback.classList.remove("show");
      }, delay || 2500);
    } else {
      overlay.classList.remove("open");
      els.fallback.classList.remove("show");
    }
  }

  function failCall(message) {
    const call = state.call;
    if (call) post(`/api/calls/${call.id}/end`, { phone: state.phone }).catch(() => {});
    cleanup(message, 4000);
    showFallback();
    if (state.fallbackTel) {
      overlay.classList.add("open");
      els.fallback.classList.add("show");
    }
  }

  async function applyRemoteCandidates(list) {
    if (!state.pc || !list) return;
    while (state.appliedCandidates < list.length) {
      const cand = list[state.appliedCandidates++];
      try {
        await state.pc.addIceCandidate(cand);
      } catch (e) {
        /* ignore */
      }
    }
  }

  function startPolling(role) {
    if (state.pollTimer) clearInterval(state.pollTimer);
    let inFlight = false;
    state.pollTimer = setInterval(async () => {
      if (!state.call || inFlight) return;
      inFlight = true;
      try {
        const q = state.phone ? `?phone=${encodeURIComponent(state.phone)}` : "";
        const { call } = await api(`/api/calls/${state.call.id}${q}`);
        if (!state.call) return;
        if (["ended", "declined", "missed"].includes(call.status)) {
          const msg =
            call.status === "declined"
              ? "Call declined."
              : call.status === "missed"
              ? "No answer."
              : "Call ended.";
          const wasOutgoingUnanswered = call.status !== "ended";
          cleanup(msg);
          if (wasOutgoingUnanswered && role === "caller") showFallback();
          return;
        }
        if (role === "caller" && call.answer_sdp && !state.answerApplied && state.pc) {
          state.answerApplied = true;
          await state.pc.setRemoteDescription({ type: "answer", sdp: call.answer_sdp });
          setStatus("Connecting…");
        }
        if (state.pc && (role === "callee" || state.answerApplied)) {
          await applyRemoteCandidates(call.remote_candidates);
        }
      } catch (e) {
        if (e.status === 404 || e.status === 403) cleanup("Call ended.");
      } finally {
        inFlight = false;
      }
    }, 1000);
  }
  // ---------- Outgoing ----------
  async function startCall(code, opts) {
    if (state.busy) {
      toast("You are already on a call.", "error");
      return;
    }
    state.busy = true;
    state.phone = opts.phone || "";
    state.fallbackTel = opts.tel || "";
    showUI("outgoing", opts.name || "Calling…", "Requesting microphone…");
    try {
      state.stream = await getMic();
      state.pc = await createPeer(state.stream);
      const offer = await state.pc.createOffer();
      await state.pc.setLocalDescription(offer);
      setStatus("Calling…");
      const { call } = await post("/api/calls/start", {
        booking_code: code,
        phone: state.phone,
        offer: offer.sdp,
      });
      state.call = call;
      state.callIdReady = true;
      state.pendingCandidates.splice(0).forEach(sendCandidate);
      startPolling("caller");
    } catch (e) {
      const msg = e.message || "Could not start the call.";
      cleanup(null);
      toast(msg, "error");
      if (state.fallbackTel) {
        overlay.classList.add("open");
        showUI("none", opts.name || "Call", msg);
        els.fallback.classList.add("show");
        els.fallback.href = "tel:" + state.fallbackTel;
        setTimeout(() => {
          if (!state.call) overlay.classList.remove("open");
        }, 5000);
      }
    }
  }

  // ---------- Incoming ----------
  function showIncoming(call, phone, tel) {
    if (state.busy) return;
    state.busy = true;
    state.call = call;
    state.phone = phone || "";
    state.fallbackTel = tel || "";
    startRing();
    showUI("incoming", call.caller_name || "Incoming call", `Incoming call • ${call.booking_code}`);
    // Watch the ringing call so we stop if the caller hangs up
    startPolling("callee");
  }

  async function acceptCall() {
    const call = state.call;
    if (!call) return;
    stopRing();
    setStatus("Connecting…");
    showUI("outgoing", els.title.textContent, "Connecting…");
    try {
      state.stream = await getMic();
      state.pc = await createPeer(state.stream);
      await state.pc.setRemoteDescription({ type: "offer", sdp: call.offer_sdp });
      await applyRemoteCandidates(call.remote_candidates || []);
      const answer = await state.pc.createAnswer();
      await state.pc.setLocalDescription(answer);
      state.callIdReady = true;
      await post(`/api/calls/${call.id}/answer`, { answer: answer.sdp, phone: state.phone });
      state.pendingCandidates.splice(0).forEach(sendCandidate);
    } catch (e) {
      failCall(e.message || "Could not answer the call.");
    }
  }

  function declineCall() {
    const call = state.call;
    if (call) post(`/api/calls/${call.id}/end`, { phone: state.phone }).catch(() => {});
    cleanup(null);
  }

  els.accept.addEventListener("click", acceptCall);
  els.decline.addEventListener("click", declineCall);
  els.end.addEventListener("click", declineCall);
  els.mute.addEventListener("click", () => {
    if (!state.stream) return;
    const track = state.stream.getAudioTracks()[0];
    if (!track) return;
    track.enabled = !track.enabled;
    els.mute.classList.toggle("on", !track.enabled);
    els.mute.textContent = track.enabled ? "Mute" : "Unmute";
  });

  // ---------- Incoming watcher ----------
  function watcherContext() {
    const nav = document.body.dataset.nav;
    if (nav === "shop" || nav === "admin") return { url: "/api/calls/incoming", phone: "", tel: "" };
    const btn = document.querySelector("[data-call-booking][data-call-phone]");
    if (btn) {
      const code = btn.dataset.callBooking;
      const phone = btn.dataset.callPhone;
      return {
        url: `/api/calls/incoming?code=${encodeURIComponent(code)}&phone=${encodeURIComponent(phone)}`,
        phone,
        tel: btn.dataset.callTel || "",
      };
    }
    return null;
  }

  async function watchTick() {
    let delay = document.hidden ? 10000 : 4000;
    try {
      if (!state.busy) {
        const ctx = watcherContext();
        if (ctx) {
          const { call } = await api(ctx.url);
          if (call && !state.busy) showIncoming(call, ctx.phone, ctx.tel);
        }
      }
    } catch (e) {
      if (e.status === 401 || e.status === 403) delay = 15000;
    }
    state.watcherTimer = setTimeout(watchTick, delay);
  }

  // ---------- Button wiring ----------
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-call-booking]");
    if (!btn) return;
    ev.preventDefault();
    startCall(btn.dataset.callBooking, {
      phone: btn.dataset.callPhone || "",
      name: btn.dataset.callName || "",
      tel: btn.dataset.callTel || "",
    });
  });

  MotoRide.calls = { start: startCall };
  state.watcherTimer = setTimeout(watchTick, 2500);
})();
