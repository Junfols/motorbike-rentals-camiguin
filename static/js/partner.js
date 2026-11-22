(function () {
  "use strict";

  const {
    escapeHtml,
    formatMoney,
    renderAdminBikeScheduleSummary,
    createBikeScheduleController,
    showToast,
    openModal,
    closeModal,
  } = window.MotoRide;

  const authView = document.getElementById("partner-auth-view");
  const dashboardView = document.getElementById("partner-dashboard-view");
  const authTabs = document.querySelector(".auth-switch-tabs");
  const loginForm = document.getElementById("partner-login-form");
  const registerForm = document.getElementById("partner-register-form");
  const loginError = document.getElementById("partner-login-error");
  const registerError = document.getElementById("partner-register-error");

  const statusBanner = document.getElementById("partner-status-banner");
  const shopTitle = document.getElementById("partner-shop-title");
  const shopStatusBadge = document.getElementById("partner-status-badge");
  const shopSubtitle = document.getElementById("partner-shop-subtitle");
  const refreshBtn = document.getElementById("partner-refresh-btn");
  const logoutBtn = document.getElementById("partner-logout-btn");

  const tabsNav = document.querySelector(".admin-tabs");
  const tabPanels = document.querySelectorAll(".partner-tab-panel");
  const pendingBadge = document.getElementById("partner-pending-badge");

  const kpiGrid = document.getElementById("partner-kpi-grid");
  const upcomingList = document.getElementById("partner-upcoming-list");
  const reviewsList = document.getElementById("partner-reviews-list");
  const jumpBookingsBtn = document.getElementById("partner-jump-bookings-btn");

  const statusPills = document.getElementById("partner-booking-status-pills");
  const bookingSearchInput = document.getElementById("partner-booking-search");
  const bookingsList = document.getElementById("partner-bookings-list");

  const addBikeBtn = document.getElementById("partner-add-bike-btn");
  const fleetList = document.getElementById("partner-fleet-list");
  const bikeForm = document.getElementById("partner-bike-form");
  const bikeModalTitle = document.getElementById("partner-bike-modal-title");
  const bikeError = document.getElementById("partner-bike-error");

  const profileForm = document.getElementById("partner-profile-form");
  const profileError = document.getElementById("partner-profile-error");

  const state = {
    shop: null,
    bookingStatus: "all",
    bookingQuery: "",
    bookings: [],
    bikes: [],
  };

  function statusLabel(status) {
    const map = {
      pending: "Pending",
      confirmed: "Confirmed",
      active: "Active",
      completed: "Completed",
      cancelled: "Cancelled",
      approved: "Verified & Live",
      suspended: "Suspended",
    };
    return map[status] || status;
  }

  async function apiJson(url, options = {}) {
    const res = await fetch(url, options);
    const data = await res.json().catch(() => ({}));
    if (res.status === 401 && !url.includes("/login") && !url.includes("/register")) {
      showAuth();
      throw new Error("Please sign in to your partner account.");
    }
    if (!res.ok) {
      throw new Error(data.error || "Request failed.");
    }
    return data;
  }

  function showAuth() {
    authView.classList.remove("hidden");
    dashboardView.classList.add("hidden");
  }

  function showDashboard() {
    authView.classList.add("hidden");
    dashboardView.classList.remove("hidden");
  }

  function switchAuthTab(tab) {
    authTabs.querySelectorAll(".pill").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-partner-auth-tab") === tab);
    });
    loginForm.classList.toggle("hidden", tab !== "login");
    registerForm.classList.toggle("hidden", tab !== "register");
  }

  function switchTab(tabName) {
    document.querySelectorAll("[data-partner-tab]").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-partner-tab") === tabName);
    });
    tabPanels.forEach((panel) => {
      panel.classList.toggle("hidden", panel.id !== `ptab-${tabName}`);
    });
  }

  function getShopInitials(name) {
    const words = String(name || "Shop")
      .trim()
      .split(/\s+/)
      .filter(Boolean);
    if (!words.length) return "SH";
    if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
    return `${words[0][0]}${words[1][0]}`.toUpperCase();
  }

  function getPartnerPublicUrl(shop) {
    if (!shop) return `${window.location.origin}/`;
    const slug = shop.slug || shop.id;
    return `${window.location.origin}/shop/${encodeURIComponent(slug)}`;
  }

  const DEFAULT_BIKE_PLACEHOLDER = "/static/icons/icon.svg";

  function normalizePartnerBikeImage(url) {
    const clean = String(url || "").trim();
    if (!clean || clean.startsWith("/static/images/")) {
      return DEFAULT_BIKE_PLACEHOLDER;
    }
    return clean;
  }

  function isPlaceholderPartnerBikeImage(bike) {
    if (!bike) return true;
    if (bike.is_placeholder_image) return true;
    return normalizePartnerBikeImage(bike.image_url) === DEFAULT_BIKE_PLACEHOLDER;
  }

  function renderShopHeader(shop) {
    state.shop = shop;
    shopTitle.textContent = shop.shop_name;
    const payoutSummary = shop.payout_number
      ? ` • Payout: ${shop.payout_method || "GCash"} ${shop.payout_number}`
      : "";
    shopSubtitle.textContent = `${shop.municipality}, Camiguin • ${shop.owner_name} • ${shop.email}${payoutSummary}`;
    shopStatusBadge.className = `badge badge-${escapeHtml(shop.status)}`;
    shopStatusBadge.textContent = statusLabel(shop.status);

    const initials = getShopInitials(shop.shop_name);
    const topAvatar = document.getElementById("partner-top-avatar");
    if (topAvatar) {
      if (shop.logo_url && !String(shop.logo_url).startsWith("/static/images/")) {
        topAvatar.innerHTML = `<img src="${escapeHtml(shop.logo_url)}" alt="${escapeHtml(shop.shop_name)}" class="partner-top-avatar-img">`;
      } else {
        topAvatar.textContent = initials;
      }
    }

    const publicUrl = getPartnerPublicUrl(shop);
    const publicPath = shop.share_url || `/shop/${encodeURIComponent(shop.slug || shop.id)}`;
    const fbShareUrl = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(publicUrl)}`;

    const topPreviewLink = document.getElementById("partner-preview-shop-link");
    if (topPreviewLink) topPreviewLink.href = publicPath;

    const openPublicBtn = document.getElementById("prof-open-public-btn");
    if (openPublicBtn) openPublicBtn.href = publicPath;

    const fbShareBtn = document.getElementById("prof-fb-share-btn");
    if (fbShareBtn) fbShareBtn.href = fbShareUrl;

    const shareUrlInput = document.getElementById("prof-share-url-input");
    if (shareUrlInput) shareUrlInput.value = publicUrl;

    const previewName = document.getElementById("prof-preview-shop-name");
    if (previewName) previewName.textContent = shop.shop_name || "Partner Shop";

    const previewMeta = document.getElementById("prof-preview-shop-meta");
    if (previewMeta) {
      previewMeta.textContent = [shop.address, `${shop.municipality || "Mambajao"}, Camiguin`]
        .filter(Boolean)
        .join(" • ");
    }

    const validCoverUrl =
      shop.cover_url && !String(shop.cover_url).startsWith("/static/images/")
        ? shop.cover_url
        : "";
    const coverImg = document.getElementById("prof-cover-preview-img");
    const clearCoverBtn = document.getElementById("prof-clear-cover-btn");
    if (coverImg) {
      if (validCoverUrl) {
        coverImg.src = validCoverUrl;
        coverImg.classList.remove("hidden");
      } else {
        coverImg.src = "";
        coverImg.classList.add("hidden");
      }
    }
    if (clearCoverBtn) {
      clearCoverBtn.classList.toggle("hidden", !validCoverUrl);
    }

    const validLogoUrl =
      shop.logo_url && !String(shop.logo_url).startsWith("/static/images/")
        ? shop.logo_url
        : "";
    const logoImg = document.getElementById("prof-logo-preview-img");
    const logoFallback = document.getElementById("prof-logo-fallback");
    const clearLogoBtn = document.getElementById("prof-clear-logo-btn");
    if (logoImg && logoFallback) {
      if (validLogoUrl) {
        logoImg.src = validLogoUrl;
        logoImg.classList.remove("hidden");
        logoFallback.classList.add("hidden");
      } else {
        logoImg.src = "";
        logoImg.classList.add("hidden");
        logoFallback.textContent = initials;
        logoFallback.classList.remove("hidden");
      }
    }
    if (clearLogoBtn) {
      clearLogoBtn.classList.toggle("hidden", !validLogoUrl);
    }

    // Overview Tab Showcase Card Live Sync
    const ovCoverImg = document.getElementById("overview-cover-img");
    if (ovCoverImg) {
      if (validCoverUrl) {
        ovCoverImg.src = validCoverUrl;
        ovCoverImg.classList.remove("hidden");
      } else {
        ovCoverImg.src = "";
        ovCoverImg.classList.add("hidden");
      }
    }
    const ovLogoImg = document.getElementById("overview-logo-img");
    const ovLogoFallback = document.getElementById("overview-logo-fallback");
    if (ovLogoImg && ovLogoFallback) {
      if (validLogoUrl) {
        ovLogoImg.src = validLogoUrl;
        ovLogoImg.classList.remove("hidden");
        ovLogoFallback.classList.add("hidden");
      } else {
        ovLogoImg.src = "";
        ovLogoImg.classList.add("hidden");
        ovLogoFallback.textContent = initials;
        ovLogoFallback.classList.remove("hidden");
      }
    }
    const ovShopName = document.getElementById("overview-shop-name");
    if (ovShopName) ovShopName.textContent = shop.shop_name || "Partner Shop";
    const ovShopMeta = document.getElementById("overview-shop-meta");
    if (ovShopMeta) {
      ovShopMeta.textContent = [
        shop.address,
        `${shop.municipality || "Mambajao"}, Camiguin`,
        shop.payout_number ? `💸 ${shop.payout_method || "GCash"}: ${shop.payout_number}` : "",
      ]
        .filter(Boolean)
        .join(" • ");
    }
    const ovPreviewLink = document.getElementById("overview-preview-shop-link");
    if (ovPreviewLink) ovPreviewLink.href = publicPath;

    if (shop.status === "pending") {
      statusBanner.className = "status-notice pending";
      statusBanner.textContent =
        "Pending Verification: Main Admin will review and approve your shop soon. You can already add your motorbikes now — they will go live automatically once approved.";
      statusBanner.classList.remove("hidden");
    } else if (shop.status === "suspended") {
      statusBanner.className = "status-notice suspended";
      statusBanner.textContent =
        "Account Suspended: Your listings are currently hidden. Please contact the platform admin.";
      statusBanner.classList.remove("hidden");
    } else {
      statusBanner.classList.add("hidden");
    }

    document.getElementById("prof-shop-name").value = shop.shop_name || "";
    document.getElementById("prof-owner-name").value = shop.owner_name || "";
    document.getElementById("prof-phone").value = shop.phone || "";
    document.getElementById("prof-whatsapp").value = shop.whatsapp_number || "";
    document.getElementById("prof-telegram-chat-id").value = shop.telegram_chat_id || "";
    document.getElementById("prof-alert-email-preview").value = shop.email || "";
    document.getElementById("prof-municipality").value = shop.municipality || "Mambajao";
    document.getElementById("prof-delivery-fee").value = shop.delivery_fee ?? 250;
    document.getElementById("prof-address").value = shop.address || "";
    document.getElementById("prof-description").value = shop.description || "";
    const profPayoutMethod = document.getElementById("prof-payout-method");
    if (profPayoutMethod) profPayoutMethod.value = shop.payout_method || "GCash";
    const profPayoutNumber = document.getElementById("prof-payout-number");
    if (profPayoutNumber) profPayoutNumber.value = shop.payout_number || shop.phone || "";
    const profPayoutAccountName = document.getElementById("prof-payout-account-name");
    if (profPayoutAccountName) profPayoutAccountName.value = shop.payout_account_name || shop.owner_name || "";
    const profContractEl = document.getElementById("prof-contract-terms");
    if (profContractEl) {
      profContractEl.value = shop.contract_terms || shop.default_contract_terms || "";
    }
  }

  function applyUrlOnboardingParams() {
    const params = new URLSearchParams(window.location.search);
    const tabParam = (params.get("tab") || "").toLowerCase();
    const hashParam = (window.location.hash || "").replace("#", "").toLowerCase();
    if (
      tabParam === "register" ||
      hashParam === "register" ||
      params.has("shop_name") ||
      params.has("bike_model")
    ) {
      switchAuthTab("register");
    }
    const shopName = params.get("shop_name");
    const ownerName = params.get("owner_name");
    const phone = params.get("phone");
    const municipality = params.get("municipality");
    const bikeModel = params.get("bike_model");

    if (shopName && document.getElementById("reg-shop-name")) {
      document.getElementById("reg-shop-name").value = shopName;
    }
    if (ownerName && document.getElementById("reg-owner-name")) {
      document.getElementById("reg-owner-name").value = ownerName;
      const payoutName = document.getElementById("reg-payout-account-name");
      if (payoutName && !payoutName.value) payoutName.value = ownerName;
    }
    if (phone && document.getElementById("reg-phone")) {
      document.getElementById("reg-phone").value = phone;
      const payoutNum = document.getElementById("reg-payout-number");
      if (payoutNum && !payoutNum.value) payoutNum.value = phone;
    }
    if (municipality && document.getElementById("reg-municipality")) {
      document.getElementById("reg-municipality").value = municipality;
    }
    if (bikeModel && document.getElementById("reg-bike-name")) {
      document.getElementById("reg-bike-name").value = bikeModel;
    }
  }

  async function checkSession() {
    applyUrlOnboardingParams();
    try {
      const data = await apiJson("/api/partner/me");
      if (data.authenticated && data.shop) {
        renderShopHeader(data.shop);
        showDashboard();
        await loadAllPartnerData();
      } else {
        showAuth();
      }
    } catch (_) {
      showAuth();
    }
  }

  async function loadAllPartnerData() {
    await Promise.all([loadDashboard(), loadBookings(), loadFleet()]);
  }

  async function loadDashboard() {
    const data = await apiJson("/api/partner/dashboard");
    renderShopHeader(data.shop);
    updatePlatformAlertStatus(data);
    const k = data.kpis;
    pendingBadge.textContent = k.pending_count;
    pendingBadge.classList.toggle("hidden", k.pending_count === 0);

    kpiGrid.innerHTML = `
      <div class="kpi-card">
        <div class="kpi-label">Pending Requests</div>
        <div class="kpi-value">${k.pending_count}</div>
        <div class="kpi-sub">${k.confirmed_count} confirmed &bull; ${k.active_count} active</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">My Fleet Units</div>
        <div class="kpi-value">${k.total_units}</div>
        <div class="kpi-sub">${k.available_models} of ${k.total_models} models ready</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Gross Bookings</div>
        <div class="kpi-value">${escapeHtml(formatMoney(k.gross_revenue))}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Total Earnings</div>
        <div class="kpi-value">${escapeHtml(formatMoney(k.net_payout))}</div>
        <div class="kpi-sub">This month: ${escapeHtml(formatMoney(k.month_payout))}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Customer Rating</div>
        <div class="kpi-value">&#11088; ${Number(k.rating_avg || 5.0).toFixed(1)}</div>
        <div class="kpi-sub">${k.review_count || 0} customer review(s)</div>
      </div>
    `;

    const upcoming = data.upcoming || [];
    if (!upcoming.length) {
      upcomingList.innerHTML = `<p class="text-muted">No upcoming or active rentals yet.</p>`;
    } else {
      upcomingList.innerHTML = upcoming
        .map(
          (b) => `
            <div class="upcoming-item">
              <div>
                <strong>${escapeHtml(b.bike_name)}</strong> &bull; ${escapeHtml(b.customer_name)}
                <div class="text-muted">${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)} (${escapeHtml(b.booking_code)}) &bull; Net: ${escapeHtml(formatMoney(b.shop_payout))}</div>
              </div>
              <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
            </div>
          `
        )
        .join("");
    }

    if (reviewsList) {
      const revs = data.reviews || [];
      if (!revs.length) {
        reviewsList.innerHTML = `<p class="text-muted" style="padding:12px;">No customer reviews yet. Reviews will show here as riders complete rentals.</p>`;
      } else {
        reviewsList.innerHTML = revs
          .map(
            (r) => `
              <div class="upcoming-item" style="display:block;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                  <strong>${escapeHtml(r.customer_name)}</strong>
                  <span style="color:#f59e0b;letter-spacing:1px;">${"★".repeat(Math.max(1, Math.min(5, r.rating || 5)))}</span>
                </div>
                <div class="text-muted" style="font-size:0.75rem;margin-bottom:4px;">
                  Rented ${escapeHtml(r.bike_name || "Motorbike")} &bull; ${escapeHtml(r.created_at || "")}
                </div>
                ${r.comment ? `<div style="font-size:0.85rem;color:#334155;font-style:italic;">"${escapeHtml(r.comment)}"</div>` : ""}
              </div>
            `
          )
          .join("");
      }
    }
  }

  async function loadBookings() {
    const params = new URLSearchParams({
      status: state.bookingStatus,
      q: state.bookingQuery,
    });
    const data = await apiJson(`/api/partner/bookings?${params.toString()}`);
    state.bookings = data.bookings || [];
    renderBookings();
  }

  function renderBookings() {
    if (!state.bookings.length) {
      bookingsList.innerHTML = `<div class="empty-state">No bookings match this filter yet.</div>`;
      return;
    }

    bookingsList.innerHTML = state.bookings
      .map((b) => {
        const actions = [];
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

        const payStatus = b.payment_status || "unpaid";
        const payLabel = window.MotoRide && window.MotoRide.paymentStatusLabel
          ? window.MotoRide.paymentStatusLabel(payStatus)
          : payStatus;
        const payChannelLabel = b.payment_channel === "maya"
          ? "Maya"
          : b.payment_channel === "gcash"
          ? "GCash"
          : "Pay at Shop";
        const hasOnlineFee = Number(b.reservation_fee || 0) > 0;
        const collectDue = b.balance_due !== undefined && b.balance_due !== null
          ? Number(b.balance_due)
          : Number(b.total_amount || 0);

        return `
          <div class="admin-booking-card">
            <div class="admin-booking-top">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="badge badge-dark" style="font-family:ui-monospace,monospace;letter-spacing:0.02em;font-size:0.84rem;padding:4px 10px;">${escapeHtml(b.booking_code)}</span>
                <strong style="font-size:1.02rem;color:var(--ink);">${escapeHtml(b.bike_name)}</strong>
                ${b.plate_number ? `<span class="spec-pill" style="padding:2px 8px;font-size:0.75rem;">Plate: ${escapeHtml(b.plate_number)}</span>` : ""}
              </div>
              <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
                ${(hasOnlineFee || payStatus !== "unpaid") ? `<span class="badge badge-${escapeHtml(payStatus)}">${escapeHtml(payLabel)}</span>` : ""}
                <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
              </div>
            </div>

            <div class="trip-details-grid">
              <div>
                <span class="trip-detail-label">Rider</span>
                <strong>${escapeHtml(b.customer_name)}</strong>
                <div class="text-muted" style="margin-top:2px;">${escapeHtml(b.customer_phone)}</div>
                ${b.customer_address ? `<div class="text-muted" style="font-size:0.8rem;margin-top:2px;">📍 ${escapeHtml(b.customer_address)}</div>` : ""}
              </div>
              <div>
                <span class="trip-detail-label">Dates</span>
                <strong>${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)}</strong>
                <div class="text-muted" style="margin-top:2px;">${b.rental_days}d &bull; ${escapeHtml(b.pickup_time)} &bull; <span style="font-weight:600;">${
                  b.pickup_method === "benoni_port"
                    ? "🚢 Benoni Port (+₱200)"
                    : b.pickup_method === "balbagon_port"
                    ? "⛴️ Balbagon Port (Free)"
                    : b.pickup_method === "airport"
                    ? "✈️ Camiguin Airport (Free)"
                    : (b.pickup_method === "around_mambajao" || b.pickup_method === "mambajao")
                    ? "🌴 Around Mambajao (Free)"
                    : b.pickup_method === "delivery"
                    ? "🏨 Hotel / Resort Delivery"
                    : "🏪 Shop Pickup"
                }</span></div>
              </div>
              <div>
                <span class="trip-detail-label">Total</span>
                <strong style="color:var(--ink);">${escapeHtml(formatMoney(b.total_amount))}</strong>
              </div>
              <div>
                <span class="trip-detail-label">Collect on Pickup</span>
                <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;">
                  <strong style="color:var(--primary-dark);">${escapeHtml(formatMoney(collectDue))}</strong>
                  ${balanceBadge}
                </div>
                <div class="text-muted" style="font-size:0.78rem;margin-top:2px;">${hasOnlineFee && payStatus !== "rejected" && payStatus !== "refunded" ? `Paid online: -${escapeHtml(formatMoney(b.reservation_fee))} (${escapeHtml(payChannelLabel)})` : "Full rental due"}</div>
              </div>
              <div>
                <span class="trip-detail-label">License #</span>
                <strong>${escapeHtml(b.license_number)}</strong>
              </div>
            </div>

            ${b.status !== "cancelled" ? `
              <div style="margin:10px 0 6px;display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
                <button type="button" class="btn btn-sm btn-primary" data-call-booking="${escapeHtml(b.booking_code)}" data-call-name="${escapeHtml(b.customer_name)}" data-call-tel="${escapeHtml(b.customer_phone)}">📞 Call Customer (in app)</button>
                <a href="/bookings/${encodeURIComponent(b.booking_code)}/contract" target="_blank" rel="noopener" class="btn btn-sm btn-outline">🖨️ Print Contract &amp; Receipt</a>
              </div>
            ` : ""}
            ${b.payment_reference ? `<div class="text-muted" style="margin-top:4px;font-size:0.84rem;"><strong>${escapeHtml(payChannelLabel)} Ref #:</strong> ${escapeHtml(b.payment_reference)}</div>` : ""}
            ${b.delivery_address ? `<div class="text-muted" style="margin-top:4px;font-size:0.84rem;"><strong>Delivery to:</strong> ${escapeHtml(b.delivery_address)}${b.google_maps_url ? ` &bull; <a href="${escapeHtml(b.google_maps_url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline" style="padding:2px 8px;font-size:0.75rem;display:inline-flex;align-items:center;gap:4px;">🗺️ Open GPS Navigation</a>` : ""}</div>` : ""}
            ${b.contract_agreed || b.signature_url || b.license_photo_url ? `
              <div class="contract-badge-row" style="margin-top:8px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:0.8rem;">
                <span class="badge badge-verified">&#128221; Digital Contract Signed</span>
                ${b.license_photo_url ? `<a href="${escapeHtml(b.license_photo_url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline" style="padding:3px 10px;font-size:0.76rem;">&#129674; Driver's License Photo</a>` : ""}
                ${b.signature_url ? `<a href="${escapeHtml(b.signature_url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline" style="padding:3px 10px;font-size:0.76rem;">&#9997;&#65039; Signature</a>` : ""}
              </div>
            ` : ""}
            ${b.notes ? `<div class="text-muted" style="margin-top:6px;font-size:0.84rem;background:#f8fafc;padding:6px 10px;border-radius:8px;border:1px solid #f1f5f9;"><strong>Rider note:</strong> ${escapeHtml(b.notes)}</div>` : ""}

            <div class="admin-booking-actions">
              ${actions.join("")}
              <div class="admin-note-inline">
                <input type="text" placeholder="Shop note (e.g., helmet size, unit plate)" value="${escapeHtml(b.admin_notes || "")}" data-note-input="${b.id}">
                <button type="button" class="btn btn-sm btn-outline" data-save-note="${b.id}">Save Note</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function loadFleet() {
    const data = await apiJson("/api/partner/bikes");
    state.bikes = data.bikes || [];
    renderFleet();
  }

  function renderFleet() {
    if (!state.bikes.length) {
      fleetList.innerHTML = `<div class="empty-state">No motorbikes added yet. Tap <strong>+ Add Motorbike</strong> to list your first unit!</div>`;
      return;
    }

    fleetList.innerHTML = state.bikes
      .map((bike) => {
        const badgeClass =
          bike.status === "available"
            ? "badge-available"
            : bike.status === "maintenance"
            ? "badge-maintenance"
            : "badge-completed";
        const isPlaceholder = isPlaceholderPartnerBikeImage(bike);
        const normalizedImg = normalizePartnerBikeImage(bike.image_url);
        const mediaHtml = isPlaceholder
          ? `<div class="bike-photo-placeholder" style="height:160px;">
               <img src="${escapeHtml(normalizedImg)}" alt="${escapeHtml(bike.name)}" class="bike-placeholder-svg">
               <span class="photo-coming-soon-text">Photo Coming Soon</span>
             </div>`
          : `<img src="${escapeHtml(normalizedImg)}" alt="${escapeHtml(bike.name)}">`;

        return `
          <div class="admin-bike-card">
            ${mediaHtml}
            <div class="admin-bike-body">
              <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
                <strong>${escapeHtml(bike.name)}</strong>
                <span class="badge ${badgeClass}">${escapeHtml(bike.status)}</span>
              </div>
              <div class="text-muted" style="margin:4px 0 8px;">
                ${escapeHtml(bike.category)} &bull; ${bike.engine_cc}cc &bull; ${escapeHtml(bike.transmission)}
              </div>
              <div style="font-size:0.88rem;margin-bottom:6px;">
                <strong>${escapeHtml(formatMoney(bike.daily_rate))}/day</strong>
              </div>
              <div class="text-muted">
                Units: ${bike.units_count} (Booked today: ${bike.booked_units}) ${bike.plate_number ? `&bull; ${escapeHtml(bike.plate_number)}` : ""}
              </div>
              ${renderAdminBikeScheduleSummary(bike)}
              <div class="admin-bike-actions">
                <button type="button" class="btn btn-sm btn-primary" data-manage-dates="${bike.id}" style="flex:1;">Manage Dates</button>
                <button type="button" class="btn btn-sm btn-outline" data-edit-bike="${bike.id}">Edit</button>
                <button type="button" class="btn btn-sm btn-danger" data-delete-bike="${bike.id}">Delete</button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  function openBikeEditor(bike) {
    bikeError.classList.add("hidden");
    bikeForm.reset();
    const previewWrap = document.getElementById("p-bike-photo-preview-wrap");
    if (previewWrap) previewWrap.classList.add("hidden");

    if (bike) {
      bikeModalTitle.textContent = `Edit ${bike.name}`;
      document.getElementById("p-bike-id").value = bike.id;
      document.getElementById("p-bike-name").value = bike.name;
      document.getElementById("p-bike-category").value = bike.category;
      document.getElementById("p-bike-cc").value = bike.engine_cc;
      document.getElementById("p-bike-transmission").value = bike.transmission;
      document.getElementById("p-bike-units").value = bike.units_count;
      document.getElementById("p-bike-status").value = bike.status;
      document.getElementById("p-bike-daily").value = bike.daily_rate;
      document.getElementById("p-bike-weekly").value = bike.weekly_rate;
      document.getElementById("p-bike-deposit").value = bike.deposit;
      document.getElementById("p-bike-plate").value = bike.plate_number || "";
      document.getElementById("p-bike-fuel").value = bike.fuel_type || "Gasoline";
      document.getElementById("p-bike-image-url").value = normalizePartnerBikeImage(bike.image_url);
      document.getElementById("p-bike-inclusions").value = bike.inclusions || "";
      document.getElementById("p-bike-description").value = bike.description || "";
    } else {
      bikeModalTitle.textContent = "Add Motorbike";
      document.getElementById("p-bike-id").value = "";
      document.getElementById("p-bike-image-url").value = DEFAULT_BIKE_PLACEHOLDER;
    }
    openModal("partner-bike-modal");
  }

  // Quick model chips & live camera photo preview in Register and Add Bike forms
  const regQuickChips = document.getElementById("reg-bike-quick-chips");
  if (regQuickChips) {
    regQuickChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".reg-bike-preset-chip");
      if (!chip) return;
      const model = chip.getAttribute("data-model") || "";
      const category = chip.getAttribute("data-category") || "Scooter";
      const rate = chip.getAttribute("data-rate") || "500";
      const nameInput = document.getElementById("reg-bike-name");
      const catInput = document.getElementById("reg-bike-category");
      const rateInput = document.getElementById("reg-bike-daily-rate");
      if (nameInput) nameInput.value = model;
      if (catInput) catInput.value = category;
      if (rateInput) rateInput.value = rate;
    });
  }

  const modalQuickChips = document.getElementById("p-bike-quick-chips");
  if (modalQuickChips) {
    modalQuickChips.addEventListener("click", (e) => {
      const chip = e.target.closest(".modal-bike-preset-chip");
      if (!chip) return;
      const model = chip.getAttribute("data-model") || "";
      const category = chip.getAttribute("data-category") || "Scooter";
      const cc = chip.getAttribute("data-cc") || "125";
      const rate = chip.getAttribute("data-rate") || "450";
      const nameInput = document.getElementById("p-bike-name");
      const catInput = document.getElementById("p-bike-category");
      const ccInput = document.getElementById("p-bike-cc");
      const rateInput = document.getElementById("p-bike-daily");
      if (nameInput) nameInput.value = model;
      if (catInput) catInput.value = category;
      if (ccInput) ccInput.value = cc;
      if (rateInput) rateInput.value = rate;
    });
  }

  const regBikePhotoInput = document.getElementById("reg-bike-photo");
  if (regBikePhotoInput) {
    regBikePhotoInput.addEventListener("change", () => {
      const file = regBikePhotoInput.files && regBikePhotoInput.files[0];
      const wrap = document.getElementById("reg-bike-photo-preview-wrap");
      const img = document.getElementById("reg-bike-photo-preview-img");
      if (file && wrap && img) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          img.src = ev.target.result;
          wrap.classList.remove("hidden");
        };
        reader.readAsDataURL(file);
      } else if (wrap) {
        wrap.classList.add("hidden");
      }
    });
  }

  const modalBikePhotoInput = document.getElementById("p-bike-image-file");
  if (modalBikePhotoInput) {
    modalBikePhotoInput.addEventListener("change", () => {
      const file = modalBikePhotoInput.files && modalBikePhotoInput.files[0];
      const wrap = document.getElementById("p-bike-photo-preview-wrap");
      const img = document.getElementById("p-bike-photo-preview-img");
      if (file && wrap && img) {
        const reader = new FileReader();
        reader.onload = (ev) => {
          img.src = ev.target.result;
          wrap.classList.remove("hidden");
        };
        reader.readAsDataURL(file);
      } else if (wrap) {
        wrap.classList.add("hidden");
      }
    });
  }

  const regPhoneInput = document.getElementById("reg-phone");
  const regPayoutNumberInput = document.getElementById("reg-payout-number");
  if (regPhoneInput && regPayoutNumberInput) {
    regPhoneInput.addEventListener("blur", () => {
      if (!regPayoutNumberInput.value.trim() && regPhoneInput.value.trim()) {
        regPayoutNumberInput.value = regPhoneInput.value.trim();
      }
    });
  }

  const regOwnerInput = document.getElementById("reg-owner-name");
  const regPayoutNameInput = document.getElementById("reg-payout-account-name");
  if (regOwnerInput && regPayoutNameInput) {
    regOwnerInput.addEventListener("blur", () => {
      if (!regPayoutNameInput.value.trim() && regOwnerInput.value.trim()) {
        regPayoutNameInput.value = regOwnerInput.value.trim();
      }
    });
  }

  // Event Listeners
  authTabs.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-partner-auth-tab]");
    if (!btn) return;
    switchAuthTab(btn.getAttribute("data-partner-auth-tab"));
  });

  loginForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    loginError.classList.add("hidden");
    try {
      const data = await apiJson("/api/partner/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: document.getElementById("partner-login-email").value.trim(),
          password: document.getElementById("partner-login-password").value,
        }),
      });
      loginForm.reset();
      renderShopHeader(data.shop);
      showDashboard();
      await loadAllPartnerData();
      showToast("Signed in!", "success");
    } catch (err) {
      loginError.textContent = err.message;
      loginError.classList.remove("hidden");
    }
  });

  registerForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    registerError.classList.add("hidden");
    try {
      const fd = new FormData(registerForm);
      const data = await apiJson("/api/partner/register", {
        method: "POST",
        body: fd,
      });
      registerForm.reset();
      const previewWrap = document.getElementById("reg-bike-photo-preview-wrap");
      if (previewWrap) previewWrap.classList.add("hidden");
      renderShopHeader(data.shop);
      showDashboard();
      await loadAllPartnerData();
      showToast(
        data.first_bike
          ? `Partner account & ${data.first_bike.name} created!`
          : "Partner account created! Add your motorbikes while awaiting approval.",
        "success"
      );
    } catch (err) {
      registerError.textContent = err.message;
      registerError.classList.remove("hidden");
    }
  });

  logoutBtn.addEventListener("click", async () => {
    await apiJson("/api/partner/logout", { method: "POST" });
    showAuth();
    showToast("Signed out.");
  });

  refreshBtn.addEventListener("click", async () => {
    try {
      await loadAllPartnerData();
      showToast("Refreshed.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  });

  tabsNav.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-partner-tab]");
    if (!btn) return;
    switchTab(btn.getAttribute("data-partner-tab"));
  });

  jumpBookingsBtn.addEventListener("click", () => switchTab("bookings"));

  statusPills.addEventListener("click", (event) => {
    const pill = event.target.closest("[data-status]");
    if (!pill) return;
    statusPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
    pill.classList.add("active");
    state.bookingStatus = pill.getAttribute("data-status");
    loadBookings();
  });

  let bookingTimer = null;
  bookingSearchInput.addEventListener("input", () => {
    clearTimeout(bookingTimer);
    bookingTimer = setTimeout(() => {
      state.bookingQuery = bookingSearchInput.value.trim();
      loadBookings();
    }, 220);
  });

  bookingsList.addEventListener("click", async (event) => {
    const balanceBtn = event.target.closest("[data-balance-paid]");
    if (balanceBtn) {
      const id = balanceBtn.getAttribute("data-id");
      const paid = balanceBtn.getAttribute("data-balance-paid") === "1";
      balanceBtn.disabled = true;
      try {
        await apiJson(`/api/partner/bookings/${id}`, {
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

    const actionBtn = event.target.closest("[data-booking-action]");
    if (actionBtn) {
      const id = actionBtn.getAttribute("data-id");
      const status = actionBtn.getAttribute("data-booking-action");
      actionBtn.disabled = true;
      try {
        await apiJson(`/api/partner/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status }),
        });
        await Promise.all([loadDashboard(), loadBookings(), loadFleet()]);
        showToast(`Booking marked ${status}.`, "success");
      } catch (err) {
        showToast(err.message, "error");
        actionBtn.disabled = false;
      }
      return;
    }

    const noteBtn = event.target.closest("[data-save-note]");
    if (noteBtn) {
      const id = noteBtn.getAttribute("data-save-note");
      const input = bookingsList.querySelector(`[data-note-input="${id}"]`);
      try {
        await apiJson(`/api/partner/bookings/${id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ admin_notes: input ? input.value : "" }),
        });
        showToast("Shop note saved.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    }
  });

  addBikeBtn.addEventListener("click", () => openBikeEditor(null));

  const scheduleCtrl = createBikeScheduleController({
    apiBase: "/api/partner/bikes",
    onUpdated: () => Promise.all([loadDashboard(), loadFleet()]),
  });

  fleetList.addEventListener("change", (event) => {
    const statusSel = event.target.closest("[data-quick-status]");
    if (!statusSel) return;
    const id = Number(statusSel.getAttribute("data-quick-status"));
    scheduleCtrl.quickChangeStatus(id, statusSel.value);
  });

  fleetList.addEventListener("click", async (event) => {
    const manageBtn = event.target.closest("[data-manage-dates]");
    if (manageBtn) {
      const id = Number(manageBtn.getAttribute("data-manage-dates"));
      scheduleCtrl.open(id);
      return;
    }

    const editBtn = event.target.closest("[data-edit-bike]");
    if (editBtn) {
      const id = Number(editBtn.getAttribute("data-edit-bike"));
      const bike = state.bikes.find((b) => b.id === id);
      if (bike) openBikeEditor(bike);
      return;
    }

    const delBtn = event.target.closest("[data-delete-bike]");
    if (delBtn) {
      const id = Number(delBtn.getAttribute("data-delete-bike"));
      if (!window.confirm("Delete this motorbike from your shop?")) return;
      try {
        await apiJson(`/api/partner/bikes/${id}`, { method: "DELETE" });
        await Promise.all([loadDashboard(), loadFleet()]);
        showToast("Motorbike deleted.", "success");
      } catch (err) {
        showToast(err.message, "error");
      }
    }
  });

  bikeForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    bikeError.classList.add("hidden");
    const id = document.getElementById("p-bike-id").value;
    const formData = new FormData(bikeForm);
    try {
      const url = id ? `/api/partner/bikes/${id}` : "/api/partner/bikes";
      const method = id ? "PUT" : "POST";
      await apiJson(url, { method, body: formData });
      closeModal("partner-bike-modal");
      await Promise.all([loadDashboard(), loadFleet()]);
      showToast(id ? "Motorbike updated!" : "Motorbike added!", "success");
    } catch (err) {
      bikeError.textContent = err.message;
      bikeError.classList.remove("hidden");
    }
  });

  function updatePlatformAlertStatus(platformFlags) {
    if (!platformFlags) return;
    if (typeof platformFlags.platform_telegram_enabled === "boolean") {
      state.platformTelegramEnabled = platformFlags.platform_telegram_enabled;
    }
    if (typeof platformFlags.platform_email_enabled === "boolean") {
      state.platformEmailEnabled = platformFlags.platform_email_enabled;
    }
    const pill = document.getElementById("partner-telegram-platform-status");
    if (!pill) return;
    pill.classList.remove("ready", "muted");
    if (state.platformTelegramEnabled) {
      pill.textContent = "Platform Telegram Bot Ready";
      pill.classList.add("ready");
    } else if (state.platformEmailEnabled) {
      pill.textContent = "Email Alerts Ready (Telegram Bot Not Set)";
      pill.classList.add("ready");
    } else {
      pill.textContent = "Ask Main Admin to Enable Telegram Bot / SMTP";
      pill.classList.add("muted");
    }
  }

  async function uploadPartnerBrandingMedia(formData, successMessage) {
    profileError.classList.add("hidden");
    try {
      const data = await apiJson("/api/partner/profile/media", {
        method: "POST",
        body: formData,
      });
      if (data && data.shop) {
        renderShopHeader(data.shop);
      }
      showToast(successMessage || "Shop photo updated!", "success");
    } catch (err) {
      profileError.textContent = err.message;
      profileError.classList.remove("hidden");
      showToast(err.message, "error");
    }
  }

  const profLogoFile = document.getElementById("prof-logo-file");
  if (profLogoFile) {
    profLogoFile.addEventListener("change", async () => {
      if (!profLogoFile.files || !profLogoFile.files[0]) return;
      const fd = new FormData();
      fd.append("logo_image", profLogoFile.files[0]);
      await uploadPartnerBrandingMedia(fd, "Profile picture uploaded!");
      profLogoFile.value = "";
    });
  }

  const profCoverFile = document.getElementById("prof-cover-file");
  if (profCoverFile) {
    profCoverFile.addEventListener("change", async () => {
      if (!profCoverFile.files || !profCoverFile.files[0]) return;
      const fd = new FormData();
      fd.append("cover_image", profCoverFile.files[0]);
      await uploadPartnerBrandingMedia(fd, "Cover photo uploaded!");
      profCoverFile.value = "";
    });
  }

  const clearLogoBtn = document.getElementById("prof-clear-logo-btn");
  if (clearLogoBtn) {
    clearLogoBtn.addEventListener("click", async () => {
      const fd = new FormData();
      fd.append("clear_logo", "1");
      await uploadPartnerBrandingMedia(fd, "Profile picture removed.");
    });
  }

  const clearCoverBtn = document.getElementById("prof-clear-cover-btn");
  if (clearCoverBtn) {
    clearCoverBtn.addEventListener("click", async () => {
      const fd = new FormData();
      fd.append("clear_cover", "1");
      await uploadPartnerBrandingMedia(fd, "Cover photo removed.");
    });
  }

  async function copyShopShareLink() {
    const url = getPartnerPublicUrl(state.shop);
    try {
      await navigator.clipboard.writeText(url);
      showToast("Shop profile link copied! Ready to paste on your Facebook Page.", "success");
    } catch (_) {
      showToast(`Shop Link: ${url}`, "success");
    }
  }

  const quickCopyLinkBtn = document.getElementById("partner-quick-copy-link-btn");
  if (quickCopyLinkBtn) {
    quickCopyLinkBtn.addEventListener("click", copyShopShareLink);
  }

  const overviewCopyLinkBtn = document.getElementById("overview-copy-link-btn");
  if (overviewCopyLinkBtn) {
    overviewCopyLinkBtn.addEventListener("click", copyShopShareLink);
  }

  const profCopyLinkBtn = document.getElementById("prof-copy-link-btn");
  if (profCopyLinkBtn) {
    profCopyLinkBtn.addEventListener("click", copyShopShareLink);
  }

  document.addEventListener("click", (e) => {
    const jumpBtn = e.target.closest("[data-jump-tab]");
    if (jumpBtn) {
      const tabName = jumpBtn.getAttribute("data-jump-tab");
      if (tabName) switchTab(tabName);
    }
  });

  const resetContractBtn = document.getElementById("prof-reset-contract-btn");
  if (resetContractBtn) {
    resetContractBtn.addEventListener("click", () => {
      const profContractEl = document.getElementById("prof-contract-terms");
      if (!profContractEl) return;
      const defaultTerms = (state.shop && state.shop.default_contract_terms) || "";
      if (defaultTerms) {
        profContractEl.value = defaultTerms;
        showToast("Default Rental Form Agreement template loaded. Click 'Save Shop Profile' to apply.", "success");
      }
    });
  }

  profileForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    profileError.classList.add("hidden");
    try {
      const fd = new FormData();
      fd.append("shop_name", document.getElementById("prof-shop-name").value.trim());
      fd.append("owner_name", document.getElementById("prof-owner-name").value.trim());
      fd.append("phone", document.getElementById("prof-phone").value.trim());
      fd.append("whatsapp_number", document.getElementById("prof-whatsapp").value.trim());
      fd.append("telegram_chat_id", document.getElementById("prof-telegram-chat-id").value.trim());
      fd.append("municipality", document.getElementById("prof-municipality").value);
      fd.append("delivery_fee", document.getElementById("prof-delivery-fee").value);
      fd.append("address", document.getElementById("prof-address").value.trim());
      fd.append("description", document.getElementById("prof-description").value.trim());
      const profPayoutMethod = document.getElementById("prof-payout-method");
      if (profPayoutMethod) fd.append("payout_method", profPayoutMethod.value);
      const profPayoutNumber = document.getElementById("prof-payout-number");
      if (profPayoutNumber) fd.append("payout_number", profPayoutNumber.value.trim());
      const profPayoutAccountName = document.getElementById("prof-payout-account-name");
      if (profPayoutAccountName) fd.append("payout_account_name", profPayoutAccountName.value.trim());
      const profContractEl = document.getElementById("prof-contract-terms");
      if (profContractEl) {
        fd.append("contract_terms", profContractEl.value.trim());
      }
      fd.append("current_password", document.getElementById("prof-current-password").value);
      fd.append("new_password", document.getElementById("prof-new-password").value);
      if (profLogoFile && profLogoFile.files && profLogoFile.files[0]) {
        fd.append("logo_image", profLogoFile.files[0]);
      }
      if (profCoverFile && profCoverFile.files && profCoverFile.files[0]) {
        fd.append("cover_image", profCoverFile.files[0]);
      }
      const data = await apiJson("/api/partner/profile", {
        method: "PUT",
        body: fd,
      });
      renderShopHeader(data.shop);
      updatePlatformAlertStatus(data);
      document.getElementById("prof-current-password").value = "";
      document.getElementById("prof-new-password").value = "";
      if (profLogoFile) profLogoFile.value = "";
      if (profCoverFile) profCoverFile.value = "";
      showToast("Shop profile saved!", "success");
    } catch (err) {
      profileError.textContent = err.message;
      profileError.classList.remove("hidden");
    }
  });

  const testPartnerAlertBtn = document.getElementById("test-partner-alert-btn");
  if (testPartnerAlertBtn) {
    testPartnerAlertBtn.addEventListener("click", async () => {
      const resultEl = document.getElementById("partner-alert-test-result");
      testPartnerAlertBtn.disabled = true;
      testPartnerAlertBtn.textContent = "Sending...";
      if (resultEl) resultEl.classList.add("hidden");
      try {
        const res = await fetch("/api/partner/profile/test-alert", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            telegram_chat_id: document.getElementById("prof-telegram-chat-id").value.trim(),
          }),
        });
        const data = await res.json().catch(() => ({}));
        if (res.status === 401) {
          showAuth();
          return;
        }
        const results = data.results || {};
        const parts = Object.entries(results).map(([channel, info]) => {
          return `${channel.toUpperCase()}: ${info.ok ? "OK" : "Failed"} — ${info.detail || ""}`;
        });
        if (resultEl) {
          resultEl.textContent = parts.length ? parts.join(" | ") : data.error || "Test failed.";
          resultEl.classList.remove("hidden", "ok", "err");
          resultEl.classList.add(data.ok ? "ok" : "err");
        }
        showToast(data.ok ? "Test alert sent!" : "Test alert could not be delivered.", data.ok ? "success" : "error");
      } catch (err) {
        if (resultEl) {
          resultEl.textContent = err.message;
          resultEl.classList.remove("hidden", "ok");
          resultEl.classList.add("err");
        }
      } finally {
        testPartnerAlertBtn.disabled = false;
        testPartnerAlertBtn.textContent = "Send Test Alert to My CP";
      }
    });
  }

  checkSession();
})();
