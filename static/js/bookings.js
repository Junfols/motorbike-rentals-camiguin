(function () {
  "use strict";

  const { escapeHtml, formatMoney, showToast, saveRecentTrip, shop } = window.MotoRide;

  const lookupForm = document.getElementById("lookup-form");
  const codeInput = document.getElementById("lookup-code");
  const phoneInput = document.getElementById("lookup-phone");
  const lookupError = document.getElementById("lookup-error");
  const lookupResult = document.getElementById("lookup-result");
  const savedListEl = document.getElementById("saved-trips-list");
  const clearSavedBtn = document.getElementById("clear-saved-trips-btn");

  const STORAGE_KEY = "motoride_recent_trips";

  function statusLabel(status) {
    const labels = {
      pending: "Pending Confirmation",
      confirmed: "Confirmed",
      active: "Active / Picked Up",
      completed: "Completed",
      cancelled: "Cancelled",
    };
    return labels[status] || status;
  }

  function getSavedTrips() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    } catch (_) {
      return [];
    }
  }

  function renderSavedTrips() {
    const trips = getSavedTrips();
    clearSavedBtn.classList.toggle("hidden", trips.length === 0);
    if (!trips.length) {
      savedListEl.innerHTML = `
        <div class="empty-state">
          No recent bookings saved on this device yet. <a href="/" class="link-btn">Browse motorbikes &rarr;</a>
        </div>
      `;
      return;
    }

    savedListEl.innerHTML = trips
      .map(
        (t) => `
          <div class="saved-trip-mini">
            <div>
              <strong>${escapeHtml(t.booking_code)}</strong> &bull; ${escapeHtml(t.bike_name)}
              <div class="text-muted">${escapeHtml(t.pickup_date)} to ${escapeHtml(t.return_date)} &bull; ${escapeHtml(formatMoney(t.total_amount))}</div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
              <span class="badge badge-${escapeHtml(t.status)}">${escapeHtml(statusLabel(t.status))}</span>
              <button
                type="button"
                class="btn btn-sm btn-outline"
                data-check-code="${escapeHtml(t.booking_code)}"
                data-check-phone="${escapeHtml(t.customer_phone)}"
              >
                Check Status
              </button>
            </div>
          </div>
        `
      )
      .join("");
  }

  async function runLookup(code, phone) {
    lookupError.classList.add("hidden");
    lookupError.textContent = "";

    try {
      const params = new URLSearchParams({ code: code.trim(), phone: phone.trim() });
      const res = await fetch(`/api/bookings/lookup?${params.toString()}`);
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.error || "Booking not found.");
      }

      const b = data.booking;
      saveRecentTrip(b);
      renderSavedTrips();
      renderLookupResult(b);
    } catch (err) {
      lookupResult.classList.add("hidden");
      lookupError.textContent = err.message;
      lookupError.classList.remove("hidden");
    }
  }

  function renderLookupResult(b) {
    const canCancel = b.status === "pending";
    const waDigits = (b.shop_whatsapp || shop.whatsapp_number || "").replace(/\D+/g, "");
    const waLink = waDigits
      ? `https://wa.me/${waDigits}?text=${encodeURIComponent(
          `Hi ${b.shop_name || shop.shop_name || "Motorbike Rentals Camiguin"}, following up on booking ${b.booking_code} (${b.bike_name}).`
        )}`
      : "";

    lookupResult.innerHTML = `
      <div class="trip-card">
        <div class="trip-card-head">
          <div>
            <span class="text-muted">Booking Reference</span>
            <h3 style="margin:2px 0 0;">${escapeHtml(b.booking_code)}</h3>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            ${(Number(b.reservation_fee || 0) > 0 || (b.payment_status && b.payment_status !== "unpaid")) ? `<span class="badge badge-${escapeHtml(b.payment_status || "unpaid")}">${escapeHtml(window.MotoRide && window.MotoRide.paymentStatusLabel ? window.MotoRide.paymentStatusLabel(b.payment_status) : (b.payment_status || "unpaid"))}</span>` : ""}
            <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
          </div>
        </div>

        <div class="trip-bike-row">
          <img src="${escapeHtml(b.bike_image || "/static/images/bike-click125.jpg")}" alt="${escapeHtml(b.bike_name)}" class="trip-bike-thumb">
          <div>
            <strong>${escapeHtml(b.bike_name)}</strong>
            <div class="text-muted">${escapeHtml(b.bike_category || "")} &bull; ${escapeHtml(b.bike_transmission || "")}</div>
            ${b.shop_name ? `<div class="text-muted"><strong>Shop:</strong> ${escapeHtml(b.shop_name)} (${escapeHtml(b.shop_municipality || "")})</div>` : ""}
            ${b.plate_number ? `<div class="text-muted">Plate / Unit: ${escapeHtml(b.plate_number)}</div>` : ""}
          </div>
        </div>

        <div class="trip-details-grid">
          <div>
            <span class="trip-detail-label">Rider</span>
            <strong>${escapeHtml(b.customer_name)}</strong>
          </div>
          <div>
            <span class="trip-detail-label">Rental Dates</span>
            <strong>${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)} (${b.rental_days}d)</strong>
          </div>
          <div>
            <span class="trip-detail-label">Pickup</span>
            <strong>${escapeHtml(b.pickup_time)} &bull; ${b.pickup_method === "delivery" ? `Delivery` : "Shop Pickup"}</strong>
          </div>
          <div>
            <span class="trip-detail-label">Total Rental</span>
            <strong>${escapeHtml(formatMoney(b.total_amount))}</strong>
          </div>
          <div>
            <span class="trip-detail-label">Balance Due on Pickup</span>
            <strong>${escapeHtml(formatMoney(b.balance_due !== undefined && b.balance_due !== null ? b.balance_due : b.total_amount))}</strong>
            ${Number(b.reservation_fee || 0) > 0 ? `<div class="text-muted">Reservation fee: ${escapeHtml(formatMoney(b.reservation_fee))}</div>` : ""}
          </div>
          <div>
            <span class="trip-detail-label">Security Deposit</span>
            <strong>${escapeHtml(formatMoney(b.deposit_amount))}</strong>
          </div>
          <div>
            <span class="trip-detail-label">License #</span>
            <strong>${escapeHtml(b.license_number)}</strong>
          </div>
        </div>

        ${(b.payment_reference || b.payment_proof_url) ? `<p class="text-muted"><strong>Reservation Payment:</strong> ${escapeHtml((b.payment_channel || "gcash").toUpperCase())}${b.payment_reference ? ` &bull; Ref # ${escapeHtml(b.payment_reference)}` : ""}${b.payment_proof_url ? ` &bull; <a href="${escapeHtml(b.payment_proof_url)}" target="_blank" rel="noopener" class="payment-proof-link">View Receipt</a>` : ""}</p>` : ""}
        ${b.delivery_address ? `<p class="text-muted"><strong>Delivery Address:</strong> ${escapeHtml(b.delivery_address)}</p>` : ""}
        ${b.admin_notes ? `<div class="info-box"><h4>Shop Note</h4><p>${escapeHtml(b.admin_notes)}</p></div>` : ""}

        <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:12px;">
          ${
            canCancel
              ? `<button type="button" class="btn btn-danger btn-sm" id="cancel-trip-btn" data-code="${escapeHtml(b.booking_code)}" data-phone="${escapeHtml(b.customer_phone)}">Cancel Request</button>`
              : ""
          }
          ${
            waLink
              ? `<a href="${escapeHtml(waLink)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">Message Shop on WhatsApp</a>`
              : ""
          }
        </div>
      </div>
    `;
    lookupResult.classList.remove("hidden");
  }

  lookupForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runLookup(codeInput.value, phoneInput.value);
  });

  savedListEl.addEventListener("click", (event) => {
    const btn = event.target.closest("[data-check-code]");
    if (!btn) return;
    const code = btn.getAttribute("data-check-code");
    const phone = btn.getAttribute("data-check-phone");
    codeInput.value = code;
    phoneInput.value = phone;
    runLookup(code, phone);
  });

  lookupResult.addEventListener("click", async (event) => {
    const btn = event.target.closest("#cancel-trip-btn");
    if (!btn) return;
    if (!window.confirm("Are you sure you want to cancel this pending booking?")) return;

    const bookingCode = btn.getAttribute("data-code");
    const customerPhone = btn.getAttribute("data-phone");
    btn.disabled = true;

    try {
      const res = await fetch("/api/bookings/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ booking_code: bookingCode, customer_phone: customerPhone }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Could not cancel booking.");
      saveRecentTrip(data.booking);
      renderSavedTrips();
      renderLookupResult(data.booking);
      showToast("Booking cancelled.", "success");
    } catch (err) {
      showToast(err.message, "error");
      btn.disabled = false;
    }
  });

  clearSavedBtn.addEventListener("click", () => {
    localStorage.removeItem(STORAGE_KEY);
    renderSavedTrips();
    showToast("Cleared saved bookings from this device.");
  });

  async function refreshActiveSavedTrips() {
    const trips = getSavedTrips().filter((t) =>
      ["pending", "confirmed", "active"].includes((t.status || "").toLowerCase())
    );
    if (!trips.length) return;
    let updatedAny = false;
    await Promise.all(
      trips.slice(0, 6).map(async (t) => {
        try {
          const params = new URLSearchParams({
            code: (t.booking_code || "").trim(),
            phone: (t.customer_phone || "").trim(),
          });
          const res = await fetch(`/api/bookings/lookup?${params.toString()}`);
          if (!res.ok) return;
          const data = await res.json();
          if (data && data.booking) {
            saveRecentTrip(data.booking);
            updatedAny = true;
          }
        } catch (_) {
          // Offline or transient failure: keep cached saved trip display
        }
      })
    );
    if (updatedAny) {
      renderSavedTrips();
    }
  }

  renderSavedTrips();
  refreshActiveSavedTrips();

  const urlParams = new URLSearchParams(window.location.search);
  const preCode = urlParams.get("code");
  const prePhone = urlParams.get("phone");
  if (preCode && prePhone) {
    codeInput.value = preCode;
    phoneInput.value = prePhone;
    runLookup(preCode, prePhone);
  }
})();
