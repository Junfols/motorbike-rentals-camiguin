(function () {
  "use strict";

  const {
    escapeHtml,
    formatMoney,
    paymentStatusLabel,
    showToast,
    openModal,
    closeModal,
    updateShopTextInDom,
  } = window.MotoRide;

  const loginView = document.getElementById("admin-login-view");
  const dashboardView = document.getElementById("admin-dashboard-view");
  const loginForm = document.getElementById("admin-login-form");
  const loginError = document.getElementById("admin-login-error");
  const logoutBtn = document.getElementById("admin-logout-btn");
  const refreshBtn = document.getElementById("admin-refresh-btn");
  const shareBtn = document.getElementById("admin-share-btn");

  const tabsNav = document.querySelector(".admin-tabs");
  const tabPanels = document.querySelectorAll(".admin-tab-panel");
  const pendingBadge = document.getElementById("tab-pending-badge");
  const partnerBadge = document.getElementById("tab-partner-badge");

  // Overview
  const kpiGrid = document.getElementById("admin-kpi-grid");
  const revenueBars = document.getElementById("revenue-bars");
  const upcomingList = document.getElementById("upcoming-rides-list");
  const jumpBookingsBtn = document.getElementById("jump-bookings-btn");
  const jumpPartnersBtn = document.getElementById("jump-partners-btn");

  // Partners
  const shopStatusPills = document.getElementById("admin-shop-status-pills");
  const partnersList = document.getElementById("admin-partners-list");
  const addPartnerBtn = document.getElementById("add-partner-btn");
  const partnerCreatorForm = document.getElementById("partner-creator-form");
  const partnerCreatorError = document.getElementById("partner-creator-error");

  // Bookings
  const bookingStatusPills = document.getElementById("admin-booking-status-pills");
  const bookingShopFilter = document.getElementById("admin-booking-shop-filter");
  const bookingSearchInput = document.getElementById("admin-booking-search");
  const bookingsList = document.getElementById("admin-bookings-list");

  // Fleet
  const fleetShopFilter = document.getElementById("admin-fleet-shop-filter");
  const addBikeBtn = document.getElementById("add-bike-btn");
  const fleetList = document.getElementById("admin-fleet-list");
  const bikeEditorForm = document.getElementById("bike-editor-form");
  const bikeEditorTitle = document.getElementById("bike-editor-title");
  const bikeEditorError = document.getElementById("bike-editor-error");
  const editBikeShopSelect = document.getElementById("edit-bike-shop-id");

  // Settings
  const settingsForm = document.getElementById("admin-settings-form");
  const settingsError = document.getElementById("settings-error");

  const adminState = {
    shopStatus: "all",
    bookingStatus: "all",
    bookingShopId: "",
    bookingQuery: "",
    fleetShopId: "",
    shops: [],
    allShops: [],
    bikes: [],
    bookings: [],
  };

  function statusLabel(status) {
    const map = {
      pending: "Pending",
      confirmed: "Confirmed",
      active: "Active",
      completed: "Completed",
      cancelled: "Cancelled",
      approved: "Approved",
      suspended: "Suspended",
    };
    return map[status] || status;
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && url !== "/api/admin/login") {
      showLogin();
      throw new Error("Session expired. Please sign in again.");
    }
    if (!res.ok) {
      throw new Error(data.error || "Request failed.");
    }
    return data;
  }

  function showLogin() {
    loginView.classList.remove("hidden");
    dashboardView.classList.add("hidden");
  }

  function showDashboard() {
    loginView.classList.add("hidden");
    dashboardView.classList.remove("hidden");
  }

  function switchTab(tabName) {
    document.querySelectorAll(".tab-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-admin-tab") === tabName);
    });
    tabPanels.forEach((panel) => {
      panel.classList.toggle("hidden", panel.id !== `tab-${tabName}`);
    });
  }

  async function checkSession() {
    try {
      const data = await apiJson("/api/admin/me");
      if (data.authenticated) {
        showDashboard();
        await loadAllAdminData();
      } else {
        showLogin();
      }
    } catch (_) {
      showLogin();
    }
  }

  async function loadAllAdminData() {
    await Promise.all([
      loadDashboard(),
      loadPartners(),
      loadBookings(),
      loadFleet(),
      loadSettings(),
    ]);
  }

  function populateShopSelects(shops) {
    const options = shops
      .map(
        (s) =>
          `<option value="${s.id}">${escapeHtml(s.shop_name)} (${escapeHtml(s.municipality)})</option>`
      )
      .join("");

    if (bookingShopFilter) {
      const prev = bookingShopFilter.value;
      bookingShopFilter.innerHTML = `<option value="">All Partner Shops</option>${options}`;
      bookingShopFilter.value = prev;
    }
    if (fleetShopFilter) {
      const prev = fleetShopFilter.value;
      fleetShopFilter.innerHTML = `<option value="">All Partner Shops</option>${options}`;
      fleetShopFilter.value = prev;
    }
    if (editBikeShopSelect) {
      const prev = editBikeShopSelect.value;
      editBikeShopSelect.innerHTML = options;
      if (prev) editBikeShopSelect.value = prev;
    }
  }

  async function loadDashboard() {
    const data = await apiJson("/api/admin/dashboard");
    const k = data.kpis;

    pendingBadge.textContent = k.pending_count;
    pendingBadge.classList.toggle("hidden", k.pending_count === 0);

    partnerBadge.textContent = k.pending_shops;
    partnerBadge.classList.toggle("hidden", k.pending_shops === 0);

    kpiGrid.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Partner Shops</div>
        <div class="kpi-value">${k.approved_shops}</div>
        <div class="kpi-sub">${k.pending_shops} pending approval &bull; ${k.suspended_shops} suspended</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">All Bookings</div>
        <div class="kpi-value">${k.pending_count} pending</div>
        <div class="kpi-sub">${k.confirmed_count} confirmed &bull; ${k.active_count} active</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Gross Platform Volume</div>
        <div class="kpi-value">${escapeHtml(formatMoney(k.projected_revenue))}</div>
        <div class="kpi-sub">Month: ${escapeHtml(formatMoney(k.month_revenue))} &bull; Today: ${escapeHtml(formatMoney(k.today_revenue))}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Platform Commission (${k.commission_rate}%)</div>
        <div class="kpi-value">${escapeHtml(formatMoney(k.platform_fee_total))}</div>
        <div class="kpi-sub">Partner payouts: ${escapeHtml(formatMoney(k.partner_payout_total))}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Verified GCash Reservation Fees</div>
        <div class="kpi-value">${escapeHtml(formatMoney(k.collected_reservation_total || 0))}</div>
        <div class="kpi-sub">${k.pending_payment_verifications || 0} receipt(s) to verify (${escapeHtml(formatMoney(k.pending_verification_total || 0))})</div>
      </div>
    `;

    const bars = data.revenue_by_shop || [];
    const maxRev = Math.max(1, ...bars.map((s) => s.gross_revenue));
    if (!bars.length) {
      revenueBars.innerHTML = `<p class="text-muted">No shop revenue data yet.</p>`;
    } else {
      revenueBars.innerHTML = bars
        .map((s) => {
          const pct = Math.round((s.gross_revenue / maxRev) * 100);
          return `
            <div class="revenue-bar-row">
              <div class="revenue-bar-labels">
                <span>${escapeHtml(s.shop_name)} (${s.booking_count})</span>
                <span>${escapeHtml(formatMoney(s.gross_revenue))} <small class="text-muted">(Fee: ${escapeHtml(formatMoney(s.platform_fee_total))})</small></span>
              </div>
              <div class="revenue-bar-track">
                <div class="revenue-bar-fill" style="width:${pct}%"></div>
              </div>
            </div>
          `;
        })
        .join("");
    }

    const upcoming = data.upcoming || [];
    if (!upcoming.length) {
      upcomingList.innerHTML = `<p class="text-muted">No upcoming or active rentals yet.</p>`;
    } else {
      upcomingList.innerHTML = upcoming
        .map(
          (b) => `
            <div class="upcoming-item">
              <div>
                <strong>${escapeHtml(b.bike_name)}</strong> &bull; ${escapeHtml(b.shop_name || "")}
                <div class="text-muted">${escapeHtml(b.customer_name)} &bull; ${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)} (${escapeHtml(b.booking_code)})</div>
              </div>
              <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
            </div>
          `
        )
        .join("");
    }
  }

  async function loadPartners() {
    const allRes = await apiJson("/api/admin/shops?status=all");
    adminState.allShops = allRes.shops || [];
    populateShopSelects(adminState.allShops);

    if (adminState.shopStatus === "all") {
      adminState.shops = adminState.allShops;
    } else {
      adminState.shops = adminState.allShops.filter((s) => s.status === adminState.shopStatus);
    }
    renderPartners();
  }

  function renderPartners() {
    if (!adminState.shops.length) {
      partnersList.innerHTML = `<div class="empty-state">No partner shops match this filter.</div>`;
      return;
    }

    partnersList.innerHTML = adminState.shops
      .map((s) => {
        const actions = [];
        if (!s.is_main) {
          if (s.status !== "approved") {
            actions.push(`<button type="button" class="btn btn-sm btn-success" data-shop-action="approved" data-id="${s.id}">Approve Shop</button>`);
          }
          if (s.status !== "suspended") {
            actions.push(`<button type="button" class="btn btn-sm btn-outline" data-shop-action="suspended" data-id="${s.id}">Suspend</button>`);
          }
          actions.push(`<button type="button" class="btn btn-sm btn-danger" data-delete-shop="${s.id}">Delete</button>`);
        }

        return `
          <div class="admin-booking-card">
            <div class="admin-booking-top">
              <div>
                <strong>${escapeHtml(s.shop_name)}</strong>
                ${s.is_main ? `<span class="badge badge-soft">Main Hub</span>` : ""}
                <span class="text-muted">&bull; ${escapeHtml(s.municipality)}, Camiguin</span>
              </div>
              <span class="badge badge-${escapeHtml(s.status)}">${escapeHtml(statusLabel(s.status))}</span>
            </div>

            <div class="trip-details-grid">
              <div>
                <span class="trip-detail-label">Owner &amp; Login</span>
                <strong>${escapeHtml(s.owner_name)}</strong>
                <div class="text-muted">${escapeHtml(s.email)}</div>
              </div>
              <div>
                <span class="trip-detail-label">Contact</span>
                <strong>${escapeHtml(s.phone)}</strong>
                <div class="text-muted">${escapeHtml(s.address || s.municipality)}</div>
              </div>
              <div>
                <span class="trip-detail-label">Fleet / Bookings</span>
                <strong>${s.bike_count || 0} model(s)</strong>
                <div class="text-muted">${s.booking_count || 0} booking(s)</div>
              </div>
              <div>
                <span class="trip-detail-label">Gross / Platform Fee</span>
                <strong>${escapeHtml(formatMoney(s.gross_revenue || 0))}</strong>
                <div class="text-muted">Fee: ${escapeHtml(formatMoney(s.platform_fee_total || 0))} &bull; Payout: ${escapeHtml(formatMoney(s.shop_payout_total || 0))}</div>
              </div>
            </div>

            ${
              actions.length
                ? `<div class="admin-booking-actions">${actions.join("")}</div>`
                : `<div class="text-muted" style="font-size:0.82rem;">Platform Main Fleet Hub (always active)</div>`
            }
          </div>
        `;
      })
      .join("");
  }

  async function loadBookings() {
    const params = new URLSearchParams({
      status: adminState.bookingStatus,
      q: adminState.bookingQuery,
    });
    if (adminState.bookingShopId) {
      params.set("shop_id", adminState.bookingShopId);
    }
    const data = await apiJson(`/api/admin/bookings?${params.toString()}`);
    adminState.bookings = data.bookings || [];
    renderBookings();
  }

  function renderBookings() {
    if (!adminState.bookings.length) {
      bookingsList.innerHTML = `<div class="empty-state">No bookings match this filter.</div>`;
      return;
    }

    bookingsList.innerHTML = adminState.bookings
      .map((b) => {
        const actions = [];
        const payStatus = b.payment_status || "unpaid";
        const payLabel = paymentStatusLabel(payStatus);
        const payChannelLabel = b.payment_channel === "maya"
          ? "Maya"
          : b.payment_channel === "gcash"
          ? "GCash"
          : "Pay at Shop";
        const hasOnlineFee = Number(b.reservation_fee || 0) > 0;

        if (payStatus === "submitted" && b.status === "pending") {
          actions.push(`<button type="button" class="btn btn-sm btn-success" data-verify-confirm="${b.id}">Verify &amp; Confirm</button>`);
        }
        if (b.status === "pending") {
          actions.push(`<button type="button" class="btn btn-sm btn-success" data-booking-action="confirmed" data-id="${b.id}">Approve</button>`);
          actions.push(`<button type="button" class="btn btn-sm btn-danger" data-booking-action="cancelled" data-id="${b.id}">Reject</button>`);
        } else if (b.status === "confirmed") {
          actions.push(`<button type="button" class="btn btn-sm btn-primary" data-booking-action="active" data-id="${b.id}">Mark Picked Up</button>`);
          actions.push(`<button type="button" class="btn btn-sm btn-danger" data-booking-action="cancelled" data-id="${b.id}">Cancel</button>`);
        } else if (b.status === "active") {
          actions.push(`<button type="button" class="btn btn-sm btn-success" data-booking-action="completed" data-id="${b.id}">Mark Returned</button>`);
        }
        const showBalanceTools = ["confirmed", "active", "completed"].includes(b.status);
        const balanceOwed = Number(b.balance_due !== undefined && b.balance_due !== null ? b.balance_due : b.total_amount) > 0;
        if (showBalanceTools && balanceOwed) {
          actions.push(
            b.balance_paid
              ? `<button type="button" class="btn btn-sm btn-outline" data-balance-paid="0" data-id="${b.id}">Undo Balance Paid</button>`
              : `<button type="button" class="btn btn-sm btn-primary" data-balance-paid="1" data-id="${b.id}">Mark Balance Paid</button>`
          );
        }
        const balanceBadge = !showBalanceTools
          ? ""
          : !balanceOwed
          ? `<span class="badge badge-verified">Paid in full</span>`
          : b.balance_paid
          ? `<span class="badge badge-verified">Balance Paid</span>`
          : `<span class="badge badge-submitted">Balance Unpaid</span>`;

        if (payStatus === "submitted") {
          actions.push(`<button type="button" class="btn btn-sm btn-primary" data-payment-action="verified" data-id="${b.id}">Verify Receipt</button>`);
          actions.push(`<button type="button" class="btn btn-sm btn-danger" data-payment-action="rejected" data-id="${b.id}">Reject Payment</button>`);
        } else if (payStatus === "verified") {
          actions.push(`<button type="button" class="btn btn-sm btn-outline" data-payment-action="refunded" data-id="${b.id}">Mark Refunded</button>`);
        } else if (payStatus === "rejected" && hasOnlineFee) {
          actions.push(`<button type="button" class="btn btn-sm btn-outline" data-payment-action="verified" data-id="${b.id}">Verify Payment</button>`);
        }

        return `
          <div class="admin-booking-card" data-booking-id="${b.id}">
            <div class="admin-booking-top">
              <div>
                <strong>${escapeHtml(b.booking_code)}</strong> &bull;
                <span>${escapeHtml(b.bike_name)}</span>
                <span class="badge badge-soft">${escapeHtml(b.shop_name || "Shop")}</span>
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
                ${(hasOnlineFee || payStatus !== "unpaid") ? `<span class="badge badge-${escapeHtml(payStatus)}">${escapeHtml(payLabel)}</span>` : ""}
                <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
              </div>
            </div>

            <div class="trip-details-grid">
              <div>
                <span class="trip-detail-label">Customer</span>
                <strong>${escapeHtml(b.customer_name)}</strong>
                <div class="text-muted">${escapeHtml(b.customer_phone)}</div>
              </div>
              <div>
                <span class="trip-detail-label">Dates</span>
                <strong>${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)}</strong>
                <div class="text-muted">${b.rental_days}d &bull; ${escapeHtml(b.pickup_time)}</div>
              </div>
              <div>
                <span class="trip-detail-label">Total / Fee (${b.commission_rate}%)</span>
                <strong>${escapeHtml(formatMoney(b.total_amount))}</strong>
                <div class="text-muted">Fee: ${escapeHtml(formatMoney(b.platform_fee))} &bull; Payout: ${escapeHtml(formatMoney(b.shop_payout))}</div>
              </div>
              <div>
                <span class="trip-detail-label">Reservation / Balance Due</span>
                <strong>${escapeHtml(formatMoney(b.balance_due !== undefined && b.balance_due !== null ? b.balance_due : b.total_amount))}</strong> ${balanceBadge}
                <div class="text-muted">${hasOnlineFee ? `${escapeHtml(payChannelLabel)}: ${escapeHtml(formatMoney(b.reservation_fee))}` : "Pay 100% at shop"} &bull; Dep: ${escapeHtml(formatMoney(b.deposit_amount))}</div>
              </div>
              <div>
                <span class="trip-detail-label">License #</span>
                <strong>${escapeHtml(b.license_number)}</strong>
              </div>
            </div>

            ${(b.payment_reference || b.payment_proof_url) ? `<div class="text-muted"><strong>Payment Proof:</strong> ${escapeHtml(payChannelLabel)}${b.payment_reference ? ` &bull; Ref # ${escapeHtml(b.payment_reference)}` : ""}${b.payment_proof_url ? ` &bull; <a href="${escapeHtml(b.payment_proof_url)}" target="_blank" rel="noopener" class="payment-proof-link">View Receipt Screenshot</a>` : ""}</div>` : ""}
            ${b.delivery_address ? `<div class="text-muted"><strong>Delivery to:</strong> ${escapeHtml(b.delivery_address)}</div>` : ""}
            ${b.notes ? `<div class="text-muted"><strong>Customer note:</strong> ${escapeHtml(b.notes)}</div>` : ""}

            <div class="admin-booking-actions">
              ${actions.join("")}
              <div class="admin-note-inline">
                <input type="text" placeholder="Admin/Shop note" value="${escapeHtml(b.admin_notes || "")}" data-note-input="${b.id}">
                <button type="button" class="btn btn-sm btn-outline" data-save-note="${b.id}">Save Note</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function loadFleet() {
    const params = new URLSearchParams();
    if (adminState.fleetShopId) {
      params.set("shop_id", adminState.fleetShopId);
    }
    const qs = params.toString();
    const data = await apiJson(`/api/admin/bikes${qs ? `?${qs}` : ""}`);
    adminState.bikes = data.bikes || [];
    renderFleet();
  }

  function renderFleet() {
    if (!adminState.bikes.length) {
      fleetList.innerHTML = `<div class="empty-state">No motorbikes found for this filter.</div>`;
      return;
    }

    fleetList.innerHTML = adminState.bikes
      .map((bike) => {
        const badgeClass =
          bike.status === "available"
            ? "badge-available"
            : bike.status === "maintenance"
            ? "badge-maintenance"
            : "badge-completed";

        return `
          <div class="admin-bike-card">
            <img src="${escapeHtml(bike.image_url)}" alt="${escapeHtml(bike.name)}">
            <div class="admin-bike-body">
              <div class="shop-pill-line" style="margin-bottom:6px;">
                ${escapeHtml(bike.shop_name || "Shop")} (${escapeHtml(bike.shop_municipality || "")})
              </div>
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                <strong>${escapeHtml(bike.name)}</strong>
                <span class="badge ${badgeClass}">${escapeHtml(bike.status)}</span>
              </div>
              <div class="text-muted" style="margin:4px 0 8px;">
                ${escapeHtml(bike.category)} &bull; ${bike.engine_cc}cc &bull; ${escapeHtml(bike.transmission)}
              </div>
              <div style="font-size:0.88rem;margin-bottom:6px;">
                <strong>${escapeHtml(formatMoney(bike.daily_rate))}/day</strong>
                ${bike.weekly_rate > 0 ? `&bull; ${escapeHtml(formatMoney(bike.weekly_rate))}/wk` : ""}
              </div>
              <div class="text-muted">
                Units: ${bike.units_count} (Booked today: ${bike.booked_units}) ${bike.plate_number ? `&bull; ${escapeHtml(bike.plate_number)}` : ""}
              </div>
              <div class="admin-bike-actions">
                <button type="button" class="btn btn-sm btn-outline" data-edit-bike="${bike.id}" style="flex:1;">Edit</button>
                <button type="button" class="btn btn-sm btn-danger" data-delete-bike="${bike.id}">Delete</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function updateAlertStatusPill(el, isReady, readyText, mutedText) {
    if (!el) return;
    el.textContent = isReady ? readyText : mutedText;
    el.classList.remove("ready", "muted");
    el.classList.add(isReady ? "ready" : "muted");
  }

  function applyAlertSettingsToForm(s) {
    const tokenInput = document.getElementById("set-telegram-bot-token");
    if (tokenInput) tokenInput.value = "";
    const clearTokenBox = document.getElementById("clear-telegram-bot-token");
    if (clearTokenBox) clearTokenBox.checked = false;
    const clearTokenWrap = document.getElementById("clear-telegram-token-wrap");
    if (clearTokenWrap) clearTokenWrap.classList.toggle("hidden", !s.has_telegram_bot_token);
    updateAlertStatusPill(
      document.getElementById("telegram-token-status"),
      !!s.has_telegram_bot_token,
      "Saved",
      "Not set"
    );

    const smtpPassInput = document.getElementById("set-smtp-password");
    if (smtpPassInput) smtpPassInput.value = "";
    const clearPassBox = document.getElementById("clear-smtp-password");
    if (clearPassBox) clearPassBox.checked = false;
    const clearPassWrap = document.getElementById("clear-smtp-password-wrap");
    if (clearPassWrap) clearPassWrap.classList.toggle("hidden", !s.has_smtp_password);
    updateAlertStatusPill(
      document.getElementById("smtp-password-status"),
      !!s.has_smtp_password,
      "Saved",
      "Not set"
    );

    document.getElementById("set-admin-telegram-chat-id").value = s.admin_telegram_chat_id || "";
    document.getElementById("set-admin-notify-email").value = s.admin_notify_email || "";
    document.getElementById("set-smtp-host").value = s.smtp_host || "";
    document.getElementById("set-smtp-port").value = s.smtp_port || "587";
    document.getElementById("set-smtp-username").value = s.smtp_username || "";
    document.getElementById("set-smtp-from-email").value = s.smtp_from_email || "";
    document.getElementById("set-notify-partner-email").checked = s.notify_partner_email !== "0";
    document.getElementById("set-notify-customer-email").checked = s.notify_customer_email === "1";

    const tgReady = !!(s.has_telegram_bot_token && (s.admin_telegram_chat_id || "").trim());
    const emailReady = !!((s.smtp_host || "").trim() && (s.admin_notify_email || "").trim());
    const summaryEl = document.getElementById("admin-alerts-summary-pill");
    if (tgReady && emailReady) {
      updateAlertStatusPill(summaryEl, true, "Telegram + Email Active", "Optional");
    } else if (tgReady) {
      updateAlertStatusPill(summaryEl, true, "Telegram Active", "Optional");
    } else if (emailReady) {
      updateAlertStatusPill(summaryEl, true, "Email Active", "Optional");
    } else {
      updateAlertStatusPill(summaryEl, false, "Active", "Not Configured");
    }
  }

  function renderAlertChannelResults(containerEl, data) {
    if (!containerEl) return;
    const results = data.results || {};
    const parts = Object.entries(results).map(([channel, info]) => {
      const icon = info.ok ? "OK" : "Failed";
      return `${channel.toUpperCase()}: ${icon} — ${info.detail || ""}`;
    });
    containerEl.textContent = parts.length ? parts.join(" | ") : data.error || "No alert channels configured.";
    containerEl.classList.remove("hidden", "ok", "err");
    containerEl.classList.add(data.ok ? "ok" : "err");
  }

  const MAX_QR_UPLOAD_BYTES = 8 * 1024 * 1024;
  const ALLOWED_QR_EXTENSIONS = new Set(["png", "jpg", "jpeg", "jfif", "webp"]);
  let activeQrUploadPromise = null;
  let qrAutoUploadedDone = false;

  function setQrHint(message, tone = "neutral") {
    const qrHintEl = document.getElementById("admin-qr-status-hint");
    if (!qrHintEl) return;
    qrHintEl.classList.remove("field-hint-error", "field-hint-success");
    if (tone === "error") qrHintEl.classList.add("field-hint-error");
    if (tone === "success") qrHintEl.classList.add("field-hint-success");
    qrHintEl.textContent = message;
  }

  function validateQrFileClient(file) {
    if (!file) return "Please choose a QR image file first.";
    const parts = String(file.name || "").toLowerCase().split(".");
    const ext = parts.length > 1 ? parts.pop() : "";
    const mimeOk = /^image\/(png|jpe?g|pjpeg|webp)$/i.test(file.type || "");
    if (!ALLOWED_QR_EXTENSIONS.has(ext) && !mimeOk) {
      return "Unsupported file type. Please choose a PNG, JPG, JPEG, JFIF, or WEBP QR image.";
    }
    if (file.size <= 0) {
      return "Selected QR image file is empty.";
    }
    if (file.size > MAX_QR_UPLOAD_BYTES) {
      const sizeMb = (file.size / (1024 * 1024)).toFixed(1);
      return `Selected image is ${sizeMb} MB (max 8 MB). Please crop or screenshot the QR code cleanly.`;
    }
    return null;
  }

  function applyPaymentSettingsToForm(s) {
    const modeEl = document.getElementById("set-reservation-mode");
    const pctEl = document.getElementById("set-reservation-percent");
    const nameEl = document.getElementById("set-gcash-account-name");
    const gcashEl = document.getElementById("set-gcash-number");
    const mayaEl = document.getElementById("set-maya-number");
    const instEl = document.getElementById("set-payment-instructions");
    const pillEl = document.getElementById("admin-payment-status-pill");
    const previewImg = document.getElementById("admin-qr-preview-img");
    const removeQrBtn = document.getElementById("remove-qr-btn");
    
    const mode = (s.reservation_mode || "optional").toLowerCase();
    if (modeEl) modeEl.value = mode;
    if (pctEl) pctEl.value = s.reservation_percent ?? "10";
    if (nameEl) nameEl.value = s.gcash_account_name || "";
    if (gcashEl) gcashEl.value = s.gcash_number || "";
    if (mayaEl) mayaEl.value = s.maya_number || "";
    if (instEl) instEl.value = s.payment_instructions || "";

    const qrUrl = (s.gcash_qr_url || "").trim();
    const configured = Boolean(qrUrl || (s.gcash_number || "").trim() || (s.maya_number || "").trim());

    if (pillEl) {
      if (mode === "off") {
        pillEl.textContent = "Off";
        pillEl.className = "status-pill-inline muted";
      } else if (configured) {
        pillEl.textContent = mode === "required" ? "Required Active" : "Optional Active";
        pillEl.className = "status-pill-inline ready";
      } else {
        pillEl.textContent = "Needs QR or Number";
        pillEl.className = "status-pill-inline muted";
      }
    }

    if (previewImg) {
      if (qrUrl) {
        previewImg.src = qrUrl;
        previewImg.classList.remove("hidden");
      } else {
        previewImg.src = "";
        previewImg.classList.add("hidden");
      }
    }
    if (removeQrBtn) {
      removeQrBtn.classList.toggle("hidden", !qrUrl);
    }
    setQrHint(
      qrUrl
        ? "QR code is live on customer checkout. Upload another file anytime to replace it."
        : "Choose your GCash / Maya InstaPay QR image (PNG/JPG, up to 8 MB) — it uploads automatically once selected.",
      qrUrl ? "success" : "neutral"
    );
  }

  async function uploadQrImageFile(file) {
    const validationError = validateQrImageFile(file);
    if (validationError) {
        throw new Error(validationError);
    }

    const formData = new FormData();
    formData.append("qr_image", file);
    const data = await apiJson("/api/admin/settings/qr", {
      method: "POST",
      body: formData,
    });
    if (data.settings) {
      updateShopTextInDom(data.settings);
      applyPaymentSettingsToForm(data.settings);
    }
    return data;
  }

  async function loadSettings() {
    const data = await apiJson("/api/admin/settings");
    const s = data.settings || {};
    document.getElementById("set-shop-name").value = s.shop_name || "";
    document.getElementById("set-location").value = s.location || "";
    document.getElementById("set-tagline").value = s.tagline || "";
    document.getElementById("set-address").value = s.address || "";
    document.getElementById("set-opening-hours").value = s.opening_hours || "";
    document.getElementById("set-phone").value = s.phone || "";
    document.getElementById("set-email").value = s.email || "";
    document.getElementById("set-whatsapp").value = s.whatsapp_number || "";
    document.getElementById("set-messenger").value = s.messenger_url || "";
    document.getElementById("set-commission-rate").value = s.commission_rate ?? "10";
    document.getElementById("set-currency").value = s.currency || "₱";
    document.getElementById("set-delivery-fee").value = s.delivery_fee || "0";
    document.getElementById("set-helmet-fee").value = s.extra_helmet_fee || "0";
    document.getElementById("set-topbox-fee").value = s.top_box_fee || "0";
    document.getElementById("set-terms-note").value = s.terms_note || "";
    applyPaymentSettingsToForm(s);
    applyAlertSettingsToForm(s);
  }

  function openBikeEditor(bike) {
    bikeEditorError.classList.add("hidden");
    bikeEditorForm.reset();

    if (bike) {
      bikeEditorTitle.textContent = `Edit ${bike.name}`;
      document.getElementById("edit-bike-id").value = bike.id;
      editBikeShopSelect.value = String(bike.shop_id);
      document.getElementById("edit-bike-name").value = bike.name;
      document.getElementById("edit-bike-category").value = bike.category;
      document.getElementById("edit-bike-cc").value = bike.engine_cc;
      document.getElementById("edit-bike-transmission").value = bike.transmission;
      document.getElementById("edit-bike-units").value = bike.units_count;
      document.getElementById("edit-bike-status").value = bike.status;
      document.getElementById("edit-bike-daily").value = bike.daily_rate;
      document.getElementById("edit-bike-weekly").value = bike.weekly_rate;
      document.getElementById("edit-bike-deposit").value = bike.deposit;
      document.getElementById("edit-bike-plate").value = bike.plate_number || "";
      document.getElementById("edit-bike-fuel").value = bike.fuel_type || "Gasoline";
      document.getElementById("edit-bike-image-url").value = bike.image_url || "";
      document.getElementById("edit-bike-inclusions").value = bike.inclusions || "";
      document.getElementById("edit-bike-description").value = bike.description || "";
      document.getElementById("edit-bike-featured").checked = Boolean(bike.featured);
    } else {
      bikeEditorTitle.textContent = "Add Motorbike";
      document.getElementById("edit-bike-id").value = "";
      if (adminState.fleetShopId) {
        editBikeShopSelect.value = adminState.fleetShopId;
      }
      document.getElementById("edit-bike-image-url").value = "/static/images/bike-click125.jpg";
    }
    openModal("bike-editor-modal");
  }

  // Event Listeners
  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    loginError.classList.add("hidden");
    const password = document.getElementById("admin-password").value;

    try {
      await apiJson("/api/admin/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      document.getElementById("admin-password").value = "";
      showDashboard();
      await loadAllAdminData();
      showToast("Signed in to Main Admin", "success");
    } catch (err) {
      loginError.textContent = err.message;
      loginError.classList.remove("hidden");
    }
  });

  logoutBtn.addEventListener("click", async () => {
    await apiJson("/api/admin/logout", { method: "POST" });
    showLogin();
    showToast("Signed out.");
  });

  refreshBtn.addEventListener("click", async () => {
    try {
      await loadAllAdminData();
      showToast("Dashboard refreshed.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  if (shareBtn) {
    shareBtn.addEventListener("click", async () => {
      const url = `${window.location.origin}/`;
      const shopName = window.MotoRide.shop.shop_name || "Motorbike Rentals Camiguin";
      if (navigator.share) {
        try {
          await navigator.share({
            title: shopName,
            text: `Rent motorbikes across Camiguin via ${shopName}:`,
            url,
          });
          return;
        } catch (_) {
          // Fall back to copy
        }
      }
      try {
        await navigator.clipboard.writeText(url);
        showToast("Platform link copied!", "success");
      } catch (_) {
        showToast(url);
      }
    });
  }

  tabsNav.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-admin-tab]");
    if (!btn) return;
    switchTab(btn.getAttribute("data-admin-tab"));
  });

  jumpBookingsBtn.addEventListener("click", () => switchTab("bookings"));
  jumpPartnersBtn.addEventListener("click", () => switchTab("partners"));

  // Partner Shops Events
  shopStatusPills.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-shop-status]");
    if (!pill) return;
    shopStatusPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    adminState.shopStatus = pill.getAttribute("data-shop-status");
    loadPartners();
  });

  addPartnerBtn.addEventListener("click", () => {
    partnerCreatorError.classList.add("hidden");
    partnerCreatorForm.reset();
    document.getElementById("new-shop-delivery").value = "200";
    document.getElementById("new-shop-password").value = "partner1234";
    openModal("partner-creator-modal");
  });

  partnerCreatorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    partnerCreatorError.classList.add("hidden");
    try {
      await apiJson("/api/admin/shops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          shop_name: document.getElementById("new-shop-name").value.trim(),
          owner_name: document.getElementById("new-shop-owner").value.trim(),
          email: document.getElementById("new-shop-email").value.trim(),
          phone: document.getElementById("new-shop-phone").value.trim(),
          municipality: document.getElementById("new-shop-municipality").value,
          delivery_fee: document.getElementById("new-shop-delivery").value,
          address: document.getElementById("new-shop-address").value.trim(),
          password: document.getElementById("new-shop-password").value,
          status: document.getElementById("new-shop-status").value,
        }),
      });
      closeModal("partner-creator-modal");
      await Promise.all([loadDashboard(), loadPartners()]);
      showToast("Partner rental shop created!", "success");
    } catch (err) {
      partnerCreatorError.textContent = err.message;
      partnerCreatorError.classList.remove("hidden");
    }
  });

  partnersList.addEventListener("click", async (event) => {
    const actionBtn = event.target.closest("[data-shop-action]");
    if (actionBtn) {
      const id = actionBtn.getAttribute("data-id");
      const status = actionBtn.getAttribute("data-shop-action");
      actionBtn.disabled = true;
      try {
        await apiJson(`/api/admin/shops/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        await Promise.all([loadDashboard(), loadPartners(), loadFleet()]);
        showToast(`Partner shop marked ${status}.`, "success");
      } catch (err) {
        showToast(err.message, "error");
        actionBtn.disabled = false;
      }
      return;
    }

    const delBtn = event.target.closest("[data-delete-shop]");
    if (delBtn) {
      const id = delBtn.getAttribute("data-delete-shop");
      if (!window.confirm("Delete this partner shop account?")) return;
      try {
        await apiJson(`/api/admin/shops/${id}`, { method: "DELETE" });
        await Promise.all([loadDashboard(), loadPartners()]);
        showToast("Partner shop removed.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    }
  });

  // Bookings Events
  bookingStatusPills.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-status]");
    if (!pill) return;
    bookingStatusPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    adminState.bookingStatus = pill.getAttribute("data-status");
    loadBookings();
  });

  bookingShopFilter.addEventListener("change", () => {
    adminState.bookingShopId = bookingShopFilter.value;
    loadBookings();
  });

  let bookingSearchTimer = null;
  bookingSearchInput.addEventListener("input", () => {
    clearTimeout(bookingSearchTimer);
    bookingSearchTimer = setTimeout(() => {
      adminState.bookingQuery = bookingSearchInput.value.trim();
      loadBookings();
    }, 220);
  });

  bookingsList.addEventListener("click", async (event) => {
    const verifyConfirmBtn = event.target.closest("[data-verify-confirm]");
    if (verifyConfirmBtn) {
      const id = verifyConfirmBtn.getAttribute("data-verify-confirm");
      verifyConfirmBtn.disabled = true;
      try {
        await apiJson(`/api/admin/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payment_status: "verified", status: "confirmed" }),
        });
        await Promise.all([loadDashboard(), loadPartners(), loadBookings(), loadFleet()]);
        showToast("Payment verified & booking confirmed!", "success");
      } catch (err) {
        showToast(err.message, "error");
        verifyConfirmBtn.disabled = false;
      }
      return;
    }

    const payBtn = event.target.closest("[data-payment-action]");
    if (payBtn) {
      const id = payBtn.getAttribute("data-id");
      const paymentStatus = payBtn.getAttribute("data-payment-action");
      payBtn.disabled = true;
      try {
        await apiJson(`/api/admin/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ payment_status: paymentStatus }),
        });
        await Promise.all([loadDashboard(), loadBookings()]);
        showToast(`Payment marked ${paymentStatusLabel(paymentStatus).toLowerCase()}.`, "success");
      } catch (err) {
        showToast(err.message, "error");
        payBtn.disabled = false;
      }
      return;
    }
    const balanceBtn = event.target.closest("[data-balance-paid]");
    if (balanceBtn) {
      const id = balanceBtn.getAttribute("data-id");
      const paid = balanceBtn.getAttribute("data-balance-paid") === "1";
      balanceBtn.disabled = true;
      try {
        await apiJson(`/api/admin/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ balance_paid: paid }),
        });
        await Promise.all([loadDashboard(), loadBookings()]);
        showToast(paid ? "Balance marked as paid." : "Balance marked as unpaid.", "success");
      } catch (err) {
        showToast(err.message, "error");
        balanceBtn.disabled = false;
      }
      return;
    }

    const statusBtn = event.target.closest("[data-booking-action]");
    if (statusBtn) {
      const id = statusBtn.getAttribute("data-id");
      const status = statusBtn.getAttribute("data-booking-action");
      statusBtn.disabled = true;
      try {
        await apiJson(`/api/admin/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        await Promise.all([loadDashboard(), loadPartners(), loadBookings(), loadFleet()]);
        showToast(`Booking marked ${status}.`, "success");
      } catch (err) {
        showToast(err.message, "error");
        statusBtn.disabled = false;
      }
      return;
    }

    const noteBtn = event.target.closest("[data-save-note]");
    if (noteBtn) {
      const id = noteBtn.getAttribute("data-save-note");
      const input = bookingsList.querySelector(`[data-note-input="${id}"]`);
      try {
        await apiJson(`/api/admin/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ admin_notes: input ? input.value : "" }),
        });
        showToast("Note saved.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    }
  });

  // Fleet Events
  fleetShopFilter.addEventListener("change", () => {
    adminState.fleetShopId = fleetShopFilter.value;
    loadFleet();
  });

  addBikeBtn.addEventListener("click", () => openBikeEditor(null));

  fleetList.addEventListener("click", async (event) => {
    const editBtn = event.target.closest("[data-edit-bike]");
    if (editBtn) {
      const id = Number(editBtn.getAttribute("data-edit-bike"));
      const bike = adminState.bikes.find((b) => b.id === id);
      if (bike) openBikeEditor(bike);
      return;
    }

    const deleteBtn = event.target.closest("[data-delete-bike]");
    if (deleteBtn) {
      const id = Number(deleteBtn.getAttribute("data-delete-bike"));
      if (!window.confirm("Delete this motorbike from fleet?")) return;
      try {
        await apiJson(`/api/admin/bikes/${id}`, { method: "DELETE" });
        await Promise.all([loadDashboard(), loadPartners(), loadFleet()]);
        showToast("Motorbike removed.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    }
  });

  bikeEditorForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    bikeEditorError.classList.add("hidden");

    const id = document.getElementById("edit-bike-id").value;
    const formData = new FormData(bikeEditorForm);
    formData.set("featured", document.getElementById("edit-bike-featured").checked ? "true" : "false");

    try {
      const url = id ? `/api/admin/bikes/${id}` : "/api/admin/bikes";
      const method = id ? "PUT" : "POST";
      await apiJson(url, { method, body: formData });
      closeModal("bike-editor-modal");
      await Promise.all([loadDashboard(), loadPartners(), loadFleet()]);
      showToast(id ? "Motorbike updated!" : "New motorbike added!", "success");
    } catch (err) {
      bikeEditorError.textContent = err.message;
      bikeEditorError.classList.remove("hidden");
    }
  });

  settingsForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    settingsError.classList.add("hidden");

    const payload = {
      shop_name: document.getElementById("set-shop-name").value.trim(),
      location: document.getElementById("set-location").value.trim(),
      tagline: document.getElementById("set-tagline").value.trim(),
      address: document.getElementById("set-address").value.trim(),
      opening_hours: document.getElementById("set-opening-hours").value.trim(),
      phone: document.getElementById("set-phone").value.trim(),
      email: document.getElementById("set-email").value.trim(),
      whatsapp_number: document.getElementById("set-whatsapp").value.trim(),
      messenger_url: document.getElementById("set-messenger").value.trim(),
      commission_rate: document.getElementById("set-commission-rate").value,
      currency: document.getElementById("set-currency").value.trim(),
      delivery_fee: document.getElementById("set-delivery-fee").value,
      extra_helmet_fee: document.getElementById("set-helmet-fee").value,
      top_box_fee: document.getElementById("set-topbox-fee").value,
      terms_note: document.getElementById("set-terms-note").value.trim(),
      reservation_mode: document.getElementById("set-reservation-mode").value,
      reservation_percent: document.getElementById("set-reservation-percent").value,
      gcash_account_name: document.getElementById("set-gcash-account-name").value.trim(),
      gcash_number: document.getElementById("set-gcash-number").value.trim(),
      maya_number: document.getElementById("set-maya-number").value.trim(),
      payment_instructions: document.getElementById("set-payment-instructions").value.trim(),
      admin_telegram_chat_id: document.getElementById("set-admin-telegram-chat-id").value.trim(),
      telegram_bot_token: document.getElementById("set-telegram-bot-token").value.trim(),
      clear_telegram_bot_token: document.getElementById("clear-telegram-bot-token").checked,
      admin_notify_email: document.getElementById("set-admin-notify-email").value.trim(),
      smtp_host: document.getElementById("set-smtp-host").value.trim(),
      smtp_port: document.getElementById("set-smtp-port").value.trim(),
      smtp_username: document.getElementById("set-smtp-username").value.trim(),
      smtp_password: document.getElementById("set-smtp-password").value.trim(),
      clear_smtp_password: document.getElementById("clear-smtp-password").checked,
      smtp_from_email: document.getElementById("set-smtp-from-email").value.trim(),
      notify_partner_email: document.getElementById("set-notify-partner-email").checked,
      notify_customer_email: document.getElementById("set-notify-customer-email").checked,
      current_password: document.getElementById("set-current-password").value,
      new_password: document.getElementById("set-new-password").value,
    };

    try {
      const qrFileInput = document.getElementById("set-qr-image-file");
      if (qrFileInput && qrFileInput.files && qrFileInput.files[0]) {
        await uploadQrImageFile(qrFileInput.files[0]);
        qrFileInput.value = "";
      }
      const data = await apiJson("/api/admin/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      updateShopTextInDom(data.settings);
      applyPaymentSettingsToForm(data.settings);
      applyAlertSettingsToForm(data.settings);
      document.getElementById("admin-shop-subtitle").textContent =
        `${data.settings.shop_name} • ${data.settings.location}`;
      document.getElementById("set-current-password").value = "";
      document.getElementById("set-new-password").value = "";
      await loadDashboard();
      showToast("Platform settings saved!", "success");
    } catch (err) {
      settingsError.textContent = err.message;
      settingsError.classList.remove("hidden");
    }
  });

    const qrFileInput = document.getElementById("set-qr-image-file");
  if (qrFileInput) {
    qrFileInput.addEventListener("change", () => {
      const file = qrFileInput.files && qrFileInput.files[0];
      if (!file) return;
      qrAutoUploadedDone = false;
      runQrUpload(file).catch(() => {});
    });
  }

  const uploadQrBtn = document.getElementById("upload-qr-btn");
  if (uploadQrBtn) {
    uploadQrBtn.addEventListener("click", async () => {
      if (activeQrUploadPromise) {
        try {
          await activeQrUploadPromise;
        } catch (_) {}
        return;
      }
      const fileInput = document.getElementById("set-qr-image-file");
      const file = fileInput && fileInput.files ? fileInput.files[0] : null;
      if (!file) {
        const previewImg = document.getElementById("admin-qr-preview-img");
        const alreadyLive = qrAutoUploadedDone || (previewImg && !previewImg.classList.contains("hidden"));
        if (alreadyLive) {
          showToast("QR code is already uploaded and live!", "success");
          return;
        }
        setQrHint("Please choose a QR image file first.", "error");
        showToast("Please choose a QR image file first.", "error");
        return;
      }
      try {
        await runQrUpload(file);
        await loadDashboard();
      } catch (_) {}
    });
  }

  const removeQrBtn = document.getElementById("remove-qr-btn");
  if (removeQrBtn) {
    removeQrBtn.addEventListener("click", async () => {
      removeQrBtn.disabled = true;
      try {
        qrAutoUploadedDone = false;
        const fileInput = document.getElementById("set-qr-image-file");
        if (fileInput) fileInput.value = "";
        const data = await apiJson("/api/admin/settings", {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ clear_gcash_qr: true }),
        });
        updateShopTextInDom(data.settings);
        applyPaymentSettingsToForm(data.settings);
        await loadDashboard();
        showToast("QR image removed.", "success");
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        removeQrBtn.disabled = false;
      }
    });
  }
  const testAdminAlertBtn = document.getElementById("test-admin-alert-btn");
  if (testAdminAlertBtn) {
    testAdminAlertBtn.addEventListener("click", async () => {
      const resultEl = document.getElementById("admin-alert-test-result");
      testAdminAlertBtn.disabled = true;
      testAdminAlertBtn.textContent = "Sending...";
      if (resultEl) resultEl.classList.add("hidden");
      try {
        const res = await fetch("/api/admin/settings/test-alert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            telegram_bot_token: document.getElementById("set-telegram-bot-token").value.trim(),
            admin_telegram_chat_id: document.getElementById("set-admin-telegram-chat-id").value.trim(),
            admin_notify_email: document.getElementById("set-admin-notify-email").value.trim(),
            smtp_host: document.getElementById("set-smtp-host").value.trim(),
            smtp_port: document.getElementById("set-smtp-port").value.trim(),
            smtp_username: document.getElementById("set-smtp-username").value.trim(),
            smtp_password: document.getElementById("set-smtp-password").value.trim(),
            smtp_from_email: document.getElementById("set-smtp-from-email").value.trim(),
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) {
          showLogin();
          return;
        }
        renderAlertChannelResults(resultEl, data);
        showToast(
          data.ok ? "Test alert delivered!" : "Test alert failed — check details.",
          data.ok ? "success" : "error"
        );
      } catch (err) {
        if (resultEl) {
          resultEl.textContent = err.message;
          resultEl.classList.remove("hidden", "ok");
          resultEl.classList.add("err");
        }
      } finally {
        testAdminAlertBtn.disabled = false;
        testAdminAlertBtn.textContent = "Send Test Alert";
      }
    });
  }

  checkSession();
})();
