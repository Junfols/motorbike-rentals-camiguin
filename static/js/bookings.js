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

  const contractModal = document.getElementById("contract-modal");
  const contractContent = document.getElementById("contract-modal-body-content");
  const reviewModal = document.getElementById("review-modal");
  const reviewForm = document.getElementById("review-form");
  const reviewError = document.getElementById("review-form-error");
  const starPicker = document.getElementById("star-picker");
  const starRatingText = document.getElementById("star-rating-text");
  const reviewRatingVal = document.getElementById("review-rating-val");

  let activeBooking = null;

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

  function renderCustomerInspectionsHtml(b) {
    const insp = b.inspections || {};
    const pickup = insp.pickup || null;
    const ret = insp.return || null;
    if (!pickup && !ret) return "";

    const renderCard = (title, item, bg, border) => {
      if (!item) return "";
      const photos = (item.photo_urls || [])
        .map(
          (u) =>
            `<a href="${escapeHtml(u)}" target="_blank" rel="noopener"><img src="${escapeHtml(u)}" alt="${escapeHtml(title)}" style="width:62px;height:62px;object-fit:cover;border-radius:8px;border:1px solid #cbd5e1;"></a>`
        )
        .join("");
      return `
        <div style="flex:1;min-width:220px;background:${bg};border:1px solid ${border};border-radius:10px;padding:10px 12px;font-size:0.84rem;">
          <strong style="display:block;margin-bottom:4px;">${title}</strong>
          <div>⛽ Fuel Gauge: <strong>${escapeHtml(item.fuel_level || "N/A")}</strong>${item.odometer_km ? ` &bull; 🧭 ${escapeHtml(item.odometer_km)}` : ""}</div>
          <div class="text-muted" style="font-size:0.78rem;margin-top:2px;">🪖 Helmets: ${Number(item.helmets_count ?? 2)}${item.created_at ? ` &bull; Recorded ${escapeHtml(item.created_at)}` : ""}</div>
          ${item.condition_notes ? `<div style="margin-top:4px;color:#334155;">📝 ${escapeHtml(item.condition_notes)}</div>` : ""}
          ${photos ? `<div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px;">${photos}</div>` : ""}
        </div>
      `;
    };

    return `
      <div style="margin-top:12px;">
        <div style="font-weight:700;font-size:0.86rem;margin-bottom:6px;color:var(--ink);">📸 Before &amp; After Handover Inspection Checklist</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;">
          ${renderCard("🛵 Pickup Condition (Before)", pickup, "#f0fdf4", "#bbf7d0")}
          ${renderCard("🏁 Return Condition (After)", ret, "#eff6ff", "#bfdbfe")}
        </div>
      </div>
    `;
  }

  function renderLookupResult(b) {
    activeBooking = b;
    const canCancel = b.status === "pending";
    const waDigits = (b.shop_whatsapp || shop.whatsapp_number || "").replace(/\D+/g, "");
    const waLink = waDigits
      ? `https://wa.me/${waDigits}?text=${encodeURIComponent(
          `Hi ${b.shop_name || shop.shop_name || "Motorbike Rentals Camiguin"}, following up on booking ${b.booking_code} (${b.bike_name}).`
        )}`
      : "";
    const messengerLink = (b.shop_messenger_url || shop.messenger_url || "").trim();
    const durText = b.duration_label || `${b.rental_days}d`;
    const durationBadge = b.rental_type === "half_day"
      ? `<span class="spec-pill" style="background:#fef3c7;color:#92400e;border-color:#fde68a;">⏱️ Half-Day (6 hrs)</span>`
      : Number(b.discount_saved || 0) > 0
      ? `<span class="spec-pill" style="background:#dcfce7;color:#166534;border-color:#86efac;">🏷️ Saved ${escapeHtml(formatMoney(b.discount_saved))}</span>`
      : "";

    lookupResult.innerHTML = `
      <div class="trip-card">
        <div class="trip-card-head" style="margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border-soft);">
          <div>
            <span class="trip-detail-label">Booking Reference</span>
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:4px;">
              <span class="badge badge-dark" style="font-family:ui-monospace,monospace;letter-spacing:0.02em;font-size:0.95rem;padding:4px 12px;">${escapeHtml(b.booking_code)}</span>
              ${durationBadge}
            </div>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap;align-items:center">
            ${(Number(b.reservation_fee || 0) > 0 || (b.payment_status && b.payment_status !== "unpaid")) ? `<span class="badge badge-${escapeHtml(b.payment_status || "unpaid")}">${escapeHtml(window.MotoRide && window.MotoRide.paymentStatusLabel ? window.MotoRide.paymentStatusLabel(b.payment_status) : (b.payment_status || "unpaid"))}</span>` : ""}
            <span class="badge badge-${escapeHtml(b.status)}">${escapeHtml(statusLabel(b.status))}</span>
          </div>
        </div>

        <div class="trip-bike-row">
          <img src="${escapeHtml(
            !b.bike_image || String(b.bike_image).startsWith("/static/images/")
              ? "/static/icons/icon.svg"
              : b.bike_image
          )}" alt="${escapeHtml(b.bike_name)}" class="trip-bike-thumb" style="border-radius:14px;border:1px solid var(--border-soft);box-shadow:var(--shadow-xs);background:#0f172a;padding:4px;">
          <div>
            <strong style="font-size:1.05rem;color:var(--ink);">${escapeHtml(b.bike_name)}</strong>
            <div class="text-muted" style="margin-top:2px;">${escapeHtml(b.bike_category || "")} &bull; ${escapeHtml(b.bike_transmission || "")}</div>
            ${b.shop_name ? `<div class="text-muted" style="margin-top:2px;"><strong>Shop:</strong> ${escapeHtml(b.shop_name)} (${escapeHtml(b.shop_municipality || "")})</div>` : ""}
            ${b.plate_number ? `<div class="text-muted" style="margin-top:2px;">Plate / Unit: ${escapeHtml(b.plate_number)}</div>` : ""}
          </div>
        </div>

        <div class="trip-details-grid">
          <div>
            <span class="trip-detail-label">Rider</span>
            <strong>${escapeHtml(b.customer_name)}</strong>
          </div>
          <div>
            <span class="trip-detail-label">Rental Dates</span>
            <strong>${escapeHtml(b.pickup_date)} &rarr; ${escapeHtml(b.return_date)} (${escapeHtml(durText)})</strong>
          </div>
          <div>
            <span class="trip-detail-label">Pickup</span>
            <strong>${escapeHtml(b.pickup_time)} &bull; ${
              b.pickup_method === "benoni_port"
                ? "Benoni Port (Mahinog) (+₱200)"
                : b.pickup_method === "balbagon_port"
                ? "Balbagon Port (Mambajao) (Free)"
                : b.pickup_method === "airport"
                ? "Camiguin Airport (Mambajao) (Free)"
                : (b.pickup_method === "around_mambajao" || b.pickup_method === "mambajao")
                ? "Around Mambajao (Free)"
                : b.pickup_method === "delivery"
                ? "Hotel / Resort Delivery"
                : "Shop Pickup"
            }</strong>
          </div>
          <div>
            <span class="trip-detail-label">Total Rental</span>
            <strong>${escapeHtml(formatMoney(b.total_amount))}</strong>
            ${Number(b.discount_saved || 0) > 0 ? `<div style="font-size:0.76rem;color:#059669;font-weight:600;">Saved ${escapeHtml(formatMoney(b.discount_saved))}</div>` : ""}
          </div>
          <div>
            <span class="trip-detail-label">Balance Due on Pickup</span>
            <strong>${escapeHtml(formatMoney(b.balance_due !== undefined && b.balance_due !== null ? b.balance_due : b.total_amount))}</strong>
            ${Number(b.reservation_fee || 0) > 0 ? `<div class="text-muted">Down payment: ${escapeHtml(formatMoney(b.reservation_fee))}</div>` : ""}
          </div>
          ${b.customer_address ? `
          <div>
            <span class="trip-detail-label">Address</span>
            <strong>${escapeHtml(b.customer_address)}</strong>
          </div>
          ` : ""}
          <div>
            <span class="trip-detail-label">License #</span>
            <strong>${escapeHtml(b.license_number)}</strong>
          </div>
        </div>

        ${(b.payment_reference || b.payment_proof_url) ? `<p class="text-muted"><strong>Down Payment:</strong> ${escapeHtml((b.payment_channel || "gcash").toUpperCase())}${b.payment_reference ? ` &bull; Ref # ${escapeHtml(b.payment_reference)}` : ""}${b.payment_proof_url ? ` &bull; <a href="${escapeHtml(b.payment_proof_url)}" target="_blank" rel="noopener" class="payment-proof-link">View Receipt</a>` : ""}</p>` : ""}
        ${b.delivery_address ? `<p class="text-muted"><strong>Delivery Address:</strong> ${escapeHtml(b.delivery_address)}${b.google_maps_url ? ` &bull; <a href="${escapeHtml(b.google_maps_url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline" style="padding:2px 8px;font-size:0.75rem;display:inline-flex;align-items:center;gap:4px;">🗺️ Open in Google Maps</a>` : ""}</p>` : ""}
        ${renderCustomerInspectionsHtml(b)}
        ${b.admin_notes ? `<div class="info-box" style="margin-top:10px;"><h4>Shop Note</h4><p>${escapeHtml(b.admin_notes)}</p></div>` : ""}

        <div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:12px;">
          ${
            b.contract_agreed || b.signature_url || b.license_photo_url
              ? `<button type="button" class="btn btn-outline btn-sm" id="view-contract-btn">📝 View Rental Contract &amp; ID</button>`
              : ""
          }
          <a href="/bookings/${encodeURIComponent(b.booking_code)}/contract?phone=${encodeURIComponent(b.customer_phone)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">🖨️ Print / Save PDF Contract</a>
          ${
            ["confirmed", "active", "completed"].includes(b.status)
              ? `<button type="button" class="btn btn-primary btn-sm" id="leave-review-btn">⭐ Leave Review</button>`
              : ""
          }
          ${
            canCancel
              ? `<button type="button" class="btn btn-danger btn-sm" id="cancel-trip-btn" data-code="${escapeHtml(b.booking_code)}" data-phone="${escapeHtml(b.customer_phone)}">Cancel Request</button>`
              : ""
          }
          ${
            b.status !== "cancelled"
              ? `<button type="button" class="btn btn-primary btn-sm" id="call-shop-btn" data-call-booking="${escapeHtml(b.booking_code)}" data-call-phone="${escapeHtml(b.customer_phone)}" data-call-name="${escapeHtml(b.shop_name || "Shop")}" data-call-tel="${escapeHtml(b.shop_phone || "")}">📞 Call Shop (in app)</button>`
              : ""
          }
          ${
            waLink
              ? `<a href="${escapeHtml(waLink)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">Message Shop on WhatsApp</a>`
              : ""
          }
          ${
            messengerLink
              ? `<a href="${escapeHtml(messengerLink)}" target="_blank" rel="noopener" class="btn btn-outline btn-sm">💬 Message on Messenger</a>`
              : ""
          }
          ${
            b.status !== "cancelled"
              ? `<button type="button" class="btn btn-outline btn-sm" data-push-toggle="1" data-push-phone="${escapeHtml(b.customer_phone)}" data-push-booking="${escapeHtml(b.booking_code)}">🔔 Get Phone Alerts for this Booking</button>`
              : ""
          }
        </div>
      </div>
    `;
    lookupResult.classList.remove("hidden");
  }

  function openContractModal(b) {
    if (!contractModal || !contractContent) return;
    contractContent.innerHTML = `
      <div style="padding:10px 0;">
        <div style="background:#f8fafc;padding:12px;border-radius:10px;border:1px solid #e2e8f0;margin-bottom:14px;">
          <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;">
            <div>
              <strong style="font-size:1.05rem;">Booking #${escapeHtml(b.booking_code)}</strong>
              <div class="text-muted">${escapeHtml(b.bike_name)} &bull; ${escapeHtml(b.pickup_date)} to ${escapeHtml(b.return_date)}</div>
            </div>
            <span class="badge badge-verified">&#10003; Signed Digital Agreement</span>
          </div>
          <div style="margin-top:6px;font-size:0.85rem;color:#475569;">
            <strong>Renter:</strong> ${escapeHtml(b.customer_name)} &bull; <strong>License:</strong> ${escapeHtml(b.license_number)}${b.customer_address ? ` &bull; <strong>Address:</strong> ${escapeHtml(b.customer_address)}` : ""}
            ${b.contract_signed_at ? `<br><strong>Signed At:</strong> ${escapeHtml(b.contract_signed_at)}` : ""}
          </div>
        </div>

        <div style="background:#ffffff;padding:12px;border-radius:8px;border:1px solid #e2e8f0;font-size:0.85rem;margin-bottom:14px;">
          <h4 style="margin:0 0 6px;">📄 Standard Rental Terms Acknowledged</h4>
          <ul style="margin:0;padding-left:18px;line-height:1.5;color:#475569;">
            <li>Renter certifies holding a valid driver's license authorized for motorcycle riding in the Philippines.</li>
            <li>Renter and backrider agree to wear helmets at all times on Camiguin roads.</li>
            <li>The motorbike shall be kept on Camiguin Island during the entire rental period.</li>
          </ul>
        </div>

        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px;">
          <div style="border:1px solid #cbd5e1;border-radius:8px;padding:10px;background:#f8fafc;text-align:center;">
            <strong style="display:block;margin-bottom:6px;font-size:0.88rem;">&#129674; Driver's License Photo</strong>
            ${
              b.license_photo_url
                ? `<a href="${escapeHtml(b.license_photo_url)}" target="_blank" rel="noopener"><img src="${escapeHtml(b.license_photo_url)}" alt="Driver's License" style="max-width:100%;max-height:160px;object-fit:contain;border-radius:6px;border:1px solid #e2e8f0;"></a>`
                : `<div class="text-muted" style="padding:20px 0;">No license photo uploaded</div>`
            }
          </div>

          <div style="border:1px solid #cbd5e1;border-radius:8px;padding:10px;background:#f8fafc;text-align:center;">
            <strong style="display:block;margin-bottom:6px;font-size:0.88rem;">&#9997;&#65039; Digital Finger Signature</strong>
            ${
              b.signature_url
                ? `<a href="${escapeHtml(b.signature_url)}" target="_blank" rel="noopener"><img src="${escapeHtml(b.signature_url)}" alt="Digital Signature" style="max-width:100%;max-height:160px;object-fit:contain;background:#ffffff;border-radius:6px;border:1px solid #e2e8f0;padding:4px;"></a>`
                : `<div class="text-muted" style="padding:20px 0;">No signature recorded</div>`
            }
          </div>
        </div>

        <div class="info-box" style="margin-top:14px;background:#f0fdf4;border-color:#bbf7d0;">
          <strong style="color:#166534;">&#127881; Express Key Handover Ready</strong>
          <p class="text-muted" style="margin:4px 0 0;font-size:0.83rem;">Your contract and license are securely verified on file. When you meet your delivery driver or arrive at ${escapeHtml(b.shop_name || "the rental shop")}, just show this screen to collect your helmet and keys immediately!</p>
        </div>

        <div style="margin-top:14px;text-align:center;">
          <a href="/bookings/${encodeURIComponent(b.booking_code)}/contract?phone=${encodeURIComponent(b.customer_phone)}" target="_blank" rel="noopener" class="btn btn-primary btn-sm" style="display:inline-flex;align-items:center;gap:6px;">🖨️ Print / Save as PDF Contract &amp; Receipt</a>
        </div>
      </div>
    `;
    contractModal.classList.remove("hidden");
  }

  function openReviewModal(b) {
    if (!reviewModal || !reviewForm) return;
    document.getElementById("review-booking-code").value = b.booking_code;
    document.getElementById("review-bike-id").value = b.bike_id;
    document.getElementById("review-customer-name").value = b.customer_name || "";
    reviewRatingVal.value = "5";
    updateStarDisplay(5);
    reviewError.classList.add("hidden");
    reviewError.textContent = "";
    reviewModal.classList.remove("hidden");
  }

  function updateStarDisplay(val) {
    if (!starPicker) return;
    const stars = starPicker.querySelectorAll(".star-pick");
    stars.forEach((s) => {
      const v = Number(s.getAttribute("data-val"));
      if (v <= val) {
        s.style.color = "#f59e0b";
      } else {
        s.style.color = "#cbd5e1";
      }
    });
    const labels = {
      1: "1 out of 5 — Poor",
      2: "2 out of 5 — Fair",
      3: "3 out of 5 — Good",
      4: "4 out of 5 — Very Good",
      5: "5 out of 5 — Excellent!",
    };
    if (starRatingText) {
      starRatingText.textContent = labels[val] || `${val} out of 5`;
    }
  }

  if (starPicker) {
    starPicker.addEventListener("click", (e) => {
      const star = e.target.closest(".star-pick");
      if (!star) return;
      const val = Number(star.getAttribute("data-val") || 5);
      reviewRatingVal.value = String(val);
      updateStarDisplay(val);
    });
  }

  if (reviewForm) {
    reviewForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      reviewError.classList.add("hidden");
      reviewError.textContent = "";

      const btn = document.getElementById("submit-review-btn");
      btn.disabled = true;
      btn.textContent = "Submitting Review...";

      try {
        const payload = {
          booking_code: document.getElementById("review-booking-code").value,
          bike_id: Number(document.getElementById("review-bike-id").value),
          rating: Number(reviewRatingVal.value),
          customer_name: document.getElementById("review-customer-name").value.trim(),
          comment: document.getElementById("review-comment").value.trim(),
        };

        const res = await fetch("/api/reviews", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not submit review.");

        showToast("Daghang salamat! Your 5-star review has been published ⭐", "success");
        reviewModal.classList.add("hidden");
        reviewForm.reset();
      } catch (err) {
        reviewError.textContent = err.message;
        reviewError.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        btn.textContent = "Submit Review ⭐";
      }
    });
  }

  document.addEventListener("click", (e) => {
    const closeBtn = e.target.closest("[data-close-modal]");
    if (closeBtn) {
      const targetId = closeBtn.getAttribute("data-close-modal");
      const targetEl = document.getElementById(targetId);
      if (targetEl) targetEl.classList.add("hidden");
    }
  });

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
    const contractBtn = event.target.closest("#view-contract-btn");
    if (contractBtn && activeBooking) {
      openContractModal(activeBooking);
      return;
    }

    const reviewBtn = event.target.closest("#leave-review-btn");
    if (reviewBtn && activeBooking) {
      openReviewModal(activeBooking);
      return;
    }

    const syncBtn = event.target.closest("#sync-pm-btn");
    if (syncBtn) {
      const bId = syncBtn.getAttribute("data-booking-id");
      const bCode = syncBtn.getAttribute("data-code");
      const bPhone = syncBtn.getAttribute("data-phone");
      syncBtn.disabled = true;
      syncBtn.textContent = "Checking...";
      try {
        const res = await fetch(`/api/bookings/${bId}/paymongo-sync`);
        const data = await res.json();
        if (!res.ok) throw new Error(data.error || "Could not check payment status.");
        if (data.status === "paid" || data.status === "already_verified") {
          showToast("Payment verified & confirmed!", "success");
          runLookup(bCode, bPhone);
        } else {
          showToast(`PayMongo status: ${data.status || "unpaid"}. If you just paid, please wait a moment and try again.`, "info");
        }
      } catch (err) {
        showToast(err.message, "error");
      } finally {
        syncBtn.disabled = false;
        syncBtn.textContent = "Sync Payment Status";
      }
      return;
    }

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
  } else if (!phoneInput.value) {
    try {
      const savedProfile = JSON.parse(localStorage.getItem("motoride_customer_profile") || "null");
      if (savedProfile && savedProfile.customer_phone) {
        phoneInput.value = savedProfile.customer_phone;
      }
    } catch (_) {}
  }
})();
