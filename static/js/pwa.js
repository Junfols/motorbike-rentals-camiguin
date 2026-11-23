(function () {
  "use strict";

  const configEl = document.getElementById("shop-config-data");
  let shopConfig = {};
  if (configEl) {
    try {
      shopConfig = JSON.parse(configEl.textContent || "{}");
    } catch (_) {
      shopConfig = {};
    }
  }

  function escapeHtml(value) {
    const str = String(value ?? "");
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatMoney(amount, currencyOverride) {
    const curr = currencyOverride || shopConfig.currency || "₱";
    const num = Number(amount || 0);
    const hasFraction = Math.abs(num % 1) > 0.001;
    const formatted = num.toLocaleString(undefined, {
      minimumFractionDigits: hasFraction ? 2 : 0,
      maximumFractionDigits: hasFraction ? 2 : 0,
    });
    return `${curr}${formatted}`;
  }

  function showToast(message, type) {
    const container = document.getElementById("toast-container");
    if (!container) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type || ""}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
      toast.remove();
    }, 3600);
  }

  function openModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.remove("hidden");
    document.body.style.overflow = "hidden";
  }

  function closeModal(id) {
    const el = document.getElementById(id);
    if (!el) return;
    el.classList.add("hidden");
    const anyOpen = document.querySelector(".modal-backdrop:not(.hidden)");
    if (!anyOpen) {
      document.body.style.overflow = "";
    }
  }

  document.addEventListener("click", (event) => {
    const closeTarget = event.target.closest("[data-close-modal]");
    if (closeTarget) {
      closeModal(closeTarget.getAttribute("data-close-modal"));
      return;
    }
    if (event.target.classList && event.target.classList.contains("modal-backdrop")) {
      closeModal(event.target.id);
    }
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      document.querySelectorAll(".modal-backdrop:not(.hidden)").forEach((el) => {
        closeModal(el.id);
      });
    }
  });

  // Offline status indicator
  const offlineBanner = document.getElementById("offline-banner");
  function syncOnlineState() {
    if (!offlineBanner) return;
    if (navigator.onLine) {
      offlineBanner.classList.add("hidden");
    } else {
      offlineBanner.classList.remove("hidden");
    }
  }
  window.addEventListener("online", syncOnlineState);
  window.addEventListener("offline", syncOnlineState);
  syncOnlineState();

  // PWA Service Worker registration (immediate so beforeinstallprompt fires faster)
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((err) => {
      console.warn("Service worker registration skipped:", err);
    });
  }

  // PWA Install Prompt handling (direct 1-tap install when supported)
  let deferredPrompt = window.__deferredInstallPrompt || null;
  let waitingForPromptResolve = null;
  const installBtn = document.getElementById("install-app-btn");
  const mobileInstallBtn = document.getElementById("mobile-install-nav-btn");
  const nativeCtaBox = document.getElementById("native-install-cta-box");
  const triggerNativeInstallBtn = document.getElementById("trigger-native-install");
  const inAppBrowserBox = document.getElementById("inapp-browser-install-box");
  const openInChromeBtn = document.getElementById("open-in-chrome-install-btn");
  const copyInstallLinkBtn = document.getElementById("copy-install-link-btn");
  const installModalHint = document.getElementById("install-modal-hint");

  const ua = navigator.userAgent || "";
  const isIOS = /iPad|iPhone|iPod/i.test(ua) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const isAndroid = /Android/i.test(ua);
  const isInAppBrowser = /FBAN|FBAV|FB_IAB|Instagram|Messenger|Line\/|MicroMessenger/i.test(ua);

  function isStandaloneMode() {
    return (
      (window.matchMedia && window.matchMedia("(display-mode: standalone)").matches) ||
      window.navigator.standalone === true
    );
  }

  function setInstallButtonsVisible(visible) {
    [installBtn, mobileInstallBtn].forEach((btn) => {
      if (!btn) return;
      btn.classList.toggle("hidden", !visible);
    });
  }

  function syncInstallReadyUi() {
    if (isStandaloneMode()) {
      setInstallButtonsVisible(false);
      return;
    }
    if (deferredPrompt && nativeCtaBox) {
      nativeCtaBox.classList.remove("hidden");
    }
    if (installBtn) {
      const label = installBtn.querySelector("span");
      if (label) label.textContent = "Install App";
    }
  }

  function captureInstallPrompt(event) {
    event.preventDefault();
    deferredPrompt = event;
    window.__deferredInstallPrompt = event;
    syncInstallReadyUi();
    if (waitingForPromptResolve) {
      const resolveFn = waitingForPromptResolve;
      waitingForPromptResolve = null;
      resolveFn(event);
    }
  }

  window.addEventListener("beforeinstallprompt", captureInstallPrompt);

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    window.__deferredInstallPrompt = null;
    if (nativeCtaBox) nativeCtaBox.classList.add("hidden");
    setInstallButtonsVisible(false);
    closeModal("install-modal");
    showToast("MotoRentals installed on your device!", "success");
  });

  syncInstallReadyUi();

  function waitBrieflyForInstallPrompt(timeoutMs) {
    if (deferredPrompt || window.__deferredInstallPrompt) {
      deferredPrompt = deferredPrompt || window.__deferredInstallPrompt;
      return Promise.resolve(deferredPrompt);
    }
    if (isIOS || isInAppBrowser) {
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      let settled = false;
      const timer = setTimeout(() => {
        if (!settled) {
          settled = true;
          waitingForPromptResolve = null;
          resolve(deferredPrompt || window.__deferredInstallPrompt || null);
        }
      }, timeoutMs);
      waitingForPromptResolve = (ev) => {
        if (!settled) {
          settled = true;
          clearTimeout(timer);
          resolve(ev);
        }
      };
    });
  }

  function prepareFallbackInstallModal() {
    if (inAppBrowserBox) {
      inAppBrowserBox.classList.toggle("hidden", !isInAppBrowser);
    }
    if (openInChromeBtn) {
      if (isAndroid) {
        const cleanHostPath = `${window.location.host}${window.location.pathname}${window.location.search}`;
        openInChromeBtn.href = `intent://${cleanHostPath}#Intent;scheme=https;package=com.android.chrome;end`;
        openInChromeBtn.classList.remove("hidden");
      } else {
        openInChromeBtn.classList.add("hidden");
      }
    }
    if (installModalHint) {
      if (isInAppBrowser) {
        installModalHint.textContent = "Opened inside Facebook / Messenger? Open in Chrome first for direct 1-tap install.";
      } else if (isIOS) {
        installModalHint.textContent = "On iPhone/iPad Safari, tap Share then 'Add to Home Screen' to install.";
      } else {
        installModalHint.textContent = "Already installed on your Home Screen, or tap your browser menu below to install.";
      }
    }
    document.querySelectorAll("[data-install-platform]").forEach((box) => {
      const plat = box.getAttribute("data-install-platform");
      if (isIOS) {
        box.classList.toggle("hidden", plat !== "ios");
      } else if (isAndroid) {
        box.classList.toggle("hidden", plat !== "android");
      } else {
        box.classList.remove("hidden");
      }
    });
  }

  async function triggerNativeInstallPrompt(promptEvent) {
    try {
      await promptEvent.prompt();
      const choice = await promptEvent.userChoice;
      deferredPrompt = null;
      window.__deferredInstallPrompt = null;
      if (nativeCtaBox) nativeCtaBox.classList.add("hidden");
      closeModal("install-modal");
      if (choice && choice.outcome === "accepted") {
        showToast("Installing MotoRentals app...", "success");
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  async function handleInstallClick() {
    if (isStandaloneMode()) {
      showToast("MotoRentals is already installed!", "success");
      return;
    }
    deferredPrompt = deferredPrompt || window.__deferredInstallPrompt;
    if (deferredPrompt) {
      const triggered = await triggerNativeInstallPrompt(deferredPrompt);
      if (triggered) return;
    }

    // Wait briefly in case Chrome is still finishing beforeinstallprompt on first page load
    const readyPrompt = await waitBrieflyForInstallPrompt(900);
    if (readyPrompt) {
      const triggered = await triggerNativeInstallPrompt(readyPrompt);
      if (triggered) return;
    }

    prepareFallbackInstallModal();
    openModal("install-modal");
  }

  if (copyInstallLinkBtn) {
    copyInstallLinkBtn.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(window.location.href);
        showToast("Link copied! Paste in Chrome to install directly.", "success");
      } catch (_) {
        showToast(window.location.href, "info");
      }
    });
  }

  if (installBtn) installBtn.addEventListener("click", handleInstallClick);
  if (mobileInstallBtn) mobileInstallBtn.addEventListener("click", handleInstallClick);
  if (triggerNativeInstallBtn) triggerNativeInstallBtn.addEventListener("click", handleInstallClick);

  // Hidden 10-tap shortcut on the app icon to open /admin
  (function initAdminTapShortcut() {
    const ADMIN_TAP_TARGET = 10;
    const TAP_RESET_MS = 2500;
    const SINGLE_TAP_NAV_DELAY_MS = 700;
    let tapCount = 0;
    let resetTimer = null;
    let homeNavTimer = null;

    document.addEventListener("click", (event) => {
      const trigger = event.target.closest("[data-admin-tap-trigger]");
      if (!trigger) return;

      const parentLink = trigger.closest("a[href]");
      if (parentLink) {
        event.preventDefault();
        event.stopPropagation();
      }

      if (homeNavTimer) {
        clearTimeout(homeNavTimer);
        homeNavTimer = null;
      }
      if (resetTimer) {
        clearTimeout(resetTimer);
      }

      tapCount += 1;

      if (tapCount >= ADMIN_TAP_TARGET) {
        tapCount = 0;
        resetTimer = null;
        if (window.location.pathname !== "/admin") {
          window.location.assign("/admin");
        }
        return;
      }

      resetTimer = setTimeout(() => {
        tapCount = 0;
        resetTimer = null;
      }, TAP_RESET_MS);

      if (tapCount === 1 && parentLink) {
        const targetHref = parentLink.getAttribute("href") || "/";
        const targetUrl = new URL(targetHref, window.location.origin);
        if (targetUrl.pathname !== window.location.pathname) {
          homeNavTimer = setTimeout(() => {
            homeNavTimer = null;
            if (tapCount === 1) {
              tapCount = 0;
              window.location.assign(parentLink.href);
            }
          }, SINGLE_TAP_NAV_DELAY_MS);
        }
      }
    });
  })();

  function saveRecentTrip(booking) {
    try {
      const key = "motoride_recent_trips";
      const current = JSON.parse(localStorage.getItem(key) || "[]");
      const filtered = current.filter((item) => item.booking_code !== booking.booking_code);
      filtered.unshift({
        booking_code: booking.booking_code,
        customer_phone: booking.customer_phone,
        bike_name: booking.bike_name,
        pickup_date: booking.pickup_date,
        return_date: booking.return_date,
        total_amount: booking.total_amount,
        status: booking.status,
      });
      localStorage.setItem(key, JSON.stringify(filtered.slice(0, 10)));
    } catch (_) {
      // Ignore storage quota issues
    }
  }

  function updateShopTextInDom(newSettings) {
    Object.assign(shopConfig, newSettings);
    document.querySelectorAll("[data-shop-name]").forEach((el) => {
      el.textContent = shopConfig.shop_name || "Motorbike Rentals Camiguin";
    });
    document.querySelectorAll("[data-shop-location]").forEach((el) => {
      el.textContent = shopConfig.location || "";
    });
    document.querySelectorAll("[data-shop-tagline]").forEach((el) => {
      el.textContent = shopConfig.tagline || "";
    });
    document.querySelectorAll("[data-shop-address]").forEach((el) => {
      el.textContent = shopConfig.address || "";
    });
    document.querySelectorAll("[data-shop-hours]").forEach((el) => {
      el.textContent = shopConfig.opening_hours || "";
    });
    document.querySelectorAll("[data-shop-phone]").forEach((el) => {
      el.textContent = shopConfig.phone || "";
    });
    document.querySelectorAll("[data-shop-email]").forEach((el) => {
      el.textContent = shopConfig.email || "";
    });
  }

  function paymentStatusLabel(status) {
    const labels = {
      unpaid: "Pay at Shop",
      submitted: "Receipt Submitted",
      verified: "Reservation Paid",
      rejected: "Payment Rejected",
      refunded: "Refunded",
    };
    return labels[status] || status || "Pay at Shop";
  }

  const SHORT_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const CALENDAR_WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

  function toLocalIsoDate(dt) {
    const d = dt instanceof Date ? dt : new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  function parseLocalIsoDate(isoStr) {
    if (!isoStr || !/^\d{4}-\d{2}-\d{2}$/.test(isoStr)) return null;
    const [y, m, d] = isoStr.split("-").map(Number);
    return new Date(y, m - 1, d);
  }

  function formatShortDate(isoStr) {
    const dt = parseLocalIsoDate(isoStr);
    if (!dt) return String(isoStr || "");
    const curYear = new Date().getFullYear();
    const label = `${SHORT_MONTHS[dt.getMonth()]} ${dt.getDate()}`;
    return dt.getFullYear() !== curYear ? `${label}, '${String(dt.getFullYear()).slice(-2)}` : label;
  }

  function formatDateRangeShort(startIso, endIso) {
    if (!startIso) return "";
    if (!endIso || startIso === endIso) return formatShortDate(startIso);
    const s = parseLocalIsoDate(startIso);
    const e = parseLocalIsoDate(endIso);
    if (!s || !e) return `${startIso} to ${endIso}`;
    const curYear = new Date().getFullYear();
    if (s.getFullYear() === e.getFullYear() && s.getMonth() === e.getMonth()) {
      const yrSuffix = s.getFullYear() !== curYear ? `, '${String(s.getFullYear()).slice(-2)}` : "";
      return `${SHORT_MONTHS[s.getMonth()]} ${s.getDate()}–${e.getDate()}${yrSuffix}`;
    }
    return `${formatShortDate(startIso)} – ${formatShortDate(endIso)}`;
  }

  function formatBookedRangesLabel(ranges, limit = 2) {
    if (!Array.isArray(ranges) || !ranges.length) return "";
    const slice = ranges.slice(0, limit).map((r) => formatDateRangeShort(r.pickup_date || r.start_date, r.return_date || r.end_date));
    const extra = ranges.length > limit ? ` (+${ranges.length - limit} more)` : "";
    return `${slice.join(", ")}${extra}`;
  }

  function renderAvailabilityCalendarHtml(calendarDays, opts = {}) {
    if (!Array.isArray(calendarDays) || !calendarDays.length) {
      return `<div class="text-muted">Calendar preview unavailable.</div>`;
    }
    const { selectedPickup = "", selectedReturn = "", interactive = false } = opts;
    const firstDt = parseLocalIsoDate(calendarDays[0].date);
    const leadingBlanks = firstDt ? firstDt.getDay() : 0;

    const cells = [];
    for (let i = 0; i < leadingBlanks; i += 1) {
      cells.push(`<div class="cal-cell cal-empty" aria-hidden="true"></div>`);
    }

    calendarDays.forEach((day, idx) => {
      const dt = parseLocalIsoDate(day.date);
      const dayNum = dt ? dt.getDate() : day.date.slice(-2);
      const monthTag = dt && (idx === 0 || dayNum === 1) ? SHORT_MONTHS[dt.getMonth()] : "";
      const isBooked = day.status === "booked";
      const isPickup = Boolean(selectedPickup && day.date === selectedPickup);
      const isReturn = Boolean(selectedReturn && day.date === selectedReturn);
      const inRange = Boolean(
        selectedPickup && selectedReturn && day.date >= selectedPickup && day.date <= selectedReturn
      );

      let subLabel = "Open";
      if (isBooked) {
        subLabel = "Booked";
      } else if (day.status === "limited") {
        subLabel = `${day.available_units} left`;
      }

      const cls = [
        "cal-cell",
        `cal-${day.status}`,
        interactive ? "cal-interactive" : "",
        isPickup ? "cal-pickup" : "",
        isReturn ? "cal-return" : "",
        inRange ? "cal-in-range" : "",
      ]
        .filter(Boolean)
        .join(" ");

      const titleText = isBooked
        ? `${formatShortDate(day.date)}: Already booked`
        : `${formatShortDate(day.date)}: ${day.available_units} of ${day.units_count} unit(s) open`;

      if (interactive) {
        cells.push(`
          <button
            type="button"
            class="${cls}"
            data-cal-date="${escapeHtml(day.date)}"
            data-cal-status="${escapeHtml(day.status)}"
            title="${escapeHtml(titleText)}"
            ${isBooked ? 'disabled aria-disabled="true"' : ""}
          >
            ${monthTag ? `<span class="cal-month-tag">${escapeHtml(monthTag)}</span>` : ""}
            <span class="cal-day-num">${dayNum}</span>
            <span class="cal-day-status">${escapeHtml(subLabel)}</span>
          </button>
        `);
      } else {
        cells.push(`
          <div class="${cls}" title="${escapeHtml(titleText)}">
            ${monthTag ? `<span class="cal-month-tag">${escapeHtml(monthTag)}</span>` : ""}
            <span class="cal-day-num">${dayNum}</span>
            <span class="cal-day-status">${escapeHtml(subLabel)}</span>
          </div>
        `);
      }
    });

    return `
      <div class="avail-cal-legend">
        <span class="cal-legend-item"><span class="cal-dot cal-dot-open"></span>Open</span>
        <span class="cal-legend-item"><span class="cal-dot cal-dot-limited"></span>Limited Units</span>
        <span class="cal-legend-item"><span class="cal-dot cal-dot-booked"></span>Booked</span>
        ${interactive ? `<span class="cal-legend-item"><span class="cal-dot cal-dot-selected"></span>Your Dates</span>` : ""}
      </div>
      <div class="avail-cal-weekdays">
        ${CALENDAR_WEEKDAYS.map((w) => `<span>${w}</span>`).join("")}
      </div>
      <div class="avail-cal-grid">${cells.join("")}</div>
    `;
  }

  function renderAdminBikeScheduleSummary(bike) {
    const bookedText = formatBookedRangesLabel(bike.booked_ranges, 2);
    const activeBlocks = Array.isArray(bike.blocks) ? bike.blocks.length : 0;
    const statusSelect = `
      <div class="quick-status-row">
        <label style="font-size:0.78rem;color:var(--muted);font-weight:700;">Availability:</label>
        <select class="select-compact bike-quick-status" data-quick-status="${bike.id}" aria-label="Change availability for ${escapeHtml(bike.name)}">
          <option value="available" ${bike.status === "available" ? "selected" : ""}>Available</option>
          <option value="maintenance" ${bike.status === "maintenance" ? "selected" : ""}>Maintenance</option>
          <option value="hidden" ${bike.status === "hidden" ? "selected" : ""}>Hidden</option>
        </select>
      </div>
    `;
    const scheduleBadge = bookedText
      ? `<div class="bike-sched-line warn">Booked dates: <strong>${escapeHtml(bookedText)}</strong></div>`
      : `<div class="bike-sched-line ok">Open for all upcoming dates</div>`;
    const blocksHint = activeBlocks > 0 ? `<div class="bike-sched-sub">${activeBlocks} walk-in/manual block(s)</div>` : "";
    return `${statusSelect}${scheduleBadge}${blocksHint}`;
  }

  function createBikeScheduleController({ apiBase, onUpdated }) {
    const modal = document.getElementById("bike-schedule-modal");
    if (!modal) {
      return {
        open: async () => {},
        quickChangeStatus: async () => {},
      };
    }

    const titleEl = document.getElementById("sched-modal-title");
    const metaEl = document.getElementById("sched-bike-meta");
    const errEl = document.getElementById("sched-modal-error");
    const statusForm = document.getElementById("sched-status-form");
    const statusSel = document.getElementById("sched-status-select");
    const unitsInput = document.getElementById("sched-units-input");
    const blockForm = document.getElementById("sched-block-form");
    const startInput = document.getElementById("sched-block-start");
    const endInput = document.getElementById("sched-block-end");
    const blockUnitsInput = document.getElementById("sched-block-units");
    const reasonInput = document.getElementById("sched-block-reason");
    const blocksList = document.getElementById("sched-blocks-list");
    const bookingsList = document.getElementById("sched-bookings-list");
    const calPreview = document.getElementById("sched-calendar-preview");

    let activeBikeId = null;

    async function requestJson(url, opts) {
      const res = await fetch(url, opts);
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || `Request failed (${res.status})`);
      }
      return data;
    }

    function renderModalBike(bike) {
      activeBikeId = bike.id;
      titleEl.textContent = `Manage Availability — ${bike.name}`;
      metaEl.textContent = `${bike.units_count} total unit(s) • ${bike.booked_units} booked today • Status: ${bike.status}`;
      statusSel.value = bike.status || "available";
      unitsInput.value = bike.units_count || 1;
      blockUnitsInput.max = bike.units_count || 1;
      blockUnitsInput.value = Math.min(Number(blockUnitsInput.value || 1), bike.units_count || 1) || 1;

      const todayIso = toLocalIsoDate(new Date());
      if (startInput && !startInput.value) startInput.value = todayIso;
      if (endInput && (!endInput.value || endInput.value < startInput.value)) endInput.value = startInput.value;
      if (startInput) startInput.min = todayIso;
      if (endInput) endInput.min = startInput.value || todayIso;

      const blocks = bike.blocks || [];
      if (!blocks.length) {
        blocksList.innerHTML = `<div class="text-muted">No manual date blocks yet.</div>`;
      } else {
        blocksList.innerHTML = blocks
          .map(
            (blk) => `
              <div class="sched-item-row">
                <div>
                  <strong>${escapeHtml(formatDateRangeShort(blk.start_date, blk.end_date))}</strong>
                  <div class="text-muted">${escapeHtml(blk.reason)} &bull; ${blk.units_blocked} unit(s)</div>
                </div>
                <button type="button" class="btn btn-sm btn-outline" data-unblock-id="${blk.id}">Unblock</button>
              </div>
            `
          )
          .join("");
      }

      const upcoming = bike.upcoming_bookings || [];
      if (!upcoming.length) {
        bookingsList.innerHTML = `<div class="text-muted">No upcoming customer bookings.</div>`;
      } else {
        bookingsList.innerHTML = upcoming
          .map(
            (b) => `
              <div class="sched-item-row">
                <div>
                  <strong>${escapeHtml(formatDateRangeShort(b.pickup_date, b.return_date))}</strong>
                  <div class="text-muted">${escapeHtml(b.booking_code)} &bull; ${escapeHtml(b.customer_name)}</div>
                </div>
                <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(b.status)}</span>
              </div>
            `
          )
          .join("");
      }

      if (calPreview) {
        calPreview.innerHTML = renderAvailabilityCalendarHtml(bike.availability_calendar || [], { interactive: false });
      }
    }

    if (startInput) {
      startInput.addEventListener("change", () => {
        if (endInput) {
          endInput.min = startInput.value;
          if (!endInput.value || endInput.value < startInput.value) {
            endInput.value = startInput.value;
          }
        }
      });
    }

    if (statusForm) {
      statusForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!activeBikeId) return;
        errEl.classList.add("hidden");
        try {
          const data = await requestJson(`${apiBase}/${activeBikeId}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              status: statusSel.value,
              units_count: Number(unitsInput.value || 1),
            }),
          });
          renderModalBike(data.bike);
          if (typeof onUpdated === "function") await onUpdated();
          showToast("Motorbike status & units saved.", "success");
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
        }
      });
    }

    if (blockForm) {
      blockForm.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (!activeBikeId) return;
        errEl.classList.add("hidden");
        try {
          const data = await requestJson(`${apiBase}/${activeBikeId}/blocks`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              start_date: startInput.value,
              end_date: endInput.value,
              units_blocked: Number(blockUnitsInput.value || 1),
              reason: (reasonInput.value || "").trim() || "Walk-in / Offline Booking",
            }),
          });
          renderModalBike(data.bike);
          if (typeof onUpdated === "function") await onUpdated();
          showToast("Dates blocked. Customers now see those dates as Booked.", "success");
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
        }
      });
    }

    if (blocksList) {
      blocksList.addEventListener("click", async (event) => {
        const btn = event.target.closest("[data-unblock-id]");
        if (!btn || !activeBikeId) return;
        errEl.classList.add("hidden");
        btn.disabled = true;
        try {
          const blkId = btn.getAttribute("data-unblock-id");
          const data = await requestJson(`${apiBase}/${activeBikeId}/blocks/${blkId}`, { method: "DELETE" });
          renderModalBike(data.bike);
          if (typeof onUpdated === "function") await onUpdated();
          showToast("Date block removed. Dates are open again.", "success");
        } catch (err) {
          errEl.textContent = err.message;
          errEl.classList.remove("hidden");
          btn.disabled = false;
        }
      });
    }

    return {
      async open(bikeId) {
        errEl.classList.add("hidden");
        try {
          const data = await requestJson(`${apiBase}/${bikeId}/blocks`);
          const todayIso = toLocalIsoDate(new Date());
          if (startInput) startInput.value = todayIso;
          if (endInput) endInput.value = todayIso;
          renderModalBike(data.bike);
          openModal("bike-schedule-modal");
        } catch (err) {
          showToast(err.message, "error");
        }
      },
      async quickChangeStatus(bikeId, statusVal) {
        try {
          await requestJson(`${apiBase}/${bikeId}/status`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ status: statusVal }),
          });
          if (typeof onUpdated === "function") await onUpdated();
          showToast(`Motorbike set to ${statusVal}.`, "success");
        } catch (err) {
          showToast(err.message, "error");
          if (typeof onUpdated === "function") await onUpdated();
        }
      },
    };
  }

  window.MotoRide = {
    get shop() {
      return shopConfig;
    },
    escapeHtml,
    formatMoney,
    formatShortDate,
    formatDateRangeShort,
    formatBookedRangesLabel,
    renderAvailabilityCalendarHtml,
    renderAdminBikeScheduleSummary,
    createBikeScheduleController,
    paymentStatusLabel,
    showToast,
    openModal,
    closeModal,
    saveRecentTrip,
    updateShopTextInDom,
  };
})();
