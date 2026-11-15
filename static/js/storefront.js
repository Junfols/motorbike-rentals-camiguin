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
  const channelShopWrap = document.getElementById("channel-shop-wrap");
  const paymentProofFields = document.getElementById("payment-proof-fields");
  const bookingPaymentRef = document.getElementById("booking-payment-reference");
  const bookingPaymentProof = document.getElementById("booking-payment-proof");

  const state = {
    category: "All",
    transmission: "All",
    municipality: "All",
    shopId: "",
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
      q && q.reservation_percent !== undefined ? q.reservation_percent : shop.reservation_percent || 10
    );
    const isConfigured = Boolean((q && q.reservation_configured) || hasGcash || hasMaya);
    const fallbackDaily = state.currentBike ? Number(state.currentBike.daily_rate || 0) : 0;
    const feeAmount =
      q && Number(q.reservation_fee || 0) > 0
        ? Number(q.reservation_fee)
        : Math.round(fallbackDaily * (percent / 100) * 100) / 100;
    const active = Boolean(mode !== "off" && isConfigured && feeAmount > 0);
    paymentQrSection.classList.toggle("hidden", !active);
    if (!active) {
      selectPaymentChannel("pay_at_shop");
      if (paymentProofFields) paymentProofFields.classList.add("hidden");
      return;
    }

    const isReq = mode === "required";
    const preferredOnline = hasGcash ? "gcash" : hasMaya ? "maya" : "pay_at_shop";

    if (paymentModePill) {
      paymentModePill.textContent = isReq ? "Required" : "Optional";
      paymentModePill.className = isReq ? "status-pill-inline ready" : "status-pill-inline muted";
    }
    if (paymentFeeBadge) {
      paymentFeeBadge.textContent = `Pay Now (${percent}%): ${formatMoney(feeAmount)}`;
    }
    if (paymentInstructionsText) {
      paymentInstructionsText.textContent =
        (shop.payment_instructions || "").trim() ||
        "Scan the QR code or send the reservation fee below, then enter your Reference No. before submitting.";
    }
    if (paymentQrBox && paymentQrImg) {
      if (qrUrl) {
        paymentQrImg.src = qrUrl;
        paymentQrBox.classList.remove("hidden");
      } else {
        paymentQrImg.src = "";
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
    if (paymentMayaRow && paymentMayaNumber) {
      if (mayaNum) {
        paymentMayaNumber.textContent = mayaNum;
        paymentMayaRow.classList.remove("hidden");
      } else {
        paymentMayaRow.classList.add("hidden");
      }
    }

    if (channelGcashWrap) channelGcashWrap.classList.toggle("hidden", !hasGcash);
    if (channelMayaWrap) channelMayaWrap.classList.toggle("hidden", !hasMaya);
    if (channelShopWrap) channelShopWrap.classList.toggle("hidden", isReq);

    let current = getSelectedPaymentChannel();
    if (resetDefault || wasHidden) {
      current = preferredOnline;
      selectPaymentChannel(current);
    } else if (isReq && current === "pay_at_shop") {
      current = preferredOnline;
      selectPaymentChannel(current);
    } else if (current === "gcash" && !hasGcash) {
      current = hasMaya ? "maya" : "pay_at_shop";
      selectPaymentChannel(current);
    } else if (current === "maya" && !hasMaya) {
      current = hasGcash ? "gcash" : "pay_at_shop";
      selectPaymentChannel(current);
    }

    if (paymentProofFields) {
      paymentProofFields.classList.toggle("hidden", current === "pay_at_shop");
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

  async function loadPublicShops() {
    if (!filterShop) return;
    try {
      const res = await fetch("/api/shops");
      const data = await res.json();
      if (!res.ok) return;
      state.shops = data.shops || [];
      const currentVal = filterShop.value;
      filterShop.innerHTML =
        `<option value="">All Rental Shops (${state.shops.length})</option>` +
        state.shops
          .map(
            (s) =>
              `<option value="${s.id}">${escapeHtml(s.shop_name)} (${escapeHtml(s.municipality)})</option>`
          )
          .join("");
      filterShop.value = currentVal;
    } catch (_) {
      // Keep default option offline
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
        }        const bookedSummary = formatBookedRangesLabel(bike.booked_ranges, 2);
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

        return `
          <article class="bike-card" data-bike-id="${bike.id}">
            <div class="bike-card-media">
              <img src="${escapeHtml(bike.image_url)}" alt="${escapeHtml(bike.name)}" loading="lazy">
              <div class="bike-card-top-badges">
                <span class="badge badge-dark">${escapeHtml(bike.category)}</span>
                ${statusBadge}
              </div>
            </div>
            <div class="bike-card-body">
              <div class="shop-pill-line">
                <span>${escapeHtml(bike.shop_name || "Verified Shop")} &bull; ${escapeHtml(bike.shop_municipality || "Camiguin")}</span>
              </div>
              <div class="bike-card-title-row">
                <h3 class="bike-card-title">${escapeHtml(bike.name)}</h3>
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

  async function openBikeModal(bikeId) {
    bookingFormError.classList.add("hidden");
    bookingFormError.textContent = "";

    try {
      const todayStr = toIsoLocal(new Date());
      const effectivePickup = state.pickupDate || todayStr;
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
      bookingBikeId.value = bike.id;
      document.getElementById("modal-bike-category").textContent = bike.category;
      document.getElementById("modal-bike-name").textContent = bike.name;
      const img = document.getElementById("modal-bike-img");
      img.src = bike.image_url;
      img.alt = bike.name;

      document.getElementById("modal-shop-name").textContent = bike.shop_name || "Verified Partner Shop";
      document.getElementById("modal-shop-location").textContent =
        [bike.shop_address, bike.shop_municipality].filter(Boolean).join(" • ");
      document.getElementById("modal-shop-phone").textContent =
        bike.shop_phone ? `Contact: ${bike.shop_phone}` : "";

      if (deliveryOptionLabel) {
        const fee = bike.shop_delivery_fee ?? shop.delivery_fee ?? 250;
        deliveryOptionLabel.textContent = `Resort / Port Delivery (+${formatMoney(fee)})`;
      }

      document.getElementById("modal-bike-specs").innerHTML = `
        <span class="spec-pill">${bike.engine_cc}cc</span>
        <span class="spec-pill">${escapeHtml(bike.transmission)}</span>
        <span class="spec-pill">${escapeHtml(bike.fuel_type)}</span>
        <span class="spec-pill">${bike.units_count} fleet unit(s)</span>
      `;
      document.getElementById("modal-bike-desc").textContent = bike.description || "";
      document.getElementById("modal-bike-inclusions").textContent = bike.inclusions || "2 Helmets";
      document.getElementById("modal-daily-rate").textContent = `${formatMoney(bike.daily_rate)} / day`;      document.getElementById("modal-deposit-rate").textContent = formatMoney(bike.deposit);

      const rangesEl = document.getElementById("modal-booked-ranges");
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

      const modalTodayStr = toIsoLocal(new Date());
      const modalPickupStr = state.pickupDate || modalTodayStr;
      bookingPickup.min = modalTodayStr;
      bookingPickup.value = modalPickupStr;
      bookingReturn.min = modalPickupStr;
      bookingReturn.value = state.returnDate || "";
      syncReturnDateUi();
      renderModalCalendar();
      const isDelivery = bookingPickupMethod.value === "delivery";
      deliveryAddressGroup.classList.toggle("hidden", !isDelivery);
      deliveryAddressInput.required = isDelivery;
      if (bookingPaymentRef) bookingPaymentRef.value = "";
      if (bookingPaymentProof) bookingPaymentProof.value = "";
      bookingSubmitBtn.textContent = "Confirm Booking Request";
      openModal("booking-modal");
      await refreshQuote();
      syncPaymentChannelUi(true);
    } catch (err) {
      showToast(err.message, "error");
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
      `;</span>
          </div>
        `;
      }
      if (q.addons_total > 0) {
        linesHtml += `
          <div class="quote-line">
            <span>Add-ons (${q.rental_days} ${dayWord})</span>
            <span>${escapeHtml(formatMoney(q.addons_total))}</span>
          </div>
        `;
      }
      if (q.delivery_total > 0) {
        linesHtml += `
          <div class="quote-line">
            <span>Resort / Port Delivery</span>
            <span>${escapeHtml(formatMoney(q.delivery_total))}</span>
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
        linesHtml += `
          <div class="quote-line">
            <span>Reservation Fee (${q.reservation_percent}% via GCash/Maya)</span>
            <span>${escapeHtml(formatMoney(q.reservation_fee))}</span>
          </div>
          <div class="quote-line">
            <span>Remaining Balance Due at Pickup</span>
            <span>${escapeHtml(formatMoney(q.balance_due))}</span>
          </div>
        `;
      }
      linesHtml += `
        <div class="quote-line deposit">
          <span>Refundable Security Deposit (paid at pickup)</span>
          <span>${escapeHtml(formatMoney(q.deposit_amount))}</span>
        </div>
      `;
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
      state.shopId = filterShop.value;
      loadFleet();
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
      const btn = event.target.closest("[data-open-bike]");
      if (!btn) return;
      openBikeModal(Number(btn.getAttribute("data-open-bike")));
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

  if (bookingPickupMethod) {
    bookingPickupMethod.addEventListener("change", () => {
      const isDelivery = bookingPickupMethod.value === "delivery";
      deliveryAddressGroup.classList.toggle("hidden", !isDelivery);
      deliveryAddressInput.required = isDelivery;
      refreshQuote();
    });
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

  async function copyPaymentText(text, label) {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
      showToast(`${label} copied!`, "success");
    } catch (_) {
      showToast(`${label}: ${text}`, "success");
    }
  }

  if (copyGcashBtn && paymentGcashNumber) {
    copyGcashBtn.addEventListener("click", () => {
      copyPaymentText(paymentGcashNumber.textContent.trim(), "GCash number");
    });
  }
  if (copyMayaBtn && paymentMayaNumber) {
    copyMayaBtn.addEventListener("click", () => {
      copyPaymentText(paymentMayaNumber.textContent.trim(), "Maya number");
    });
  }
  if (bookingForm) {
    bookingForm.querySelectorAll('input[name="payment_channel"]').forEach((radio) => {
      radio.addEventListener("change", () => syncPaymentChannelUi(false));
    });
  }

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

      const payload = {
        bike_id: Number(bookingBikeId.value),
        pickup_date: bookingPickup.value,
        return_date: bookingReturn.value,
        pickup_time: document.getElementById("booking-pickup-time").value,
        pickup_method: bookingPickupMethod.value,
        delivery_address: deliveryAddressInput.value.trim(),
        extra_helmet: extraHelmetCheckbox.checked,
        top_box: topBoxCheckbox.checked,
        customer_name: document.getElementById("booking-customer-name").value.trim(),
        customer_phone: document.getElementById("booking-customer-phone").value.trim(),
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
              ? "Reservation fee is required: please pay via GCash and enter your Reference No. or upload your receipt screenshot before proceeding."
              : "Please enter your Reference No., upload a receipt screenshot, or choose 'Pay Full at Shop on Pickup'.";
          bookingFormError.textContent = msg;
          bookingFormError.classList.remove("hidden");
          showToast(msg, "error");
          bookingPaymentRef?.focus();
          return;
        }
      }

      bookingSubmitBtn.disabled = true;
      bookingSubmitBtn.textContent = "Submitting...";

      try {
        let fetchOpts;
        if (proofFile && paymentActive && selectedChannel !== "pay_at_shop") {
          const fd = new FormData();
          Object.entries(payload).forEach(([k, v]) => {
            fd.append(k, typeof v === "boolean" ? (v ? "true" : "false") : String(v ?? ""));
          });
          fd.append("payment_channel", selectedChannel);
          fd.append("payment_reference", paymentReference);
          fd.append("payment_proof", proofFile);
          fetchOpts = { method: "POST", body: fd };
        } else {
          fetchOpts = {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...payload,
              payment_channel: selectedChannel,
              payment_reference: selectedChannel === "pay_at_shop" ? "" : paymentReference,
            }),
          };
        }
        const res = await fetch("/api/bookings", fetchOpts);
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || "Could not submit booking.");
        }

        const booking = data.booking;
        saveRecentTrip(booking);
        closeModal("booking-modal");
        bookingForm.reset();
        syncReturnDateUi();
        deliveryAddressGroup.classList.add("hidden");
        deliveryAddressInput.required = false;

        showConfirmationModal(booking);
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

  function showConfirmationModal(booking) {
    document.getElementById("confirm-booking-code").textContent = booking.booking_code;
    document.getElementById("confirm-summary").innerHTML = `
      <div><strong>Rental Shop:</strong> ${escapeHtml(booking.shop_name || "Verified Partner")} (${escapeHtml(booking.shop_municipality || "Camiguin")})</div>
      <div><strong>Motorbike:</strong> ${escapeHtml(booking.bike_name)}</div>
      <div><strong>Dates:</strong> ${escapeHtml(booking.pickup_date)} to ${escapeHtml(booking.return_date)} (${booking.rental_days} day(s))</div>
      <div><strong>Pickup:</strong> ${escapeHtml(booking.pickup_time)} &bull; ${booking.pickup_method === "delivery" ? `Delivery (${escapeHtml(booking.delivery_address)})` : "Shop Pickup"}</div>
      <div><strong>Total Rental:</strong> ${escapeHtml(formatMoney(booking.total_amount))}</div>
      ${Number(booking.reservation_fee || 0) > 0 ? `<div><strong>Reservation Fee (${escapeHtml((booking.payment_channel || "gcash").toUpperCase())}):</strong> ${escapeHtml(formatMoney(booking.reservation_fee))} (${escapeHtml(paymentStatusLabel(booking.payment_status))})${booking.payment_reference ? ` &bull; Ref # ${escapeHtml(booking.payment_reference)}` : ""}</div>` : ""}
      <div><strong>Balance Due on Pickup:</strong> ${escapeHtml(formatMoney(booking.balance_due !== undefined && booking.balance_due !== null ? booking.balance_due : booking.total_amount))}</div>
      <div><strong>Refundable Deposit:</strong> ${escapeHtml(formatMoney(booking.deposit_amount))}</div>
      <div><strong>Status:</strong> <span class="badge badge-pending">Pending Shop Confirmation</span></div>
    `;

    const trackLink = document.getElementById("confirm-track-link");
    trackLink.href = `/bookings?code=${encodeURIComponent(booking.booking_code)}&phone=${encodeURIComponent(booking.customer_phone)}`;

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

  bindDatePickerPlaceholder(searchReturnInput);
  bindDatePickerPlaceholder(bookingReturn);
  initDefaultDates();
  loadPublicShops();
  loadFleet();
})();
