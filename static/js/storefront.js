(function () {
  "use strict";

  const {
    escapeHtml,
    formatMoney,
    formatShortDate,
    formatDateRangeShort,
    formatBookedRangesLabel,
    renderAvailabilityCalendarHtml,
    paymentStatusLabel,
    showToast,
    openModal,
    closeModal,
    saveRecentTrip,
    shop,
  } = window.MotoRide;

  const fleetGrid = document.getElementById("fleet-grid");
  const fleetDateSummary = document.getElementById("fleet-date-summary");
  const searchForm = document.getElementById("availability-search-form");
  const searchPickupInput = document.getElementById("search-pickup-date");
  const searchReturnInput = document.getElementById("search-return-date");
  const searchMunicipality = document.getElementById("search-municipality");
  const searchTransmission = document.getElementById("search-transmission");
  const filterShop = document.getElementById("filter-shop");
  const categoryPills = document.getElementById("category-pills");
  const filterSearchQ = document.getElementById("filter-search-q");
  const filterSort = document.getElementById("filter-sort");
  const filterAvailableOnly = document.getElementById("filter-available-only");
  const partnerShopsStripWrap = document.getElementById("partner-shops-strip-wrap");
  const partnerShopsStrip = document.getElementById("partner-shops-strip");
  const partnerShopsResetBtn = document.getElementById("partner-shops-reset-btn");
  const shopProfileBanner = document.getElementById("shop-profile-banner");

  const initialFeaturedShop =
    typeof window.INITIAL_FEATURED_SHOP === "object" && window.INITIAL_FEATURED_SHOP
      ? window.INITIAL_FEATURED_SHOP
      : null;
  const initialBootstrap =
    typeof window.INITIAL_STOREFRONT_BOOTSTRAP === "object" && window.INITIAL_STOREFRONT_BOOTSTRAP
      ? window.INITIAL_STOREFRONT_BOOTSTRAP
      : null;

  // Booking Modal Elements
  const bookingForm = document.getElementById("booking-form");
  const bookingBikeId = document.getElementById("booking-bike-id");
  const bookingPickup = document.getElementById("booking-pickup-date");
  const bookingReturn = document.getElementById("booking-return-date");
  const bookingPickupMethod = document.getElementById("booking-pickup-method");
  const deliveryOptionLabel = document.getElementById("delivery-option-label");
  const deliveryAddressGroup = document.getElementById("delivery-address-group");
  const deliveryAddressInput = document.getElementById("booking-delivery-address");
  const extraHelmetCheckbox = document.getElementById("booking-extra-helmet");
  const topBoxCheckbox = document.getElementById("booking-top-box");
  const quoteAvailability = document.getElementById("quote-availability");
  const quoteLines = document.getElementById("quote-lines");
  const modalAvailCalendar = document.getElementById("modal-availability-calendar");
  const modalNextAvailableBtn = document.getElementById("modal-next-available-btn");
  const bookingFormError = document.getElementById("booking-form-error");
  const bookingSubmitBtn = document.getElementById("booking-submit-btn");
  const paymentQrSection = document.getElementById("payment-qr-section");
  const paymentModePill = document.getElementById("payment-mode-pill");
  const paymentFeeBadge = document.getElementById("payment-fee-badge");
  const paymentQrBox = document.getElementById("payment-qr-box");
  const paymentQrImg = document.getElementById("payment-qr-img");
  const paymentInstructionsText = document.getElementById("payment-instructions-text");
  const paymentGcashRow = document.getElementById("payment-gcash-row");
  const paymentGcashNumber = document.getElementById("payment-gcash-number");
  const paymentGcashName = document.getElementById("payment-gcash-name");
  const paymentMayaRow = document.getElementById("payment-maya-row");
  const paymentMayaNumber = document.getElementById("payment-maya-number");
  const copyGcashBtn = document.getElementById("copy-gcash-btn");
  const copyMayaBtn = document.getElementById("copy-maya-btn");
  const channelGcashWrap = document.getElementById("channel-gcash-wrap");
  const channelMayaWrap = document.getElementById("channel-maya-wrap");
  const channelPaymongoWrap = document.getElementById("channel-paymongo-wrap");
  const channelShopWrap = document.getElementById("channel-shop-wrap");
  const paymongoInfoBox = document.getElementById("paymongo-info-box");
  const paymentProofFields = document.getElementById("payment-proof-fields");
  const bookingPaymentRef = document.getElementById("booking-payment-reference");
  const bookingPaymentProof = document.getElementById("booking-payment-proof");

  const state = {
    category: "All",
    transmission: "All",
    municipality: "All",
    shopId: initialFeaturedShop && initialFeaturedShop.id ? String(initialFeaturedShop.id) : "",
    featuredShop: initialFeaturedShop,
    q: "",
    sort: "featured",
    availableOnly: false,
    pickupDate: "",
    returnDate: "",
    bikes: [],
    shops: [],
    latestQuote: null,
    currentBike: null,
    suggestedOpenWindow: null,
  };

  function getSelectedPaymentChannel() {
    if (!bookingForm) return "pay_at_shop";
    const checked = bookingForm.querySelector('input[name="payment_channel"]:checked');
    return checked ? checked.value : "pay_at_shop";
  }

  function selectPaymentChannel(channel) {
    if (!bookingForm) return;
    const radio = bookingForm.querySelector(`input[name="payment_channel"][value="${channel}"]`);
    if (radio) radio.checked = true;
  }

  function syncPaymentChannelUi(resetDefault) {
    if (!paymentQrSection) return;
    const wasHidden = paymentQrSection.classList.contains("hidden");
    const q = state.latestQuote;
    const qrUrl = (shop.gcash_qr_url || "").trim();
    const gcashNum = (shop.gcash_number || "").trim();
    const gcashName = (shop.gcash_account_name || "").trim();
    const mayaNum = (shop.maya_number || "").trim();
    const hasGcash = Boolean(qrUrl || gcashNum);
    const hasMaya = Boolean(mayaNum);
    const mode = String((q && q.reservation_mode) || shop.reservation_mode || "required").toLowerCase();
    const percent = Number(
      q && q.reservation_percent !== undefined ? q.reservation_percent : shop.reservation_percent || 30
    );
    const isConfigured = Boolean((q && q.reservation_configured) || hasGcash || hasMaya);
    const fallbackDaily = state.currentBike ? Number(state.currentBike.daily_rate || 0) : 0;
    const isFlat500 = Boolean(q && Number(q.rental_days || 1) >= 3);
    const feeAmount =
      q && Number(q.reservation_fee || 0) > 0
        ? Number(q.reservation_fee)
        : Math.round(fallbackDaily * (percent / 100) * 100) / 100;
    const active = Boolean(mode !== "off" && isConfigured && feeAmount > 0);
    paymentQrSection.classList.toggle("hidden", !active);
    if (!active) {
      selectPaymentChannel("pay_at_shop");
      if (paymentProofFields) paymentProofFields.classList.add("hidden");
      if (paymongoInfoBox) paymongoInfoBox.classList.add("hidden");
      return;
    }

    const isReq = mode === "required";

    if (paymentModePill) {
      paymentModePill.textContent = isReq ? "Required" : "Optional";
      paymentModePill.className = isReq ? "status-pill-inline ready" : "status-pill-inline muted";
    }
    if (paymentFeeBadge) {
      paymentFeeBadge.textContent = isFlat500
        ? `Down Payment (3+ Days): ${formatMoney(feeAmount)}`
        : `Down Payment (${percent}%): ${formatMoney(feeAmount)}`;
    }
    if (paymentInstructionsText) {
      paymentInstructionsText.textContent =
        (shop.payment_instructions || "").trim() ||
        "Scan the QR code or send the down payment below, then enter your Reference No. before submitting.";
    }

    if (channelGcashWrap) channelGcashWrap.classList.toggle("hidden", !hasGcash);
    if (channelMayaWrap) channelMayaWrap.classList.toggle("hidden", !hasMaya);
    if (channelShopWrap) channelShopWrap.classList.toggle("hidden", isReq);

    const defaultChannel = hasGcash ? "gcash" : hasMaya ? "maya" : "pay_at_shop";
    let current = getSelectedPaymentChannel();
    if (resetDefault || wasHidden || current === "paymongo") {
      current = defaultChannel;
      selectPaymentChannel(current);
    } else if (isReq && current === "pay_at_shop") {
      current = defaultChannel;
      selectPaymentChannel(current);
    } else if (current === "gcash" && !hasGcash) {
      current = hasMaya ? "maya" : "pay_at_shop";
      selectPaymentChannel(current);
    } else if (current === "maya" && !hasMaya) {
      current = hasGcash ? "gcash" : "pay_at_shop";
      selectPaymentChannel(current);
    }

    // Toggle sub-sections depending on whether Manual GCash/Maya or Shop pickup is active
    if (current === "gcash") {
      if (paymongoInfoBox) paymongoInfoBox.classList.add("hidden");
      if (paymentProofFields) paymentProofFields.classList.remove("hidden");
      if (paymentQrBox && paymentQrImg) {
        if (qrUrl) {
          paymentQrImg.src = qrUrl;
          paymentQrBox.classList.remove("hidden");
        } else {
          paymentQrBox.classList.add("hidden");
        }
      }
      if (paymentGcashRow && paymentGcashNumber) {
        if (gcashNum) {
          paymentGcashNumber.textContent = gcashNum;
          if (paymentGcashName) {
            paymentGcashName.textContent = gcashName ? `Account Name: ${gcashName}` : "";
          }
          paymentGcashRow.classList.remove("hidden");
        } else {
          paymentGcashRow.classList.add("hidden");
        }
      }
      if (paymentMayaRow) paymentMayaRow.classList.add("hidden");
    } else if (current === "maya") {
      if (paymongoInfoBox) paymongoInfoBox.classList.add("hidden");
      if (paymentProofFields) paymentProofFields.classList.remove("hidden");
      if (paymentQrBox) paymentQrBox.classList.add("hidden");
      if (paymentGcashRow) paymentGcashRow.classList.add("hidden");
      if (paymentMayaRow && paymentMayaNumber) {
        if (mayaNum) {
          paymentMayaNumber.textContent = mayaNum;
          paymentMayaRow.classList.remove("hidden");
        } else {
          paymentMayaRow.classList.add("hidden");
        }
      }
    } else {
      // pay_at_shop
      if (paymongoInfoBox) paymongoInfoBox.classList.add("hidden");
      if (paymentProofFields) paymentProofFields.classList.add("hidden");
      if (paymentQrBox) paymentQrBox.classList.add("hidden");
      if (paymentGcashRow) paymentGcashRow.classList.add("hidden");
      if (paymentMayaRow) paymentMayaRow.classList.add("hidden");
    }
  }

  function toIsoLocal(dt) {
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const d = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function syncDateWrap(input) {
    if (!input) return;
    const wrap = input.closest(".date-input-wrap");
    if (wrap) {
      wrap.classList.toggle("is-empty", !input.value);
    }
  }

  function syncReturnDateUi() {
    syncDateWrap(searchReturnInput);
    syncDateWrap(bookingReturn);
  }

  function bindDatePickerPlaceholder(input) {
    if (!input) return;
    syncDateWrap(input);
    input.addEventListener("input", () => syncDateWrap(input));
    input.addEventListener("change", () => syncDateWrap(input));
    input.addEventListener("click", (event) => {
      if (typeof input.showPicker !== "function") return;
      const rect = input.getBoundingClientRect();
      // Preserve native browser handling when user clicks the right-side calendar icon directly
      if (event.clientX && rect.right - event.clientX <= 34) return;
      try {
        input.showPicker();
      } catch (_) {
        // Fallback silently if browser blocks programmatic showPicker
      }
    });
  }

  function initDefaultDates() {
    const todayStr = toIsoLocal(new Date());

    state.pickupDate = todayStr;
    state.returnDate = "";

    [searchPickupInput, bookingPickup].forEach((el) => {
      if (el) {
        el.min = todayStr;
        el.value = todayStr;
      }
    });
    [searchReturnInput, bookingReturn].forEach((el) => {
      if (el) {
        el.min = todayStr;
        el.value = "";
      }
    });
    syncReturnDateUi();
  }

  function calcDaysDiff(pStr, rStr) {
    if (!pStr || !rStr) return 1;
    const p = new Date(`${pStr}T00:00:00`);
    const r = new Date(`${rStr}T00:00:00`);
    const diff = Math.round((r - p) / 86400000);
    return Math.max(1, diff);
  }

  function addDaysIso(isoStr, days) {
    if (!isoStr || !/^\d{4}-\d{2}-\d{2}$/.test(isoStr)) return "";
    const [y, m, d] = isoStr.split("-").map(Number);
    return toIsoLocal(new Date(y, m - 1, d + days));
  }

  function hasBookedDayInRange(bike, startIso, endIso) {
    const ranges = (bike && bike.booked_ranges) || [];
    const end = endIso || startIso;
    return ranges.some((r) => r.pickup_date <= end && r.return_date >= startIso);
  }

  function isDateFullyBooked(bike, isoStr) {
    if (!bike || !isoStr) return false;
    if (bike.status !== "available") return true;
    const calDay = (bike.availability_calendar || []).find((d) => d.date === isoStr);
    if (calDay) return calDay.status === "booked";
    return hasBookedDayInRange(bike, isoStr, isoStr);
  }

  function findNextAvailableRange(bike, startIso, returnIso) {
    if (!bike || bike.status !== "available") return null;
    const todayIso = toIsoLocal(new Date());
    const baseStart = startIso && startIso >= todayIso ? startIso : todayIso;
    const hasRet = Boolean(returnIso && returnIso >= baseStart);
    const spanDays = hasRet
      ? Math.max(0, Math.round((new Date(`${returnIso}T00:00:00`) - new Date(`${baseStart}T00:00:00`)) / 86400000))
      : 0;
    const startOffset = startIso && startIso >= todayIso ? 1 : 0;
    for (let offset = startOffset; offset <= 120; offset += 1) {
      const candPickup = addDaysIso(baseStart, offset);
      const candReturn = hasRet ? addDaysIso(candPickup, spanDays) : candPickup;
      if (!hasBookedDayInRange(bike, candPickup, candReturn)) {
        return {
          pickup_date: candPickup,
          return_date: hasRet ? candReturn : "",
        };
      }
    }
    return null;
  }

  function renderModalCalendar() {
    if (!modalAvailCalendar || !state.currentBike) return;
    modalAvailCalendar.innerHTML = renderAvailabilityCalendarHtml(
      state.currentBike.availability_calendar || [],
      {
        selectedPickup: bookingPickup ? bookingPickup.value : "",
        selectedReturn: bookingReturn ? bookingReturn.value : "",
        interactive: true,
      }
    );
  }

  function syncNextAvailableBtn(suggestion) {
    if (!modalNextAvailableBtn) return;
    state.suggestedOpenWindow = suggestion || null;
    if (!suggestion || !suggestion.pickup_date) {
      modalNextAvailableBtn.classList.add("hidden");
      return;
    }
    const label = suggestion.return_date
      ? formatDateRangeShort(suggestion.pickup_date, suggestion.return_date)
      : formatShortDate(suggestion.pickup_date);
    modalNextAvailableBtn.textContent = `Use Next Open: ${label}`;
    modalNextAvailableBtn.classList.remove("hidden");
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

  function getActiveShopObject() {
    if (!state.shopId) return null;
    const match = state.shops.find((s) => String(s.id) === String(state.shopId));
    if (match) return match;
    if (state.featuredShop && String(state.featuredShop.id) === String(state.shopId)) {
      return state.featuredShop;
    }
    return null;
  }

  function getShopShareUrl(shopObj) {
    if (!shopObj) return window.location.origin;
    const slug = shopObj.slug || shopObj.id;
    return `${window.location.origin}/shop/${encodeURIComponent(slug)}`;
  }

  const DEFAULT_BIKE_PLACEHOLDER = "/static/icons/icon.svg";

  function normalizeBikeImageUrl(rawUrl) {
    const s = String(rawUrl || "").trim();
    if (!s || s.startsWith("/static/images/")) return DEFAULT_BIKE_PLACEHOLDER;
    return s;
  }

  function isPlaceholderBikeImage(rawUrl) {
    return normalizeBikeImageUrl(rawUrl) === DEFAULT_BIKE_PLACEHOLDER;
  }

  function renderPartnerShopsStrip() {
    if (!partnerShopsStripWrap || !partnerShopsStrip) return;
    if (!state.shops || !state.shops.length) {
      partnerShopsStripWrap.classList.add("hidden");
      return;
    }
    partnerShopsStripWrap.classList.remove("hidden");
    if (partnerShopsResetBtn) {
      partnerShopsResetBtn.classList.toggle("hidden", !state.shopId);
    }

    partnerShopsStrip.innerHTML = state.shops
      .map((s) => {
        const isActive = String(state.shopId) === String(s.id);
        const avatarHtml = s.logo_url
          ? `<img src="${escapeHtml(s.logo_url)}" alt="${escapeHtml(s.shop_name)}" class="shop-strip-avatar-img" loading="lazy">`
          : `<span class="shop-strip-avatar-fallback">${escapeHtml(getShopInitials(s.shop_name))}</span>`;
        const coverImgUrl = (s.cover_url && !String(s.cover_url).startsWith("/static/images/")) ? s.cover_url : "";
        const coverStyle = coverImgUrl
          ? `style="background-image: linear-gradient(180deg, rgba(15,23,42,0.28), rgba(15,23,42,0.78)), url('${escapeHtml(coverImgUrl)}');"`
          : "";
        const unitCount = Number(s.bike_count || 0);
        return `
          <button
            type="button"
            role="listitem"
            class="shop-strip-card ${isActive ? "active" : ""}"
            data-select-shop="${s.id}"
            aria-pressed="${isActive ? "true" : "false"}"
          >
            <div class="shop-strip-cover" ${coverStyle}>
              <span class="shop-strip-hub-tag verified">Verified</span>
            </div>
            <div class="shop-strip-body">
              <div class="shop-strip-avatar">${avatarHtml}</div>
              <div class="shop-strip-info">
                <strong class="shop-strip-name">${escapeHtml(s.shop_name)}</strong>
                <span class="shop-strip-meta">${escapeHtml(s.municipality || "Camiguin")} &bull; ${unitCount} model(s)</span>
                <span style="font-size:0.75rem;color:#f59e0b;display:inline-flex;align-items:center;gap:3px;margin-top:2px;">★ <strong style="color:#0f172a;">${Number(s.rating_avg || 5.0).toFixed(1)}</strong> <small style="color:#64748b;">(${s.review_count || 0})</small></span>
              </div>
            </div>
          </button>
        `;
      })
      .join("");
  }

  function renderShopProfileBanner() {
    if (!shopProfileBanner) return;
    const activeShop = getActiveShopObject();
    if (!activeShop) {
      shopProfileBanner.classList.add("hidden");
      shopProfileBanner.innerHTML = "";
      return;
    }

    const shareUrl = getShopShareUrl(activeShop);
    const fbShareHref = `https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(shareUrl)}`;
    const coverImg = (activeShop.cover_url && !String(activeShop.cover_url).startsWith("/static/images/"))
      ? activeShop.cover_url
      : "";
    const avatarHtml = activeShop.logo_url
      ? `<img src="${escapeHtml(activeShop.logo_url)}" alt="${escapeHtml(activeShop.shop_name)}" class="shop-banner-avatar-img">`
      : `<div class="shop-banner-avatar-fallback">${escapeHtml(getShopInitials(activeShop.shop_name))}</div>`;

    const waRaw = String(activeShop.whatsapp_number || activeShop.phone || "").replace(/\D+/g, "");
    const waDigits = waRaw.startsWith("0") ? `63${waRaw.slice(1)}` : waRaw;
    const waHref = waDigits
      ? `https://wa.me/${waDigits}?text=${encodeURIComponent(`Hi ${activeShop.shop_name}! I saw your shop profile on ${shop.shop_name} (${shareUrl}) and would like to inquire about motorbike rental.`)}`
      : "";

    const locParts = [activeShop.address, activeShop.municipality, "Camiguin"].filter(Boolean).join(" • ");
    const desc =
      activeShop.description ||
      `Verified local motorbike rental partner in ${activeShop.municipality || "Camiguin"}, Camiguin Island. Browse live availability and book directly online.`;

    shopProfileBanner.classList.remove("hidden");
    shopProfileBanner.innerHTML = `
      <div class="shop-banner-cover">
        ${coverImg ? `<img src="${escapeHtml(coverImg)}" alt="${escapeHtml(activeShop.shop_name)} Cover Photo" class="shop-banner-cover-img">` : ""}
        <div class="shop-banner-cover-overlay"></div>
        <div class="shop-banner-top-bar">
          <span class="shop-banner-verified-pill">
            &#10003; Verified Camiguin Partner Shop
          </span>
          <button type="button" class="btn btn-sm shop-banner-reset-btn" data-clear-shop-filter="1">
            &larr; All Island Shops
          </button>
        </div>
      </div>
      <div class="shop-banner-content">
        <div class="shop-banner-identity">
          <div class="shop-banner-avatar-wrap">
            ${avatarHtml}
          </div>
          <div class="shop-banner-title-block">
            <h2 class="shop-banner-title">${escapeHtml(activeShop.shop_name)}</h2>
            <p class="shop-banner-location">${escapeHtml(locParts)}</p>
            <div class="shop-banner-chips">
              ${activeShop.phone ? `<span class="shop-banner-chip">&#128222; ${escapeHtml(activeShop.phone)}</span>` : ""}
              <span class="shop-banner-chip" title="Average tourist rating">&#11088; ${Number(activeShop.rating_avg || 5.0).toFixed(1)} (${Number(activeShop.review_count || 0)} review${activeShop.review_count === 1 ? "" : "s"})</span>
              <span class="shop-banner-chip">&#128666; Delivery: ${escapeHtml(formatMoney(activeShop.delivery_fee || 0))}</span>
              ${activeShop.bike_count !== undefined ? `<span class="shop-banner-chip">&#127949; ${Number(activeShop.bike_count)} Motorbike Model(s)</span>` : ""}
            </div>
          </div>
        </div>
        <p class="shop-banner-desc">${escapeHtml(desc)}</p>
        <div class="shop-banner-share-bar">
          <div class="shop-banner-link-box">
            <span class="shop-banner-link-label">Shop Profile Link:</span>
            <code class="shop-banner-link-code">${escapeHtml(shareUrl)}</code>
          </div>
          <div class="shop-banner-actions">
            <button type="button" class="btn btn-sm btn-outline" data-copy-shop-link="${escapeHtml(shareUrl)}">
              Copy Link for FB Page
            </button>
            <a href="${escapeHtml(fbShareHref)}" target="_blank" rel="noopener" class="btn btn-sm btn-fb-share">
              Share on Facebook
            </a>
            ${
              waHref
                ? `<a href="${escapeHtml(waHref)}" target="_blank" rel="noopener" class="btn btn-sm btn-primary">WhatsApp Shop</a>`
                : ""
            }
          </div>
        </div>
        ${
          activeShop.reviews && activeShop.reviews.length
            ? `
          <div class="shop-banner-reviews" style="margin-top:16px;padding-top:16px;border-top:1px solid rgba(0,0,0,0.08);">
            <div style="font-weight:700;font-size:0.95rem;margin-bottom:8px;color:#0f2b3a;">
              ⭐ Customer Reviews (${activeShop.reviews.length})
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:10px;">
              ${activeShop.reviews
                .slice(0, 6)
                .map(
                  (r) => `
                <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:12px;padding:10px 12px;font-size:0.85rem;">
                  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                    <strong style="color:#0f2b3a;">${escapeHtml(r.customer_name)}</strong>
                    <span style="color:#f59e0b;letter-spacing:1px;">${"★".repeat(Math.max(1, Math.min(5, r.rating || 5)))}</span>
                  </div>
                  <div class="text-muted" style="font-size:0.75rem;margin-bottom:4px;">Rented ${escapeHtml(r.bike_name || "Motorbike")}</div>
                  ${r.comment ? `<p style="margin:0;color:#334155;font-style:italic;">"${escapeHtml(r.comment)}"</p>` : ""}
                </div>
              `
                )
                .join("")}
            </div>
          </div>
        `
            : ""
        }
      </div>
    `;
  }

  function selectShopFilter(shopId, options) {
    const opts = options || {};
    state.shopId = shopId ? String(shopId) : "";
    if (filterShop) {
      filterShop.value = state.shopId;
    }
    const activeShop = getActiveShopObject();
    if (activeShop) {
      state.featuredShop = activeShop;
    }
    if (opts.updateHistory !== false && window.history && typeof window.history.replaceState === "function") {
      const nextUrl = activeShop && activeShop.slug ? `/shop/${encodeURIComponent(activeShop.slug)}` : "/";
      try {
        window.history.replaceState({ shopId: state.shopId }, "", nextUrl);
      } catch (_) {
        // Ignore history state errors
      }
    }
    renderPartnerShopsStrip();
    renderShopProfileBanner();
    loadFleet();
    if (opts.scrollToBanner && shopProfileBanner && !shopProfileBanner.classList.contains("hidden")) {
      shopProfileBanner.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }

  function populateShopFilterOptions() {
    if (!filterShop) return;
    if (
      state.featuredShop &&
      !state.shops.some((s) => String(s.id) === String(state.featuredShop.id))
    ) {
      state.shops.unshift(state.featuredShop);
    }
    const targetVal = state.shopId || filterShop.value || "";
    filterShop.innerHTML =
      `<option value="">All Rental Shops (${state.shops.length})</option>` +
      state.shops
        .map(
          (s) =>
            `<option value="${s.id}">${escapeHtml(s.shop_name)} (${escapeHtml(s.municipality)})</option>`
        )
        .join("");
    filterShop.value = targetVal;
    renderPartnerShopsStrip();
    renderShopProfileBanner();
  }

  async function loadPublicShops() {
    if (!filterShop) return;
    try {
      const res = await fetch("/api/shops");
      const data = await res.json();
      if (!res.ok) return;
      state.shops = data.shops || [];
      populateShopFilterOptions();
    } catch (_) {
      // Keep default option offline
      renderShopProfileBanner();
    }
  }

  async function loadFleet() {
    const todayStr = toIsoLocal(new Date());
    const pickupDate = state.pickupDate || todayStr;
    const params = new URLSearchParams({
      category: state.category,
      transmission: state.transmission,
      municipality: state.municipality,
      q: state.q,
      sort: state.sort,
      pickup_date: pickupDate,
      available_only: state.availableOnly ? "1" : "0",
    });
    if (state.returnDate) {
      params.set("return_date", state.returnDate);
    }
    if (state.shopId) {
      params.set("shop_id", state.shopId);
    }

    try {
      const res = await fetch(`/api/bikes?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Failed to load motorbikes.");
      }
      state.bikes = data.bikes || [];
      renderFleet();
    } catch (err) {
      fleetGrid.innerHTML = `<div class="empty-state">${escapeHtml(err.message)}</div>`;
    }
  }

  function renderFleet() {
    if (fleetDateSummary) {
      if (!state.returnDate) {
        const pickupLabel = state.pickupDate || toIsoLocal(new Date());
        fleetDateSummary.textContent =
          `${state.bikes.length} model(s) starting ${pickupLabel} — select a return date for trip availability`;
      } else {
        const days = calcDaysDiff(state.pickupDate, state.returnDate);
        const dayWord = days === 1 ? "day" : "days";
        fleetDateSummary.textContent =
          `${state.bikes.length} model(s) for ${state.pickupDate} to ${state.returnDate} (${days} ${dayWord})`;
      }
    }

    if (!state.bikes.length) {
      fleetGrid.innerHTML = `
        <div class="empty-state">
          <strong>No motorbikes matched your filters.</strong>
          <p class="text-muted">Try another municipality, rental shop, or date range.</p>
        </div>
      `;
      return;
    }

    fleetGrid.innerHTML = state.bikes
      .map((bike) => {
        let statusBadge = "";
        if (bike.status === "maintenance") {
          statusBadge = `<span class="badge badge-maintenance">Maintenance</span>`;
        } else if (bike.is_available) {
          const unitLabel = bike.available_units > 1 ? `${bike.available_units} units left` : "Available";
          statusBadge = `<span class="badge badge-available">${escapeHtml(unitLabel)}</span>`;
        } else {
          statusBadge = `<span class="badge badge-booked">Booked for Dates</span>`;
        }

        const bookedSummary = formatBookedRangesLabel(bike.booked_ranges, 2);
        const bookedStrip = bookedSummary
          ? `<div class="bike-booked-strip">Booked: <strong>${escapeHtml(bookedSummary)}</strong></div>`
          : "";

        let nextOpenRow = "";
        if (!bike.is_available && bike.status === "available") {
          if (bike.next_available_date) {
            const nextLabel = bike.next_available_return_date
              ? formatDateRangeShort(bike.next_available_date, bike.next_available_return_date)
              : formatShortDate(bike.next_available_date);
            nextOpenRow = `
              <div class="bike-next-open-row">
                <span>Next open: <strong>${escapeHtml(nextLabel)}</strong></span>
                <button
                  type="button"
                  class="btn btn-sm btn-primary"
                  data-use-next-open="${bike.id}"
                >Book ${escapeHtml(formatShortDate(bike.next_available_date))}</button>
              </div>
            `;
          } else {
            nextOpenRow = `<div class="bike-next-open-row"><span>Booked for selected dates — check calendar for open days.</span></div>`;
          }
        }

        const normImg = normalizeBikeImageUrl(bike.image_url);
        const isPlaceholder = isPlaceholderBikeImage(bike.image_url);
        const mediaInnerHtml = isPlaceholder
          ? `
            <div class="bike-photo-placeholder">
              <img src="${escapeHtml(normImg)}" alt="${escapeHtml(bike.name)}" class="bike-placeholder-svg" loading="lazy">
              <span class="photo-coming-soon-text">Photo Coming Soon</span>
            </div>
          `
          : `<img src="${escapeHtml(normImg)}" alt="${escapeHtml(bike.name)}" loading="lazy">`;

        return `
          <article class="bike-card" data-bike-id="${bike.id}">
            <div class="bike-card-media ${isPlaceholder ? "is-placeholder" : ""}">
              ${mediaInnerHtml}
              <div class="bike-card-top-badges">
                <span class="badge badge-dark">${escapeHtml(bike.category)}</span>
                ${statusBadge}
              </div>
            </div>
            <div class="bike-card-body">
              <div class="shop-pill-line">
                <button type="button" class="shop-pill-btn" data-select-shop="${bike.shop_id}" title="View ${escapeHtml(bike.shop_name || "Shop")} Profile">
                  ${
                    bike.shop_logo_url
                      ? `<img src="${escapeHtml(bike.shop_logo_url)}" alt="" class="shop-pill-avatar">`
                      : `<span class="shop-pill-avatar-fallback">${escapeHtml(getShopInitials(bike.shop_name))}</span>`
                  }
                  <span>${escapeHtml(bike.shop_name || "Verified Shop")} &bull; ${escapeHtml(bike.shop_municipality || "Camiguin")}</span>
                </button>
              </div>
              <div class="bike-card-title-row">
                <h3 class="bike-card-title">${escapeHtml(bike.name)}</h3>
                <div class="bike-rating-pill" title="Average tourist rating">
                  <span class="rating-star">&#9733;</span>
                  <strong>${Number(bike.rating_avg || 5.0).toFixed(1)}</strong>
                  <span class="rating-count">(${bike.rating_count || 0})</span>
                </div>
              </div>
              <div class="bike-specs-row">
                <span class="spec-pill">${bike.engine_cc}cc</span>
                <span class="spec-pill">${escapeHtml(bike.transmission)}</span>
                <span class="spec-pill">${escapeHtml(bike.fuel_type)}</span>
              </div>
              <p class="bike-card-inclusions">${escapeHtml(bike.inclusions || bike.description)}</p>
              ${bookedStrip}
              ${nextOpenRow}
              <div class="bike-card-footer">
                <div>
                  <div class="bike-price-main">
                    ${escapeHtml(formatMoney(bike.daily_rate))}<span class="bike-price-unit">/day</span>
                  </div>
                </div>
                <button
                  type="button"
                  class="btn ${bike.is_available ? "btn-primary" : "btn-outline"}"
                  data-open-bike="${bike.id}"
                >
                  ${bike.is_available ? "Book Now" : "View Calendar"}
                </button>
              </div>
            </div>
          </article>
        `;
      })
      .join("");
  }

  function renderModalContractTerms(bikeObj) {
    const headingEl = document.getElementById("contract-terms-heading");
    const bodyEl = document.getElementById("contract-terms-body");
    if (headingEl) {
      const shopTitle = (bikeObj && bikeObj.shop_name ? String(bikeObj.shop_name).trim() : "MOTORBIKE RENTAL").toUpperCase();
      headingEl.textContent = `📄 ${shopTitle} FORM AGREEMENT`;
    }
    if (!bodyEl) return;
    const rawTerms = (bikeObj && bikeObj.shop_contract_terms ? String(bikeObj.shop_contract_terms).trim() : "");
    if (!rawTerms) return;

    const lines = rawTerms.split(/\r?\n/);
    const htmlParts = [];
    let currentList = [];
    const flushList = () => {
      if (currentList.length) {
        htmlParts.push(`<ul class="contract-terms-list" style="margin:0 0 8px;padding-left:18px;">${currentList.join("")}</ul>`);
        currentList = [];
      }
    };

    for (const rawLine of lines) {
      const line = rawLine.trim();
      if (!line) {
        flushList();
        continue;
      }
      if (/^[•\-*>]\s*/.test(line)) {
        const cleanItem = line.replace(/^[•\-*>]\s*/, "");
        currentList.push(`<li>${escapeHtml(cleanItem)}</li>`);
      } else if (line.endsWith(":") || line.endsWith(";") || (line === line.toUpperCase() && line.length > 4)) {
        flushList();
        htmlParts.push(`<div style="font-weight:700;color:#1e293b;margin:8px 0 4px;">${escapeHtml(line)}</div>`);
      } else {
        currentList.push(`<li>${escapeHtml(line)}</li>`);
      }
    }
    flushList();
    if (htmlParts.length) {
      bodyEl.innerHTML = htmlParts.join("");
    }
  }

  function applyModalBikeImage(bikeObj) {
    const img = document.getElementById("modal-bike-img");
    const wrap = document.getElementById("modal-bike-img-wrap");
    const comingSoon = document.getElementById("modal-photo-coming-soon");
    const normImg = normalizeBikeImageUrl(bikeObj && bikeObj.image_url);
    const isPh = isPlaceholderBikeImage(bikeObj && bikeObj.image_url);
    if (img) {
      img.src = normImg;
      img.alt = (bikeObj && bikeObj.name) || "";
      img.classList.toggle("bike-placeholder-svg", isPh);
    }
    if (wrap) {
      wrap.classList.toggle("is-placeholder", isPh);
    }
    if (comingSoon) {
      comingSoon.classList.toggle("hidden", !isPh);
    }
  }

  async function openBikeModal(bikeId) {
    if (!bikeId) return;
    if (bookingFormError) {
      bookingFormError.classList.add("hidden");
      bookingFormError.textContent = "";
    }

    const todayStr = toIsoLocal(new Date());
    const effectivePickup = state.pickupDate || todayStr;
    if (state.returnDate && state.returnDate < effectivePickup) {
      state.returnDate = "";
    }

    // Step 1: Pre-populate modal immediately from memory if bike exists
    const localBike = (state.bikes || []).find((b) => Number(b.id) === Number(bikeId));
    if (localBike) {
      state.currentBike = localBike;
      if (bookingBikeId) bookingBikeId.value = localBike.id;
      const catEl = document.getElementById("modal-bike-category");
      if (catEl) catEl.textContent = localBike.category || "Scooter";
      const nameEl = document.getElementById("modal-bike-name");
      if (nameEl) nameEl.textContent = localBike.name || "Motorbike";
      applyModalBikeImage(localBike);
      const shopNameEl = document.getElementById("modal-shop-name");
      if (shopNameEl) shopNameEl.textContent = localBike.shop_name || "Verified Partner Shop";
      const shopLocEl = document.getElementById("modal-shop-location");
      if (shopLocEl) {
        shopLocEl.textContent = [localBike.shop_address, localBike.shop_municipality].filter(Boolean).join(" • ");
      }
      const shopPhoneEl = document.getElementById("modal-shop-phone");
      if (shopPhoneEl) {
        shopPhoneEl.textContent = localBike.shop_phone ? `Contact: ${localBike.shop_phone}` : "";
      }
      if (deliveryOptionLabel) {
        const fee = localBike.shop_delivery_fee ?? shop.delivery_fee ?? 250;
        deliveryOptionLabel.textContent = `Hotel / Resort Delivery (Mambajao, Catarman, Sagay, Guinsiliban) (+${formatMoney(fee)})`;
      }
      const specsEl = document.getElementById("modal-bike-specs");
      if (specsEl) {
        specsEl.innerHTML = `
          <span class="spec-pill">${localBike.engine_cc || 125}cc</span>
          <span class="spec-pill">${escapeHtml(localBike.transmission || "Automatic")}</span>
          <span class="spec-pill">${escapeHtml(localBike.fuel_type || "Gasoline")}</span>
          <span class="spec-pill">${localBike.units_count || 1} fleet unit(s)</span>
        `;
      }
      const descEl = document.getElementById("modal-bike-desc");
      if (descEl) descEl.textContent = localBike.description || "";
      const incEl = document.getElementById("modal-bike-inclusions");
      if (incEl) incEl.textContent = localBike.inclusions || "2 Helmets";
      const rateEl = document.getElementById("modal-daily-rate");
      if (rateEl) rateEl.textContent = `${formatMoney(localBike.daily_rate || 0)} / day`;
      const depEl = document.getElementById("modal-deposit-rate");
      if (depEl) depEl.textContent = formatMoney(localBike.deposit || 0);
      renderModalContractTerms(localBike);
    }

    const modalTodayStr = toIsoLocal(new Date());
    const modalPickupStr = state.pickupDate || modalTodayStr;
    if (bookingPickup) {
      bookingPickup.min = modalTodayStr;
      bookingPickup.value = modalPickupStr;
    }
    if (bookingReturn) {
      bookingReturn.min = modalPickupStr;
      bookingReturn.value = state.returnDate || "";
    }
    syncReturnDateUi();

    if (modalAvailCalendar) {
      if (localBike && Array.isArray(localBike.availability_calendar) && localBike.availability_calendar.length) {
        renderModalCalendar();
      } else {
        modalAvailCalendar.innerHTML = `<div class="loading-state" style="padding:16px 8px;font-size:0.86rem;">Checking 35-day live calendar...</div>`;
      }
    }

    if (bookingPickupMethod) {
      if (pendingDeliverySpot) {
        applyPendingDeliverySpot();
      } else {
        syncPickupMethodUi();
      }
    }
    if (bookingPaymentRef) bookingPaymentRef.value = "";
    if (bookingPaymentProof) bookingPaymentProof.value = "";
    if (bookingSubmitBtn) {
      bookingSubmitBtn.textContent = "Confirm Booking Request";
      bookingSubmitBtn.disabled = false;
    }

    // Open modal immediately for instant feedback
    openModal("booking-modal");
    restoreCustomerProfile();
    syncPaymentChannelUi(true);

    // Step 2: Fetch full live schedule and quote in the background
    try {
      const params = new URLSearchParams({
        pickup_date: effectivePickup,
      });
      if (state.returnDate) {
        params.set("return_date", state.returnDate);
      }
      const res = await fetch(`/api/bikes/${bikeId}?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not load bike details.");
      }

      const bike = data.bike;
      state.currentBike = bike;
      if (bookingBikeId) bookingBikeId.value = bike.id;
      const catEl = document.getElementById("modal-bike-category");
      if (catEl) catEl.textContent = bike.category;
      const nameEl = document.getElementById("modal-bike-name");
      if (nameEl) nameEl.textContent = bike.name;
      applyModalBikeImage(bike);

      const shopNameEl = document.getElementById("modal-shop-name");
      if (shopNameEl) shopNameEl.textContent = bike.shop_name || "Verified Partner Shop";
      const shopLocEl = document.getElementById("modal-shop-location");
      if (shopLocEl) {
        shopLocEl.textContent = [bike.shop_address, bike.shop_municipality].filter(Boolean).join(" • ");
      }
      const shopPhoneEl = document.getElementById("modal-shop-phone");
      if (shopPhoneEl) {
        shopPhoneEl.textContent = bike.shop_phone ? `Contact: ${bike.shop_phone}` : "";
      }

      if (deliveryOptionLabel) {
        const fee = bike.shop_delivery_fee ?? shop.delivery_fee ?? 250;
        deliveryOptionLabel.textContent = `Hotel / Resort Delivery (Mambajao, Catarman, Sagay, Guinsiliban) (+${formatMoney(fee)})`;
      }

      const specsEl = document.getElementById("modal-bike-specs");
      if (specsEl) {
        specsEl.innerHTML = `
          <span class="spec-pill">${bike.engine_cc}cc</span>
          <span class="spec-pill">${escapeHtml(bike.transmission)}</span>
          <span class="spec-pill">${escapeHtml(bike.fuel_type)}</span>
          <span class="spec-pill">${bike.units_count} fleet unit(s)</span>
        `;
      }
      const descEl = document.getElementById("modal-bike-desc");
      if (descEl) descEl.textContent = bike.description || "";
      const incEl = document.getElementById("modal-bike-inclusions");
      if (incEl) incEl.textContent = bike.inclusions || "2 Helmets";
      renderModalContractTerms(bike);
      const rateEl = document.getElementById("modal-daily-rate");
      if (rateEl) rateEl.textContent = `${formatMoney(bike.daily_rate)} / day`;
      const depEl = document.getElementById("modal-deposit-rate");
      if (depEl) depEl.textContent = formatMoney(bike.deposit);

      const rangesEl = document.getElementById("modal-booked-ranges");
      if (rangesEl) {
        const ranges = bike.booked_ranges || [];
        if (!ranges.length) {
          rangesEl.innerHTML = `<span class="text-muted">No upcoming bookings yet — wide open!</span>`;
        } else {
          rangesEl.innerHTML = ranges
            .map(
              (r) =>
                `<span class="booked-range-pill">${escapeHtml(formatDateRangeShort(r.pickup_date, r.return_date))}</span>`
            )
            .join("");
        }
      }

      const avgEl = document.getElementById("modal-rating-avg");
      if (avgEl) avgEl.textContent = Number(bike.rating_avg || 5.0).toFixed(1);
      const countEl = document.getElementById("modal-rating-count");
      if (countEl) countEl.textContent = String(bike.rating_count || 0);
      const reviewsListEl = document.getElementById("modal-reviews-list");
      if (reviewsListEl) {
        if (Array.isArray(bike.reviews) && bike.reviews.length) {
          reviewsListEl.innerHTML = bike.reviews.map(r => `
            <div style="padding:6px 0;border-bottom:1px solid #f1f5f9;font-size:0.8rem;">
              <div style="display:flex;justify-content:space-between;align-items:center;">
                <strong>${escapeHtml(r.customer_name)}</strong>
                <span style="color:#f59e0b;">${'★'.repeat(Math.max(1, Math.min(5, r.rating || 5)))}</span>
              </div>
              <div class="text-muted" style="margin-top:2px;">&ldquo;${escapeHtml(r.comment)}&rdquo;</div>
            </div>
          `).join("");
        } else {
          reviewsListEl.innerHTML = `<div class="text-muted" style="font-size:0.82rem;">No reviews yet for this motorbike.</div>`;
        }
      }

      renderModalCalendar();
      await refreshQuote();
      syncPaymentChannelUi(false);
    } catch (err) {
      if (bookingFormError) {
        bookingFormError.textContent = err.message;
        bookingFormError.classList.remove("hidden");
      }
      await refreshQuote();
    }
  }

  async function refreshQuote() {
    const bikeId = bookingBikeId.value;
    const pDate = bookingPickup.value;
    const rDate = bookingReturn.value;
    if (!bikeId || !pDate) return;

    const hasExplicitReturn = Boolean(rDate);
    if (hasExplicitReturn && rDate < pDate) {
      bookingReturn.value = pDate;
      syncDateWrap(bookingReturn);
    }
    syncReturnDateUi();
    const effectiveReturn = bookingReturn.value || pDate;

    const params = new URLSearchParams({
      bike_id: bikeId,
      pickup_date: pDate,
      return_date: effectiveReturn,
      pickup_method: bookingPickupMethod.value,
      extra_helmet: extraHelmetCheckbox.checked ? "1" : "0",
      top_box: topBoxCheckbox.checked ? "1" : "0",
    });

    try {
      const res = await fetch(`/api/quote?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        state.latestQuote = null;
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = data.error || "Invalid dates";
        quoteLines.innerHTML = "";
        bookingSubmitBtn.disabled = true;
        syncPaymentChannelUi(false);
        return;
      }

      const q = data.quote;
      state.latestQuote = q;
      if (q.bike_status !== "available") {
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = "Currently under maintenance";
        bookingSubmitBtn.disabled = true;
        syncNextAvailableBtn(null);
      } else if (!q.is_available) {
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = hasExplicitReturn
          ? "Already booked for these dates — pick open green dates on the calendar above"
          : `${formatShortDate(pDate)} is already booked — tap a green open date on the calendar above.`;
        bookingSubmitBtn.disabled = true;
        syncNextAvailableBtn(
          findNextAvailableRange(state.currentBike, pDate, hasExplicitReturn ? bookingReturn.value : "")
        );
      } else if (!hasExplicitReturn) {
        quoteAvailability.className = "quote-availability muted";
        quoteAvailability.textContent = "Select a return date above to check availability & total price.";
        bookingSubmitBtn.disabled = false;
        syncNextAvailableBtn(null);
      } else {
        quoteAvailability.className = "quote-availability ok";
        quoteAvailability.textContent = `Available (${q.available_units} of ${q.units_count} unit(s) open)`;
        bookingSubmitBtn.disabled = false;
        syncNextAvailableBtn(null);
      }

      const dayWord = q.rental_days === 1 ? "day" : "days";
      let linesHtml = `
        <div class="quote-line">
          <span>Rental (${q.rental_days} ${dayWord})</span>
          <span>${escapeHtml(formatMoney(q.base_subtotal))}</span>
        </div>
      `;
      if (q.addons_total > 0) {
        linesHtml += `
          <div class="quote-line">
            <span>Add-ons (${q.rental_days} ${dayWord})</span>
            <span>${escapeHtml(formatMoney(q.addons_total))}</span>
          </div>
        `;
      }
      if (q.delivery_total > 0) {
        const dLabel = q.pickup_method === "benoni_port"
          ? "Benoni Port (Mahinog) Delivery (+₱200)"
          : "Hotel / Resort Delivery";
        linesHtml += `
          <div class="quote-line">
            <span>${escapeHtml(dLabel)}</span>
            <span>${escapeHtml(formatMoney(q.delivery_total))}</span>
          </div>
        `;
      } else if (q.pickup_method === "balbagon_port") {
        linesHtml += `
          <div class="quote-line">
            <span>Balbagon Port (Mambajao) Delivery</span>
            <span style="color:var(--success,#059669);font-weight:700;">FREE</span>
          </div>
        `;
      } else if (q.pickup_method === "airport") {
        linesHtml += `
          <div class="quote-line">
            <span>Camiguin Airport (Mambajao) Delivery</span>
            <span style="color:var(--success,#059669);font-weight:700;">FREE</span>
          </div>
        `;
      } else if (q.pickup_method === "around_mambajao" || q.pickup_method === "mambajao") {
        linesHtml += `
          <div class="quote-line">
            <span>Hotel / Resort Delivery (Mambajao)</span>
            <span style="color:var(--success,#059669);font-weight:700;">FREE</span>
          </div>
        `;
      }
      linesHtml += `
        <div class="quote-line total">
          <span>Total Rental Amount</span>
          <span>${escapeHtml(formatMoney(q.total_amount))}</span>
        </div>
      `;
      if (q.reservation_mode !== "off" && q.reservation_configured && Number(q.reservation_fee || 0) > 0) {
        const dpLabel = Number(q.rental_days || 1) >= 3
          ? "Down Payment (3+ Days Flat Rate)"
          : `Down Payment (${q.reservation_percent}% for 1–2 Days)`;
        linesHtml += `
          <div class="quote-line">
            <span>${escapeHtml(dpLabel)}</span>
            <span>${escapeHtml(formatMoney(q.reservation_fee))}</span>
          </div>
          <div class="quote-line">
            <span>Remaining Balance Due at Pickup</span>
            <span>${escapeHtml(formatMoney(q.balance_due))}</span>
          </div>
        `;
      }
      quoteLines.innerHTML = linesHtml;
      syncPaymentChannelUi(false);
    } catch (_) {
      state.latestQuote = null;
      quoteAvailability.className = "quote-availability bad";
      quoteAvailability.textContent = "Unable to calculate quote right now.";
      syncPaymentChannelUi(false);
    }
  }

  // Event Listeners
  if (searchForm) {
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!searchReturnInput || !searchReturnInput.value) {
        if (searchReturnInput) {
          searchReturnInput.focus();
          if (typeof searchReturnInput.reportValidity === "function") {
            searchReturnInput.reportValidity();
          }
          try {
            searchReturnInput.showPicker?.();
          } catch (_) {}
        }
        showToast("Please select a return date.", "error");
        return;
      }
      if (searchReturnInput.value < searchPickupInput.value) {
        searchReturnInput.value = searchPickupInput.value;
        syncDateWrap(searchReturnInput);
      }
      state.pickupDate = searchPickupInput.value;
      state.returnDate = searchReturnInput.value;
      state.municipality = searchMunicipality ? searchMunicipality.value : "All";
      state.transmission = searchTransmission.value;
      loadFleet();
      document.getElementById("fleet")?.scrollIntoView({ behavior: "smooth" });
    });
  }

  if (searchPickupInput) {
    searchPickupInput.addEventListener("change", () => {
      const pVal = searchPickupInput.value || toIsoLocal(new Date());
      if (searchReturnInput) {
        searchReturnInput.min = pVal;
        if (searchReturnInput.value && searchReturnInput.value < pVal) {
          searchReturnInput.value = pVal;
          syncDateWrap(searchReturnInput);
        }
      }
      state.pickupDate = pVal;
      state.returnDate = searchReturnInput ? searchReturnInput.value : "";
      loadFleet();
    });
  }

  if (searchReturnInput) {
    searchReturnInput.addEventListener("change", () => {
      if (searchReturnInput.value && searchPickupInput && searchReturnInput.value < searchPickupInput.value) {
        searchReturnInput.value = searchPickupInput.value;
      }
      syncDateWrap(searchReturnInput);
      state.pickupDate = searchPickupInput ? searchPickupInput.value : state.pickupDate;
      state.returnDate = searchReturnInput.value;
      loadFleet();
    });
  }

  if (searchMunicipality) {
    searchMunicipality.addEventListener("change", () => {
      state.municipality = searchMunicipality.value;
      loadFleet();
    });
  }

  if (searchTransmission) {
    searchTransmission.addEventListener("change", () => {
      state.transmission = searchTransmission.value;
      loadFleet();
    });
  }

  if (filterShop) {
    filterShop.addEventListener("change", () => {
      selectShopFilter(filterShop.value, { updateHistory: true });
    });
  }

  if (partnerShopsStrip) {
    partnerShopsStrip.addEventListener("click", (event) => {
      const card = event.target.closest("[data-select-shop]");
      if (!card) return;
      const clickedShopId = card.getAttribute("data-select-shop");
      const nextShopId = String(state.shopId) === String(clickedShopId) ? "" : clickedShopId;
      selectShopFilter(nextShopId, { updateHistory: true, scrollToBanner: Boolean(nextShopId) });
    });
  }

  if (partnerShopsResetBtn) {
    partnerShopsResetBtn.addEventListener("click", () => {
      selectShopFilter("", { updateHistory: true });
    });
  }

  if (shopProfileBanner) {
    shopProfileBanner.addEventListener("click", async (event) => {
      const clearBtn = event.target.closest("[data-clear-shop-filter]");
      if (clearBtn) {
        selectShopFilter("", { updateHistory: true });
        return;
      }
      const copyBtn = event.target.closest("[data-copy-shop-link]");
      if (copyBtn) {
        const url = copyBtn.getAttribute("data-copy-shop-link");
        try {
          await navigator.clipboard.writeText(url);
          showToast("Shop profile link copied! Ready to paste on your Facebook Page.", "success");
        } catch (_) {
          showToast(`Shop Link: ${url}`, "success");
        }
      }
    });
  }

  if (categoryPills) {
    categoryPills.addEventListener("click", (event) => {
      const btn = event.target.closest("[data-category]");
      if (!btn) return;
      categoryPills.querySelectorAll(".pill").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      state.category = btn.getAttribute("data-category");
      loadFleet();
    });
  }

  if (filterSort) {
    filterSort.addEventListener("change", () => {
      state.sort = filterSort.value;
      loadFleet();
    });
  }

  if (filterAvailableOnly) {
    filterAvailableOnly.addEventListener("change", () => {
      state.availableOnly = filterAvailableOnly.checked;
      loadFleet();
    });
  }

  let searchDebounce = null;
  if (filterSearchQ) {
    filterSearchQ.addEventListener("input", () => {
      clearTimeout(searchDebounce);
      searchDebounce = setTimeout(() => {
        state.q = filterSearchQ.value.trim();
        loadFleet();
      }, 220);
    });
  }

  if (fleetGrid) {
    fleetGrid.addEventListener("click", (event) => {
      const nextBtn = event.target.closest("[data-use-next-open]");
      if (nextBtn) {
        const bikeId = Number(nextBtn.getAttribute("data-use-next-open"));
        const bike = state.bikes.find((b) => b.id === bikeId);
        if (bike && bike.next_available_date) {
          state.pickupDate = bike.next_available_date;
          state.returnDate = bike.next_available_return_date || "";
          if (searchPickupInput) searchPickupInput.value = state.pickupDate;
          if (searchReturnInput) {
            searchReturnInput.min = state.pickupDate;
            searchReturnInput.value = state.returnDate;
          }
          syncReturnDateUi();
          loadFleet();
          openBikeModal(bikeId);
          return;
        }
      }
      const shopBtn = event.target.closest("[data-select-shop]");
      if (shopBtn) {
        selectShopFilter(shopBtn.getAttribute("data-select-shop"), {
          updateHistory: true,
          scrollToBanner: true,
        });
        return;
      }
      const btn = event.target.closest("[data-open-bike]");
      if (btn) {
        openBikeModal(Number(btn.getAttribute("data-open-bike")));
        return;
      }
      const card = event.target.closest(".bike-card[data-bike-id]");
      if (card) {
        const bikeId = Number(card.getAttribute("data-bike-id"));
        if (bikeId) {
          openBikeModal(bikeId);
          return;
        }
      }
    });
  }

  if (modalAvailCalendar) {
    modalAvailCalendar.addEventListener("click", (event) => {
      const cell = event.target.closest("[data-cal-date]");
      if (!cell || cell.disabled || !state.currentBike) return;
      const clicked = cell.getAttribute("data-cal-date");
      if (!clicked || !bookingPickup || !bookingReturn) return;

      const curPickup = bookingPickup.value;
      const curReturn = bookingReturn.value;
      const pickupBlocked = !curPickup || isDateFullyBooked(state.currentBike, curPickup);

      if (
        pickupBlocked ||
        curReturn ||
        clicked < curPickup ||
        hasBookedDayInRange(state.currentBike, curPickup, clicked)
      ) {
        bookingPickup.value = clicked;
        bookingReturn.min = clicked;
        bookingReturn.value = "";
        syncDateWrap(bookingReturn);
        showToast(`Pickup set to ${formatShortDate(clicked)}. Now tap a return date.`);
      } else {
        bookingReturn.min = curPickup;
        bookingReturn.value = clicked;
        syncDateWrap(bookingReturn);
      }
      renderModalCalendar();
      refreshQuote();
    });
  }

  if (modalNextAvailableBtn) {
    modalNextAvailableBtn.addEventListener("click", () => {
      const sug = state.suggestedOpenWindow;
      if (!sug || !sug.pickup_date || !bookingPickup || !bookingReturn) return;
      bookingPickup.value = sug.pickup_date;
      bookingReturn.min = sug.pickup_date;
      bookingReturn.value = sug.return_date || "";
      syncDateWrap(bookingReturn);
      renderModalCalendar();
      refreshQuote();
      showToast(`Moved to open date ${formatShortDate(sug.pickup_date)}.`, "success");
    });
  }

  let deliveryMapInstance = null;
  let deliveryMarker = null;

  function initOrUpdateDeliveryMap(targetLat, targetLng) {
    const mapEl = document.getElementById("delivery-map");
    if (!mapEl || typeof L === "undefined") return;

    const defaultLat = targetLat || 9.2450;
    const defaultLng = targetLng || 124.6850;

    if (!deliveryMapInstance) {
      deliveryMapInstance = L.map("delivery-map", {
        center: [defaultLat, defaultLng],
        zoom: 12,
        minZoom: 10,
        maxZoom: 18,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; OpenStreetMap',
        maxZoom: 19,
      }).addTo(deliveryMapInstance);

      deliveryMarker = L.marker([defaultLat, defaultLng], {
        draggable: true,
      }).addTo(deliveryMapInstance);

      deliveryMarker.on("dragend", (e) => {
        const pos = e.target.getLatLng();
        setDeliveryCoordinates(pos.lat, pos.lng);
      });

      deliveryMapInstance.on("click", (e) => {
        const pos = e.latlng;
        deliveryMarker.setLatLng(pos);
        setDeliveryCoordinates(pos.lat, pos.lng);
      });
    }

    setTimeout(() => {
      if (deliveryMapInstance) {
        deliveryMapInstance.invalidateSize();
        if (targetLat && targetLng) {
          deliveryMapInstance.setView([targetLat, targetLng], 14);
          if (deliveryMarker) deliveryMarker.setLatLng([targetLat, targetLng]);
        }
      }
    }, 200);
  }

  function setDeliveryCoordinates(lat, lng, addressLabel) {
    const latInput = document.getElementById("booking-delivery-lat");
    const lngInput = document.getElementById("booking-delivery-lng");
    const coordsText = document.getElementById("delivery-coords-text");
    if (latInput) latInput.value = lat.toFixed(6);
    if (lngInput) lngInput.value = lng.toFixed(6);
    if (coordsText) coordsText.textContent = `${lat.toFixed(5)}, ${lng.toFixed(5)}${addressLabel ? ` (${addressLabel})` : ""}`;
    if (addressLabel && deliveryAddressInput) {
      deliveryAddressInput.value = addressLabel;
    }
  }

  const pickupLocationPreset = document.getElementById("booking-pickup-location-preset");
  const dropoffLocationPreset = document.getElementById("booking-dropoff-location-preset");

  function buildPresetDeliveryAddress(baseAddress) {
    const cleanBase = (baseAddress || "").trim();
    const dropoffVal = dropoffLocationPreset ? dropoffLocationPreset.value : "Same as Pickup Location";
    if (!cleanBase) return "";
    if (dropoffVal && dropoffVal !== "Same as Pickup Location") {
      return `${cleanBase} (Drop-off: ${dropoffVal})`;
    }
    return cleanBase;
  }

  function syncPickupMethodUi() {
    if (!bookingPickupMethod) return;
    const method = bookingPickupMethod.value;
    const isDelivery = method !== "shop";
    if (deliveryAddressGroup) deliveryAddressGroup.classList.toggle("hidden", !isDelivery);
    const labelEl = document.getElementById("delivery-address-label");

    if (method === "benoni_port") {
      if (labelEl) labelEl.textContent = "Arrival Details / Pier (Benoni Port, Mahinog) *";
      if (deliveryAddressInput) {
        deliveryAddressInput.required = true;
        deliveryAddressInput.placeholder = "e.g., Benoni Port (Mahinog) — Ferry name / Arrival time";
        if (
          !deliveryAddressInput.value ||
          deliveryAddressInput.value.includes("Airport") ||
          deliveryAddressInput.value.includes("Balbagon") ||
          deliveryAddressInput.value === "Shop Pickup"
        ) {
          deliveryAddressInput.value = buildPresetDeliveryAddress("Benoni Port (Mahinog)");
        }
      }
      if (pickupLocationPreset && pickupLocationPreset.value !== "Benoni Port (Mahinog)") {
        pickupLocationPreset.value = "Benoni Port (Mahinog)";
      }
      initOrUpdateDeliveryMap(9.1306, 124.7937);
      setDeliveryCoordinates(9.1306, 124.7937, deliveryAddressInput ? deliveryAddressInput.value : "Benoni Port (Mahinog)");
    } else if (method === "balbagon_port") {
      if (labelEl) labelEl.textContent = "Arrival Details / Pier (Balbagon Port, Mambajao) *";
      if (deliveryAddressInput) {
        deliveryAddressInput.required = true;
        deliveryAddressInput.placeholder = "e.g., Balbagon Port (Mambajao) — Bohol Ferry / Arrival time";
        if (
          !deliveryAddressInput.value ||
          deliveryAddressInput.value.includes("Benoni") ||
          deliveryAddressInput.value.includes("Airport") ||
          deliveryAddressInput.value === "Shop Pickup"
        ) {
          deliveryAddressInput.value = buildPresetDeliveryAddress("Balbagon Port (Mambajao)");
        }
      }
      if (pickupLocationPreset && pickupLocationPreset.value !== "Balbagon Port (Mambajao)") {
        pickupLocationPreset.value = "Balbagon Port (Mambajao)";
      }
      initOrUpdateDeliveryMap(9.2561, 124.7175);
      setDeliveryCoordinates(9.2561, 124.7175, deliveryAddressInput ? deliveryAddressInput.value : "Balbagon Port (Mambajao)");
    } else if (method === "airport") {
      if (labelEl) labelEl.textContent = "Flight / Arrival Details (Camiguin Airport, Mambajao) *";
      if (deliveryAddressInput) {
        deliveryAddressInput.required = true;
        deliveryAddressInput.placeholder = "e.g., Camiguin Airport (Mambajao) — Flight number / ETA";
        if (
          !deliveryAddressInput.value ||
          deliveryAddressInput.value.includes("Benoni") ||
          deliveryAddressInput.value.includes("Balbagon") ||
          deliveryAddressInput.value === "Shop Pickup"
        ) {
          deliveryAddressInput.value = buildPresetDeliveryAddress("Camiguin Airport (Mambajao)");
        }
      }
      if (pickupLocationPreset && pickupLocationPreset.value !== "Camiguin Airport (Mambajao)") {
        pickupLocationPreset.value = "Camiguin Airport (Mambajao)";
      }
      initOrUpdateDeliveryMap(9.2530, 124.7061);
      setDeliveryCoordinates(9.2530, 124.7061, deliveryAddressInput ? deliveryAddressInput.value : "Camiguin Airport (Mambajao)");
    } else if (method === "around_mambajao" || method === "mambajao" || method === "delivery") {
      if (labelEl) {
        labelEl.textContent =
          method === "delivery"
            ? "Hotel / Resort Delivery Address (Mambajao, Catarman, Sagay, Guinsiliban) *"
            : "Delivery Address (Resort / Hotel / Location in Mambajao) *";
      }
      if (deliveryAddressInput) {
        deliveryAddressInput.required = true;
        deliveryAddressInput.placeholder = "e.g., Paras Beach Resort / Balyali / Nouveau Resort / Catarman / Sagay";
        if (
          deliveryAddressInput.value.startsWith("Benoni Port") ||
          deliveryAddressInput.value.startsWith("Balbagon Port") ||
          deliveryAddressInput.value.startsWith("Camiguin Airport") ||
          deliveryAddressInput.value === "Shop Pickup"
        ) {
          deliveryAddressInput.value = "";
        }
      }
      initOrUpdateDeliveryMap();
    } else {
      // shop
      if (pickupLocationPreset && pickupLocationPreset.value !== "shop") {
        pickupLocationPreset.value = "shop";
      }
      if (deliveryAddressInput) {
        deliveryAddressInput.required = false;
        if (
          deliveryAddressInput.value.startsWith("Benoni Port") ||
          deliveryAddressInput.value.startsWith("Balbagon Port") ||
          deliveryAddressInput.value.startsWith("Camiguin Airport")
        ) {
          deliveryAddressInput.value = "";
        }
      }
    }
  }

  if (bookingPickupMethod) {
    bookingPickupMethod.addEventListener("change", () => {
      syncPickupMethodUi();
      refreshQuote();
    });
  }

  if (pickupLocationPreset) {
    pickupLocationPreset.addEventListener("change", () => {
      const selectedOpt = pickupLocationPreset.options[pickupLocationPreset.selectedIndex];
      if (!selectedOpt) return;
      const targetMethod = selectedOpt.getAttribute("data-method") || "shop";
      const presetAddress = selectedOpt.getAttribute("data-address") || pickupLocationPreset.value;
      const lat = parseFloat(selectedOpt.getAttribute("data-lat") || "");
      const lng = parseFloat(selectedOpt.getAttribute("data-lng") || "");

      if (bookingPickupMethod) {
        bookingPickupMethod.value = targetMethod;
      }
      syncPickupMethodUi();
      if (targetMethod !== "shop") {
        const fullAddr = buildPresetDeliveryAddress(presetAddress);
        if (deliveryAddressInput) {
          deliveryAddressInput.value = fullAddr;
        }
        if (!Number.isNaN(lat) && !Number.isNaN(lng)) {
          initOrUpdateDeliveryMap(lat, lng);
          setDeliveryCoordinates(lat, lng, fullAddr);
        }
      }
      refreshQuote();
    });
  }

  if (dropoffLocationPreset) {
    dropoffLocationPreset.addEventListener("change", () => {
      if (!deliveryAddressInput || !bookingPickupMethod) return;
      const currentVal = (deliveryAddressInput.value || "").replace(/\s*\(Drop-off:.*\)$/i, "").trim();
      if (currentVal && bookingPickupMethod.value !== "shop") {
        deliveryAddressInput.value = buildPresetDeliveryAddress(currentVal);
      }
    });
  }

  const landmarkChipsEl = document.getElementById("landmark-chips");
  if (landmarkChipsEl) {
    landmarkChipsEl.addEventListener("click", (e) => {
      const chip = e.target.closest(".landmark-chip");
      if (!chip) return;
      const lat = parseFloat(chip.getAttribute("data-lat"));
      const lng = parseFloat(chip.getAttribute("data-lng"));
      const name = chip.getAttribute("data-name") || "";

      if (bookingPickupMethod) {
        if (name.includes("Benoni")) {
          bookingPickupMethod.value = "benoni_port";
        } else if (name.includes("Balbagon")) {
          bookingPickupMethod.value = "balbagon_port";
        } else if (name.includes("Airport")) {
          bookingPickupMethod.value = "airport";
        } else if (
          name.includes("Catarman") ||
          name.includes("Sagay") ||
          name.includes("Guinsiliban") ||
          name.includes("Mahinog") ||
          name.includes("Nouveau") ||
          name.includes("Mantigue")
        ) {
          bookingPickupMethod.value = "delivery";
        } else {
          bookingPickupMethod.value = "around_mambajao";
        }
        syncPickupMethodUi();
      }
      const fullAddr = buildPresetDeliveryAddress(name);
      initOrUpdateDeliveryMap(lat, lng);
      setDeliveryCoordinates(lat, lng, fullAddr);
      refreshQuote();
    });
  }

  const locateMeBtn = document.getElementById("locate-me-btn");
  if (locateMeBtn) {
    locateMeBtn.addEventListener("click", () => {
      if (!navigator.geolocation) {
        showToast("Geolocation is not supported by your browser.", "error");
        return;
      }
      locateMeBtn.disabled = true;
      locateMeBtn.textContent = "Locating...";
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          locateMeBtn.disabled = false;
          locateMeBtn.textContent = "📍 My GPS Location";
          const lat = pos.coords.latitude;
          const lng = pos.coords.longitude;
          initOrUpdateDeliveryMap(lat, lng);
          setDeliveryCoordinates(lat, lng, "Current GPS Location");
          showToast("Pinned your exact GPS location!", "success");
        },
        (err) => {
          locateMeBtn.disabled = false;
          locateMeBtn.textContent = "📍 My GPS Location";
          showToast("Could not get GPS location: " + err.message, "error");
        },
        { timeout: 10000, enableHighAccuracy: true }
      );
    });
  }

  const CAMIGUIN_LANDMARKS = [
    {
      id: "benoni-port",
      name: "🚢 Benoni Ferry Port",
      category: "port",
      badgeClass: "badge-port",
      typeLabel: "Ferry Terminal",
      lat: 9.1672,
      lng: 124.8028,
      desc: "Main gateway port to Camiguin from Balingoan, Misamis Oriental / CDO. Fastcraft and RoRo dock here.",
      address: "Benoni Port (Mahinog)"
    },
    {
      id: "balbagon-port",
      name: "⛴️ Balbagon Port",
      category: "port",
      badgeClass: "badge-port",
      typeLabel: "Ferry Port",
      lat: 9.2530,
      lng: 124.7170,
      desc: "Ferry terminal connecting Camiguin to Jagna, Bohol (Super Shuttle Ferry).",
      address: "Balbagon Port (Mambajao)"
    },
    {
      id: "camiguin-airport",
      name: "✈️ Camiguin Airport (CGM)",
      category: "port",
      badgeClass: "badge-port",
      typeLabel: "Airport",
      lat: 9.2520,
      lng: 124.7060,
      desc: "Camiguin domestic commercial airport in Mambajao with flights from Cebu / Manila.",
      address: "Camiguin Airport (Mambajao)"
    },
    {
      id: "white-island",
      name: "🏖️ White Island Sandbar",
      category: "beach",
      badgeClass: "badge-spot",
      typeLabel: "Tourist Attraction",
      lat: 9.2580,
      lng: 124.6540,
      desc: "Iconic uninhabited white sandbar with Mt. Hibok-Hibok view. Boat jump-off at Yumbing.",
      address: "White Island Jump-off, Yumbing, Mambajao"
    },
    {
      id: "mantigue-island",
      name: "🏝️ Mantigue Island Nature Park",
      category: "beach",
      badgeClass: "badge-spot",
      typeLabel: "Tourist Attraction",
      lat: 9.1720,
      lng: 124.8230,
      desc: "4-hectare marine sanctuary with crystal clear water and lush mini-forest.",
      address: "Mantigue Island Boat Jump-off, San Roque, Mahinog"
    },
    {
      id: "sunken-cemetery",
      name: "🌊 Sunken Cemetery & Cross",
      category: "history",
      badgeClass: "badge-spot",
      typeLabel: "Historical Landmark",
      lat: 9.2010,
      lng: 124.6320,
      desc: "Famous underwater cemetery submerged during the 1871 Mt. Vulcan eruption.",
      address: "Sunken Cemetery, Bonbon, Catarman"
    },
    {
      id: "church-ruins",
      name: "⛪ Old Spanish Church Ruins (Guiob)",
      category: "history",
      badgeClass: "badge-spot",
      typeLabel: "Historical Landmark",
      lat: 9.2070,
      lng: 124.6300,
      desc: "16th-century stone church walls preserved after the 1871 volcanic eruption.",
      address: "Guiob Church Ruins, Bonbon, Catarman"
    },
    {
      id: "katibawasan-falls",
      name: "💧 Katibawasan Falls",
      category: "nature",
      badgeClass: "badge-spot",
      typeLabel: "Nature / Waterfall",
      lat: 9.2150,
      lng: 124.7170,
      desc: "Stunning 250-foot waterfall cascading into a natural boulder basin.",
      address: "Katibawasan Falls, Upper Mambajao"
    },
    {
      id: "tuasan-falls",
      name: "🏞️ Tuasan Falls",
      category: "nature",
      badgeClass: "badge-spot",
      typeLabel: "Nature / Waterfall",
      lat: 9.1760,
      lng: 124.6750,
      desc: "Pristine wild waterfall tucked in lush jungle scenery with refreshing plunge pool.",
      address: "Tuasan Falls, Mainit, Catarman"
    },
    {
      id: "ardent-springs",
      name: "♨️ Ardent Hibok-Hibok Hot Springs",
      category: "nature",
      badgeClass: "badge-spot",
      typeLabel: "Thermal Spring",
      lat: 9.2210,
      lng: 124.6760,
      desc: "Natural geothermal warm pools surrounded by tropical greenery at Mt. Hibok-Hibok foot.",
      address: "Ardent Hot Springs, Esperanza, Mambajao"
    },
    {
      id: "stonino-springs",
      name: "🧊 Sto. Niño Cold Springs",
      category: "nature",
      badgeClass: "badge-spot",
      typeLabel: "Natural Cold Spring",
      lat: 9.1410,
      lng: 124.7210,
      desc: "Huge spring-fed freshwater pool with chilly crystal-clear spring water.",
      address: "Sto. Niño Cold Springs, Sagay, Camiguin"
    },
    {
      id: "paras-beach-resort",
      name: "🌴 Paras Beach Resort",
      category: "resort",
      badgeClass: "badge-resort",
      typeLabel: "Beach Resort",
      lat: 9.2480,
      lng: 124.6620,
      desc: "Popular beachfront resort facing White Island in Yumbing, Mambajao.",
      address: "Paras Beach Resort, Yumbing, Mambajao"
    },
    {
      id: "balyali-resort",
      name: "🌴 Balyali Resort Camiguin",
      category: "resort",
      badgeClass: "badge-resort",
      typeLabel: "Beachfront Resort",
      lat: 9.2465,
      lng: 124.6730,
      desc: "Cozy boutique resort with stunning beach sunset views in Agoho, Mambajao.",
      address: "Balyali Resort, Agoho, Mambajao"
    },
    {
      id: "tongatok-cliff",
      name: "🌅 Tongatok Cliff Resort",
      category: "resort",
      badgeClass: "badge-resort",
      typeLabel: "Cliffside Resort",
      lat: 9.2415,
      lng: 124.6465,
      desc: "Cliffside resort and cafe known for dramatic rocky cove vistas and sunset cocktails.",
      address: "Tongatok Cliff Resort, Mambajao, Camiguin"
    },
    {
      id: "lanzones-resort",
      name: "🌿 Lanzones Resort Camiguin",
      category: "resort",
      badgeClass: "badge-resort",
      typeLabel: "Resort",
      lat: 9.2420,
      lng: 124.6680,
      desc: "Peaceful villa resort surrounded by verdant Lanzones fruit orchards in Agoho.",
      address: "Lanzones Resort, Agoho, Mambajao"
    },
    {
      id: "nouveau-resort",
      name: "✨ Nouveau Resort Camiguin",
      category: "resort",
      badgeClass: "badge-resort",
      typeLabel: "Luxury Resort",
      lat: 9.1760,
      lng: 124.7890,
      desc: "Premier 4-star luxury seaside resort with infinity pool facing Bohol Sea.",
      address: "Nouveau Resort, San Jose, Mahinog"
    }
  ];

  let pendingDeliverySpot = null;

  function prefillDeliveryForSpot(spot) {
    pendingDeliverySpot = spot;
    const modal = document.getElementById("booking-modal");
    if (modal && !modal.classList.contains("hidden")) {
      applyPendingDeliverySpot();
      showToast(`Set delivery to ${spot.name}!`, "success");
    } else {
      const firstAvailBike = (state.bikes || []).find((b) => b.is_available) || (state.bikes || [])[0];
      if (firstAvailBike) {
        openBikeModal(firstAvailBike.id);
        setTimeout(() => {
          applyPendingDeliverySpot();
        }, 150);
        showToast(`Selected ${spot.name}! Motorbike ready for booking.`, "success");
      } else {
        document.getElementById("fleet")?.scrollIntoView({ behavior: "smooth" });
        showToast(`Selected ${spot.name}! Please choose a motorbike from the fleet below.`, "success");
      }
    }
  }

  function applyPendingDeliverySpot() {
    if (!pendingDeliverySpot) return;
    if (bookingPickupMethod) {
      const spotName = `${pendingDeliverySpot.name || ""} ${pendingDeliverySpot.address || ""}`;
      if (spotName.includes("Benoni")) {
        bookingPickupMethod.value = "benoni_port";
      } else if (spotName.includes("Balbagon")) {
        bookingPickupMethod.value = "balbagon_port";
      } else if (spotName.includes("Airport")) {
        bookingPickupMethod.value = "airport";
      } else if (
        spotName.includes("Catarman") ||
        spotName.includes("Sagay") ||
        spotName.includes("Guinsiliban") ||
        spotName.includes("Mahinog") ||
        spotName.includes("Nouveau")
      ) {
        bookingPickupMethod.value = "delivery";
      } else {
        bookingPickupMethod.value = "around_mambajao";
      }
      syncPickupMethodUi();
      initOrUpdateDeliveryMap(pendingDeliverySpot.lat, pendingDeliverySpot.lng);
      setDeliveryCoordinates(
        pendingDeliverySpot.lat,
        pendingDeliverySpot.lng,
        pendingDeliverySpot.address || pendingDeliverySpot.name
      );
      refreshQuote();
    }
    pendingDeliverySpot = null;
  }

  let homepageMapInstance = null;
  let homepageMarkers = [];

  function initHomepageTouristMap() {
    const mapEl = document.getElementById("homepage-map");
    if (!mapEl || typeof L === "undefined") return;

    if (!homepageMapInstance) {
      homepageMapInstance = L.map("homepage-map", {
        center: [9.208, 124.715],
        zoom: 11,
        minZoom: 10,
        maxZoom: 18,
        scrollWheelZoom: false,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
        maxZoom: 19,
      }).addTo(homepageMapInstance);

      CAMIGUIN_LANDMARKS.forEach((lm) => {
        const marker = L.marker([lm.lat, lm.lng], {
          title: lm.name,
        }).addTo(homepageMapInstance);

        const popupHtml = `
          <div class="map-popup-card">
            <div class="map-popup-title">${escapeHtml(lm.name)}</div>
            <span class="map-popup-badge ${lm.badgeClass}">${escapeHtml(lm.typeLabel)}</span>
            <p class="map-popup-desc">${escapeHtml(lm.desc)}</p>
            <button type="button" class="map-popup-btn" data-book-delivery-spot="${lm.id}">
              🛵 Book Motorbike Delivery Here &rarr;
            </button>
          </div>
        `;
        marker.bindPopup(popupHtml);
        marker.__landmarkData = lm;
        homepageMarkers.push(marker);
      });

      // Delegate click on popup buttons
      document.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-book-delivery-spot]");
        if (!btn) return;
        const spotId = btn.getAttribute("data-book-delivery-spot");
        const spot = CAMIGUIN_LANDMARKS.find((s) => s.id === spotId);
        if (spot) {
          prefillDeliveryForSpot(spot);
        }
      });

      // Filter chips handler
      const filterWrap = document.getElementById("tourist-filter-shortcuts");
      if (filterWrap) {
        filterWrap.addEventListener("click", (e) => {
          const chip = e.target.closest("[data-map-filter]");
          if (!chip) return;
          filterWrap.querySelectorAll(".landmark-chip").forEach((c) => c.classList.remove("active"));
          chip.classList.add("active");
          const filterCat = chip.getAttribute("data-map-filter");

          homepageMarkers.forEach((m) => {
            const data = m.__landmarkData;
            if (filterCat === "all" || data.category === filterCat) {
              if (!homepageMapInstance.hasLayer(m)) {
                homepageMapInstance.addLayer(m);
              }
            } else {
              if (homepageMapInstance.hasLayer(m)) {
                homepageMapInstance.removeLayer(m);
              }
            }
          });
        });
      }

      // Locate user on homepage map
      const locateBtn = document.getElementById("tourist-map-locate-btn");
      if (locateBtn) {
        locateBtn.addEventListener("click", () => {
          if (!navigator.geolocation) {
            showToast("Geolocation is not supported by your browser.", "error");
            return;
          }
          locateBtn.disabled = true;
          locateBtn.textContent = "Locating...";
          navigator.geolocation.getCurrentPosition(
            (pos) => {
              locateBtn.disabled = false;
              locateBtn.textContent = "📍 Found You!";
              const lat = pos.coords.latitude;
              const lng = pos.coords.longitude;
              homepageMapInstance.setView([lat, lng], 14);
              const userMarker = L.marker([lat, lng]).addTo(homepageMapInstance);
              userMarker.bindPopup(`
                <div class="map-popup-card">
                  <div class="map-popup-title">📍 Your GPS Location</div>
                  <p class="map-popup-desc">${lat.toFixed(5)}, ${lng.toFixed(5)}</p>
                  <button type="button" class="map-popup-btn" data-book-delivery-custom="1">
                    🛵 Deliver Motorbike to My Location &rarr;
                  </button>
                </div>
              `).openPopup();
              userMarker.on("popupopen", () => {
                const b = document.querySelector("[data-book-delivery-custom]");
                if (b) {
                  b.onclick = () => {
                    prefillDeliveryForSpot({
                      id: "gps-me",
                      name: "My GPS Location",
                      lat: lat,
                      lng: lng,
                      address: `GPS Location (${lat.toFixed(5)}, ${lng.toFixed(5)})`
                    });
                  };
                }
              });
              showToast("Found your location on Camiguin island!", "success");
            },
            (err) => {
              locateBtn.disabled = false;
              locateBtn.textContent = "📍 Find My Location";
              showToast("Could not get GPS location: " + err.message, "error");
            },
            { enableHighAccuracy: true, timeout: 8000 }
          );
        });
      }
    }

    setTimeout(() => {
      if (homepageMapInstance) {
        homepageMapInstance.invalidateSize();
      }
    }, 300);
  }

  if (bookingPickup) {
    bookingPickup.addEventListener("change", () => {
      const pVal = bookingPickup.value || toIsoLocal(new Date());
      if (bookingReturn) {
        bookingReturn.min = pVal;
        if (bookingReturn.value && bookingReturn.value < pVal) {
          bookingReturn.value = pVal;
          syncDateWrap(bookingReturn);
        }
      }
      renderModalCalendar();
      refreshQuote();
    });
  }

  if (bookingReturn) {
    bookingReturn.addEventListener("change", () => {
      if (bookingReturn.value && bookingPickup && bookingReturn.value < bookingPickup.value) {
        bookingReturn.value = bookingPickup.value;
      }
      syncDateWrap(bookingReturn);
      renderModalCalendar();
      refreshQuote();
    });
  }

  [extraHelmetCheckbox, topBoxCheckbox].forEach((el) => {
    if (el) el.addEventListener("change", refreshQuote);
  });

  function syncCopyToClipboard(text) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "-9999px";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch (_) {
      return false;
    }
  }

  function openOfficialWalletApp(wallet) {
    const ua = navigator.userAgent || "";
    const isAndroid = /Android/i.test(ua);
    const isIos = /iPhone|iPad|iPod/i.test(ua);

    let deepLink = "";
    if (wallet === "gcash") {
      if (isAndroid) {
        deepLink =
          "intent://#Intent;scheme=gcash;package=com.globe.gcash.android;S.browser_fallback_url=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.globe.gcash.android;end";
      } else if (isIos) {
        deepLink = "gcash://";
      }
    } else if (wallet === "maya") {
      if (isAndroid) {
        deepLink =
          "intent://#Intent;scheme=paymaya;package=com.paymaya;S.browser_fallback_url=https%3A%2F%2Fplay.google.com%2Fstore%2Fapps%2Fdetails%3Fid%3Dcom.paymaya;end";
      } else if (isIos) {
        deepLink = "paymaya://";
      }
    }

    if (!deepLink) return;
    setTimeout(() => {
      try {
        window.location.href = deepLink;
      } catch (_) {}
    }, 180);
  }

  async function copyPaymentText(text, label, walletApp) {
    const cleanText = (text || "").trim();
    if (!cleanText) return;
    const digitsOnly = cleanText.replace(/[^\d+]/g, "") || cleanText;
    syncCopyToClipboard(digitsOnly);
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(digitsOnly);
      }
    } catch (_) {}
    if (walletApp === "gcash") {
      showToast(`GCash number (${digitsOnly}) copied! Opening GCash app...`, "success");
      openOfficialWalletApp("gcash");
    } else if (walletApp === "maya") {
      showToast(`Maya number (${digitsOnly}) copied! Opening Maya app...`, "success");
      openOfficialWalletApp("maya");
    } else {
      showToast(`${label} copied!`, "success");
    }
  }

  if (copyGcashBtn && paymentGcashNumber) {
    copyGcashBtn.addEventListener("click", () => {
      copyPaymentText(paymentGcashNumber.textContent.trim(), "GCash number", "gcash");
    });
  }
  if (copyMayaBtn && paymentMayaNumber) {
    copyMayaBtn.addEventListener("click", () => {
      copyPaymentText(paymentMayaNumber.textContent.trim(), "Maya number", "maya");
    });
  }
  if (bookingForm) {
    bookingForm.querySelectorAll('input[name="payment_channel"]').forEach((radio) => {
      radio.addEventListener("change", () => syncPaymentChannelUi(false));
    });
  }

  // Digital Contract & Signature Pad setup
  const licenseInput = document.getElementById("booking-license-photo");
  const licensePreviewWrap = document.getElementById("license-preview-container");
  const licensePreviewImg = document.getElementById("license-preview-img");
  const removeLicenseBtn = document.getElementById("remove-license-photo-btn");

  if (licenseInput) {
    licenseInput.addEventListener("change", () => {
      const file = licenseInput.files && licenseInput.files[0];
      if (file) {
        const reader = new FileReader();
        reader.onload = (e) => {
          if (licensePreviewImg) licensePreviewImg.src = e.target.result;
          if (licensePreviewWrap) licensePreviewWrap.classList.remove("hidden");
        };
        reader.readAsDataURL(file);
      } else {
        if (licensePreviewWrap) licensePreviewWrap.classList.add("hidden");
      }
    });
  }

  if (removeLicenseBtn && licenseInput) {
    removeLicenseBtn.addEventListener("click", () => {
      licenseInput.value = "";
      if (licensePreviewWrap) licensePreviewWrap.classList.add("hidden");
      if (licensePreviewImg) licensePreviewImg.src = "";
    });
  }

  // Auto-save & restore rider profile so returning tourists don't re-type info
  const CUSTOMER_PROFILE_KEY = "motoride_customer_profile";

  function saveCustomerProfile(p) {
    if (!p) return;
    try {
      localStorage.setItem(
        CUSTOMER_PROFILE_KEY,
        JSON.stringify({
          customer_name: (p.customer_name || "").trim(),
          customer_phone: (p.customer_phone || "").trim(),
          customer_address: (p.customer_address || "").trim(),
          license_number: (p.license_number || "").trim(),
          customer_email: (p.customer_email || "").trim(),
        })
      );
    } catch (_) {}
  }

  function getSavedCustomerProfile() {
    try {
      const raw = localStorage.getItem(CUSTOMER_PROFILE_KEY);
      if (!raw) return null;
      const data = JSON.parse(raw);
      if (data && typeof data === "object") return data;
    } catch (_) {}
    return null;
  }

  function restoreCustomerProfile() {
    const profile = getSavedCustomerProfile();
    const pill = document.getElementById("saved-customer-pill");
    if (!profile) {
      if (pill) pill.style.display = "none";
      return;
    }
    const nameEl = document.getElementById("booking-customer-name");
    const phoneEl = document.getElementById("booking-customer-phone");
    const addrEl = document.getElementById("booking-customer-address");
    const licEl = document.getElementById("booking-license-number");
    const emailEl = document.getElementById("booking-customer-email");

    let filledAny = false;
    if (nameEl && !nameEl.value && profile.customer_name) {
      nameEl.value = profile.customer_name;
      filledAny = true;
    }
    if (phoneEl && !phoneEl.value && profile.customer_phone) {
      phoneEl.value = profile.customer_phone;
      filledAny = true;
    }
    if (addrEl && !addrEl.value && profile.customer_address) {
      addrEl.value = profile.customer_address;
      filledAny = true;
    }
    if (licEl && !licEl.value && profile.license_number) {
      licEl.value = profile.license_number;
      filledAny = true;
    }
    if (emailEl && !emailEl.value && profile.customer_email) {
      emailEl.value = profile.customer_email;
      filledAny = true;
    }
    if (pill) pill.style.display = filledAny ? "inline" : "none";
  }

  function clearSavedCustomerProfile() {
    try {
      localStorage.removeItem(CUSTOMER_PROFILE_KEY);
    } catch (_) {}
    const nameEl = document.getElementById("booking-customer-name");
    const phoneEl = document.getElementById("booking-customer-phone");
    const addrEl = document.getElementById("booking-customer-address");
    const licEl = document.getElementById("booking-license-number");
    const emailEl = document.getElementById("booking-customer-email");
    if (nameEl) nameEl.value = "";
    if (phoneEl) phoneEl.value = "";
    if (addrEl) addrEl.value = "";
    if (licEl) licEl.value = "";
    if (emailEl) emailEl.value = "";
    const pill = document.getElementById("saved-customer-pill");
    if (pill) pill.style.display = "none";
    showToast("Saved rider information cleared.", "success");
  }

  const clearSavedCustomerBtn = document.getElementById("clear-saved-customer-btn");
  if (clearSavedCustomerBtn) {
    clearSavedCustomerBtn.addEventListener("click", (e) => {
      e.preventDefault();
      clearSavedCustomerProfile();
    });
  }

  const sigCanvas = document.getElementById("signature-pad");
  const sigStatus = document.getElementById("signature-status");
  const clearSigBtn = document.getElementById("clear-signature-btn");
  let isDrawingSig = false;
  let hasSigned = false;

  function initSignaturePad() {
    if (!sigCanvas) return;
    const ctx = sigCanvas.getContext("2d");
    if (!ctx) return;

    ctx.strokeStyle = "#0f172a";
    ctx.lineWidth = 2.5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    function getPos(e) {
      const rect = sigCanvas.getBoundingClientRect();
      const scaleX = sigCanvas.width / (rect.width || 1);
      const scaleY = sigCanvas.height / (rect.height || 1);
      if (e.touches && e.touches[0]) {
        return {
          x: (e.touches[0].clientX - rect.left) * scaleX,
          y: (e.touches[0].clientY - rect.top) * scaleY,
        };
      }
      return {
        x: (e.clientX - rect.left) * scaleX,
        y: (e.clientY - rect.top) * scaleY,
      };
    }

    function startDraw(e) {
      isDrawingSig = true;
      hasSigned = true;
      const pos = getPos(e);
      ctx.beginPath();
      ctx.moveTo(pos.x, pos.y);
      if (sigStatus) {
        sigStatus.textContent = "✓ Signature recorded";
        sigStatus.style.color = "#16a34a";
      }
    }

    function draw(e) {
      if (!isDrawingSig) return;
      if (e.cancelable) e.preventDefault();
      const pos = getPos(e);
      ctx.lineTo(pos.x, pos.y);
      ctx.stroke();
    }

    function stopDraw() {
      if (!isDrawingSig) return;
      isDrawingSig = false;
      ctx.closePath();
    }

    sigCanvas.addEventListener("mousedown", startDraw);
    sigCanvas.addEventListener("mousemove", draw);
    window.addEventListener("mouseup", stopDraw);

    sigCanvas.addEventListener("touchstart", (e) => {
      if (e.cancelable) e.preventDefault();
      startDraw(e);
    }, { passive: false });
    sigCanvas.addEventListener("touchmove", (e) => {
      if (e.cancelable) e.preventDefault();
      draw(e);
    }, { passive: false });
    sigCanvas.addEventListener("touchend", stopDraw);

    if (clearSigBtn) {
      clearSigBtn.addEventListener("click", () => {
        ctx.clearRect(0, 0, sigCanvas.width, sigCanvas.height);
        hasSigned = false;
        if (sigStatus) {
          sigStatus.textContent = "✍️ Sign above using finger or stylus";
          sigStatus.style.color = "";
        }
        const sigDataInput = document.getElementById("booking-signature-data");
        if (sigDataInput) sigDataInput.value = "";
      });
    }
  }

  initSignaturePad();

  if (bookingForm) {
    bookingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      bookingFormError.classList.add("hidden");
      bookingFormError.textContent = "";

      if (!bookingPickup.value || !bookingReturn.value) {
        bookingFormError.textContent = "Please select your pickup and return dates.";
        bookingFormError.classList.remove("hidden");
        if (!bookingReturn.value && bookingReturn) {
          bookingReturn.focus();
          try {
            bookingReturn.showPicker?.();
          } catch (_) {}
        }
        return;
      }

      const licenseFile = licenseInput && licenseInput.files ? licenseInput.files[0] : null;
      if (!licenseFile) {
        const msg = "Please upload a photo of your valid Philippine Driver's License or Foreign Driver's Permit.";
        bookingFormError.textContent = msg;
        bookingFormError.classList.remove("hidden");
        showToast(msg, "error");
        licenseInput?.focus();
        return;
      }

      if (sigCanvas && !hasSigned) {
        const msg = "Please sign your digital signature on the Rental Agreement pad before submitting.";
        bookingFormError.textContent = msg;
        bookingFormError.classList.remove("hidden");
        showToast(msg, "error");
        sigCanvas.scrollIntoView({ behavior: "smooth", block: "center" });
        return;
      }

      const contractAgree = document.getElementById("booking-contract-agree");
      if (contractAgree && !contractAgree.checked) {
        const msg = "Please agree to the Digital Rental Agreement before submitting.";
        bookingFormError.textContent = msg;
        bookingFormError.classList.remove("hidden");
        showToast(msg, "error");
        contractAgree.focus();
        return;
      }

      let sigData = "";
      if (sigCanvas && hasSigned) {
        try {
          sigData = sigCanvas.toDataURL("image/png");
        } catch (_) {}
      }

      const payload = {
        bike_id: Number(bookingBikeId.value),
        pickup_date: bookingPickup.value,
        return_date: bookingReturn.value,
        pickup_time: document.getElementById("booking-pickup-time").value,
        pickup_method: bookingPickupMethod.value,
        delivery_address: deliveryAddressInput.value.trim(),
        delivery_lat: document.getElementById("booking-delivery-lat")?.value || null,
        delivery_lng: document.getElementById("booking-delivery-lng")?.value || null,
        extra_helmet: extraHelmetCheckbox.checked,
        top_box: topBoxCheckbox.checked,
        customer_name: document.getElementById("booking-customer-name").value.trim(),
        customer_phone: document.getElementById("booking-customer-phone").value.trim(),
        customer_address: document.getElementById("booking-customer-address")?.value.trim() || "",
        license_number: document.getElementById("booking-license-number").value.trim(),
        customer_email: document.getElementById("booking-customer-email").value.trim(),
        notes: document.getElementById("booking-notes").value.trim(),
      };

      const q = state.latestQuote;
      const qrUrl = (shop.gcash_qr_url || "").trim();
      const gcashNum = (shop.gcash_number || "").trim();
      const mayaNum = (shop.maya_number || "").trim();
      const hasOnlineChannel = Boolean(qrUrl || gcashNum || mayaNum);
      const effectiveMode = String(
        (q && q.reservation_mode) || shop.reservation_mode || "required"
      ).toLowerCase();
      const paymentActive = Boolean(
        effectiveMode !== "off" &&
          ((q && q.reservation_configured && Number(q.reservation_fee || 0) > 0) || hasOnlineChannel)
      );
      let selectedChannel = paymentActive ? getSelectedPaymentChannel() : "pay_at_shop";
      if (paymentActive && effectiveMode === "required" && selectedChannel === "pay_at_shop") {
        selectedChannel = qrUrl || gcashNum ? "gcash" : "maya";
        selectPaymentChannel(selectedChannel);
      }
      const paymentReference = bookingPaymentRef ? bookingPaymentRef.value.trim() : "";
      const proofFile =
        bookingPaymentProof && bookingPaymentProof.files ? bookingPaymentProof.files[0] : null;

      if (paymentActive && selectedChannel !== "pay_at_shop") {
        if (selectedChannel === "paymongo") {
          // Automatic online payment via PayMongo: no manual receipt or reference number needed
        } else {
          if (paymentReference && paymentReference.length < 6) {
            const msg = "Please enter your full GCash / Maya Reference No. (at least 6 characters).";
            bookingFormError.textContent = msg;
            bookingFormError.classList.remove("hidden");
            showToast(msg, "error");
            bookingPaymentRef?.focus();
            return;
          }
          if (!paymentReference && !proofFile) {
            const msg =
              effectiveMode === "required"
                ? "Reservation fee is required: please pay via GCash/Maya and enter your Reference No. or upload your receipt screenshot before proceeding."
                : "Please enter your Reference No., upload a receipt screenshot, or choose 'Pay Full at Shop on Pickup'.";
            bookingFormError.textContent = msg;
            bookingFormError.classList.remove("hidden");
            showToast(msg, "error");
            bookingPaymentRef?.focus();
            return;
          }
        }
      }

      bookingSubmitBtn.disabled = true;
      bookingSubmitBtn.textContent = "Submitting...";

      try {
        let fetchOpts;
        if ((proofFile && paymentActive && selectedChannel !== "pay_at_shop") || licenseFile || sigData) {
          const fd = new FormData();
          Object.entries(payload).forEach(([k, v]) => {
            fd.append(k, typeof v === "boolean" ? (v ? "true" : "false") : String(v ?? ""));
          });
          fd.append("payment_channel", selectedChannel);
          fd.append("payment_reference", selectedChannel === "pay_at_shop" ? "" : paymentReference);
          if (proofFile) fd.append("payment_proof", proofFile);
          if (licenseFile) fd.append("license_photo", licenseFile);
          if (sigData) fd.append("signature_data", sigData);
          fd.append("contract_agreed", "1");
          fd.append("require_license_photo", "1");
          fetchOpts = { method: "POST", body: fd };
        } else {
          fetchOpts = {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...payload,
              payment_channel: selectedChannel,
              payment_reference: selectedChannel === "pay_at_shop" ? "" : paymentReference,
              signature_data: sigData,
              contract_agreed: true,
              require_license_photo: true,
            }),
          };
        }
        const res = await fetch("/api/bookings", fetchOpts);
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || "Could not submit booking.");
        }

        const booking = data.booking;
        saveCustomerProfile(payload);
        saveRecentTrip(booking);
        closeModal("booking-modal");
        bookingForm.reset();
        if (clearSigBtn) clearSigBtn.click();
        if (licensePreviewWrap) licensePreviewWrap.classList.add("hidden");
        syncReturnDateUi();
        deliveryAddressGroup.classList.add("hidden");
        deliveryAddressInput.required = false;

        showConfirmationModal(booking, data.checkout_url);
        loadFleet();
        showToast("Booking request submitted!", "success");
      } catch (err) {
        bookingFormError.textContent = err.message;
        bookingFormError.classList.remove("hidden");
      } finally {
        bookingSubmitBtn.disabled = false;
        bookingSubmitBtn.textContent = "Confirm Booking Request";
      }
    });
  }

  function formatStorefrontPickupLabel(method, address) {
    if (method === "benoni_port") {
      return `Benoni Port (Mahinog) (+₱200)${address ? ` — ${escapeHtml(address)}` : ""}`;
    }
    if (method === "balbagon_port") {
      return `Balbagon Port (Mambajao) (Free)${address ? ` — ${escapeHtml(address)}` : ""}`;
    }
    if (method === "airport") {
      return `Camiguin Airport (Mambajao) (Free)${address ? ` — ${escapeHtml(address)}` : ""}`;
    }
    if (method === "around_mambajao" || method === "mambajao") {
      return `Around Mambajao Delivery (Free)${address ? ` — ${escapeHtml(address)}` : ""}`;
    }
    if (method === "delivery") {
      return `Hotel / Resort Delivery${address ? ` (${escapeHtml(address)})` : ""}`;
    }
    return "Shop Pickup (Free)";
  }

  function showConfirmationModal(booking, checkoutUrl) {
    document.getElementById("confirm-booking-code").textContent = booking.booking_code;

    const payUrl = checkoutUrl || booking.payment_checkout_url;
    const onlineBox = document.getElementById("confirm-online-pay-box");
    const paymongoLink = document.getElementById("confirm-paymongo-link");
    if (onlineBox && paymongoLink) {
      if (payUrl && booking.payment_status !== "verified") {
        paymongoLink.href = payUrl;
        onlineBox.classList.remove("hidden");
      } else {
        onlineBox.classList.add("hidden");
      }
    }
    document.getElementById("confirm-summary").innerHTML = `
      <div><strong>Rental Shop:</strong> ${escapeHtml(booking.shop_name || "Verified Partner")} (${escapeHtml(booking.shop_municipality || "Camiguin")})</div>
      <div><strong>Motorbike:</strong> ${escapeHtml(booking.bike_name)}</div>
      ${booking.customer_address ? `<div><strong>Address:</strong> ${escapeHtml(booking.customer_address)}</div>` : ""}
      <div><strong>Dates:</strong> ${escapeHtml(booking.pickup_date)} to ${escapeHtml(booking.return_date)} (${booking.rental_days} day(s))</div>
      <div><strong>Pickup:</strong> ${escapeHtml(booking.pickup_time)} &bull; ${formatStorefrontPickupLabel(booking.pickup_method, booking.delivery_address)}</div>
      <div><strong>Total Rental:</strong> ${escapeHtml(formatMoney(booking.total_amount))}</div>
      ${Number(booking.reservation_fee || 0) > 0 ? `<div><strong>Down Payment (${escapeHtml((booking.payment_channel || "gcash").toUpperCase())}):</strong> ${escapeHtml(formatMoney(booking.reservation_fee))} (${escapeHtml(paymentStatusLabel(booking.payment_status))})${booking.payment_reference ? ` &bull; Ref # ${escapeHtml(booking.payment_reference)}` : ""}</div>` : ""}
      <div><strong>Balance Due on Pickup:</strong> ${escapeHtml(formatMoney(booking.balance_due !== undefined && booking.balance_due !== null ? booking.balance_due : booking.total_amount))}</div>
      <div><strong>Status:</strong> <span class="badge badge-pending">Pending Shop Confirmation</span></div>
    `;

    const trackLink = document.getElementById("confirm-track-link");
    trackLink.href = `/bookings?code=${encodeURIComponent(booking.booking_code)}&phone=${encodeURIComponent(booking.customer_phone)}`;

    const contractLink = document.getElementById("confirm-contract-link");
    if (contractLink) {
      contractLink.href = `/bookings/${encodeURIComponent(booking.booking_code)}/contract?phone=${encodeURIComponent(booking.customer_phone)}`;
      contractLink.classList.remove("hidden");
    }

    const waBtn = document.getElementById("confirm-whatsapp-link");
    const waDigits = (booking.shop_whatsapp || shop.whatsapp_number || "").replace(/\D+/g, "");
    if (waDigits) {
      const msg = encodeURIComponent(
        `Hi ${booking.shop_name || shop.shop_name || "Motorbike Rentals Camiguin"}! I submitted booking ${booking.booking_code} for ${booking.bike_name} (${booking.pickup_date} to ${booking.return_date}). Total: ${formatMoney(booking.total_amount)}.`
      );
      waBtn.href = `https://wa.me/${waDigits}?text=${msg}`;
      waBtn.classList.remove("hidden");
    } else {
      waBtn.classList.add("hidden");
    }

    openModal("confirmation-modal");
  }

  const copyCodeBtn = document.getElementById("copy-code-btn");
  if (copyCodeBtn) {
    copyCodeBtn.addEventListener("click", async () => {
      const code = document.getElementById("confirm-booking-code").textContent;
      try {
        await navigator.clipboard.writeText(code);
        showToast("Booking code copied!", "success");
      } catch (_) {
        showToast(`Code: ${code}`);
      }
    });
  }

  document.addEventListener("click", (e) => {
    const guideBtn = e.target.closest("[data-guide-category]");
    if (guideBtn) {
      const cat = guideBtn.getAttribute("data-guide-category");
      const fleetEl = document.getElementById("fleet");
      if (fleetEl) {
        fleetEl.scrollIntoView({ behavior: "smooth" });
      }
      const pill = document.querySelector(`#category-pills [data-category="${cat}"]`);
      if (pill) {
        pill.click();
      }
    }
  });

  bindDatePickerPlaceholder(searchReturnInput);
  bindDatePickerPlaceholder(bookingReturn);
  initDefaultDates();
  initHomepageTouristMap();
  if (
    initialBootstrap &&
    Array.isArray(initialBootstrap.shops) &&
    Array.isArray(initialBootstrap.bikes)
  ) {
    state.shops = initialBootstrap.shops;
    state.bikes = initialBootstrap.bikes;
    populateShopFilterOptions();
    renderFleet();
  } else {
    loadPublicShops();
    loadFleet();
  }
})();
