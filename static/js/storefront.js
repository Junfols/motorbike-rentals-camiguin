(function () {
  "use strict";

  const { escapeHtml, formatMoney, showToast, openModal, closeModal, saveRecentTrip, shop } =
    window.MotoRide;

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
  const bookingFormError = document.getElementById("booking-form-error");
  const bookingSubmitBtn = document.getElementById("booking-submit-btn");

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
  };

  function toIsoLocal(dt) {
    const y = dt.getFullYear();
    const m = String(dt.getMonth() + 1).padStart(2, "0");
    const d = String(dt.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  function initDefaultDates() {
    const today = new Date();
    const returnDt = new Date(today);
    returnDt.setDate(today.getDate() + 2);

    const todayStr = toIsoLocal(today);
    const returnStr = toIsoLocal(returnDt);

    state.pickupDate = todayStr;
    state.returnDate = returnStr;

    [searchPickupInput, bookingPickup].forEach((el) => {
      if (el) {
        el.min = todayStr;
        el.value = todayStr;
      }
    });
    [searchReturnInput, bookingReturn].forEach((el) => {
      if (el) {
        el.min = todayStr;
        el.value = returnStr;
      }
    });
  }

  function calcDaysDiff(pStr, rStr) {
    if (!pStr || !rStr) return 1;
    const p = new Date(`${pStr}T00:00:00`);
    const r = new Date(`${rStr}T00:00:00`);
    const diff = Math.round((r - p) / 86400000);
    return Math.max(1, diff);
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
    const params = new URLSearchParams({
      category: state.category,
      transmission: state.transmission,
      municipality: state.municipality,
      q: state.q,
      sort: state.sort,
      pickup_date: state.pickupDate,
      return_date: state.returnDate,
      available_only: state.availableOnly ? "1" : "0",
    });
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
    const days = calcDaysDiff(state.pickupDate, state.returnDate);
    const dayWord = days === 1 ? "day" : "days";
    if (fleetDateSummary) {
      fleetDateSummary.textContent =
        `${state.bikes.length} model(s) for ${state.pickupDate} to ${state.returnDate} (${days} ${dayWord})`;
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

        const weeklyLine =
          bike.weekly_rate > 0
            ? `<div class="bike-price-weekly">Weekly: ${escapeHtml(formatMoney(bike.weekly_rate))}</div>`
            : "";

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
              <div class="bike-card-footer">
                <div>
                  <div class="bike-price-main">
                    ${escapeHtml(formatMoney(bike.daily_rate))}<span class="bike-price-unit">/day</span>
                  </div>
                  ${weeklyLine}
                </div>
                <button
                  type="button"
                  class="btn ${bike.is_available ? "btn-primary" : "btn-outline"}"
                  data-open-bike="${bike.id}"
                >
                  ${bike.is_available ? "Book Now" : "Check Dates"}
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
      const params = new URLSearchParams({
        pickup_date: state.pickupDate,
        return_date: state.returnDate,
      });
      const res = await fetch(`/api/bikes/${bikeId}?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Could not load bike details.");
      }

      const bike = data.bike;
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
      document.getElementById("modal-daily-rate").textContent = `${formatMoney(bike.daily_rate)} / day`;
      document.getElementById("modal-weekly-rate").textContent =
        bike.weekly_rate > 0 ? `${formatMoney(bike.weekly_rate)} / 7 days` : "Standard daily rate";
      document.getElementById("modal-deposit-rate").textContent = formatMoney(bike.deposit);

      const rangesEl = document.getElementById("modal-booked-ranges");
      const ranges = bike.booked_ranges || [];
      if (!ranges.length) {
        rangesEl.innerHTML = `<span class="text-muted">No upcoming bookings yet — wide open!</span>`;
      } else {
        rangesEl.innerHTML = ranges
          .map(
            (r) =>
              `<span class="booked-range-pill">${escapeHtml(r.pickup_date)} &rarr; ${escapeHtml(r.return_date)}</span>`
          )
          .join("");
      }

      bookingPickup.value = state.pickupDate;
      bookingReturn.value = state.returnDate;
      const isDelivery = bookingPickupMethod.value === "delivery";
      deliveryAddressGroup.classList.toggle("hidden", !isDelivery);
      deliveryAddressInput.required = isDelivery;
      bookingSubmitBtn.textContent = "Confirm Booking Request";
      openModal("booking-modal");
      await refreshQuote();
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  async function refreshQuote() {
    const bikeId = bookingBikeId.value;
    const pDate = bookingPickup.value;
    const rDate = bookingReturn.value;
    if (!bikeId || !pDate || !rDate) return;

    if (rDate < pDate) {
      bookingReturn.value = pDate;
    }

    const params = new URLSearchParams({
      bike_id: bikeId,
      pickup_date: bookingPickup.value,
      return_date: bookingReturn.value,
      pickup_method: bookingPickupMethod.value,
      extra_helmet: extraHelmetCheckbox.checked ? "1" : "0",
      top_box: topBoxCheckbox.checked ? "1" : "0",
    });

    try {
      const res = await fetch(`/api/quote?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = data.error || "Invalid dates";
        quoteLines.innerHTML = "";
        bookingSubmitBtn.disabled = true;
        return;
      }

      const q = data.quote;
      if (q.is_available) {
        quoteAvailability.className = "quote-availability ok";
        quoteAvailability.textContent = `Available (${q.available_units} of ${q.units_count} unit(s) open)`;
        bookingSubmitBtn.disabled = false;
      } else if (q.bike_status !== "available") {
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = "Currently under maintenance";
        bookingSubmitBtn.disabled = true;
      } else {
        quoteAvailability.className = "quote-availability bad";
        quoteAvailability.textContent = "Already booked for these dates — try another date range";
        bookingSubmitBtn.disabled = true;
      }

      const dayWord = q.rental_days === 1 ? "day" : "days";
      let linesHtml = `
        <div class="quote-line">
          <span>Rental (${q.rental_days} ${dayWord})</span>
          <span>${escapeHtml(formatMoney(q.base_subtotal))}</span>
        </div>
      `;
      if (q.discount_saved > 0) {
        linesHtml += `
          <div class="quote-line discount">
            <span>Weekly Rate Savings</span>
            <span>-${escapeHtml(formatMoney(q.discount_saved))}</span>
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
        <div class="quote-line deposit">
          <span>Refundable Security Deposit (paid at pickup)</span>
          <span>${escapeHtml(formatMoney(q.deposit_amount))}</span>
        </div>
      `;
      quoteLines.innerHTML = linesHtml;
    } catch (_) {
      quoteAvailability.className = "quote-availability bad";
      quoteAvailability.textContent = "Unable to calculate quote right now.";
    }
  }

  // Event Listeners
  if (searchForm) {
    searchForm.addEventListener("submit", (event) => {
      event.preventDefault();
      if (searchReturnInput.value < searchPickupInput.value) {
        searchReturnInput.value = searchPickupInput.value;
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
      if (searchReturnInput.value < searchPickupInput.value) {
        searchReturnInput.value = searchPickupInput.value;
      }
      state.pickupDate = searchPickupInput.value;
      state.returnDate = searchReturnInput.value;
      loadFleet();
    });
  }

  if (searchReturnInput) {
    searchReturnInput.addEventListener("change", () => {
      if (searchReturnInput.value < searchPickupInput.value) {
        searchReturnInput.value = searchPickupInput.value;
      }
      state.pickupDate = searchPickupInput.value;
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
      const btn = event.target.closest("[data-open-bike]");
      if (!btn) return;
      openBikeModal(Number(btn.getAttribute("data-open-bike")));
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

  [bookingPickup, bookingReturn, extraHelmetCheckbox, topBoxCheckbox].forEach((el) => {
    if (el) el.addEventListener("change", refreshQuote);
  });

  if (bookingForm) {
    bookingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      bookingFormError.classList.add("hidden");
      bookingFormError.textContent = "";

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

      bookingSubmitBtn.disabled = true;
      bookingSubmitBtn.textContent = "Submitting...";

      try {
        const res = await fetch("/api/bookings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.error || "Could not submit booking.");
        }

        const booking = data.booking;
        saveRecentTrip(booking);
        closeModal("booking-modal");
        bookingForm.reset();
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

  initDefaultDates();
  loadPublicShops();
  loadFleet();
})();
