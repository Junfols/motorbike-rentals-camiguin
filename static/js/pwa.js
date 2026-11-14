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

  // PWA Service Worker registration
  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch((err) => {
        console.warn("Service worker registration skipped:", err);
      });
    });
  }

  // PWA Install Prompt handling
  let deferredPrompt = null;
  const installBtn = document.getElementById("install-app-btn");
  const mobileInstallBtn = document.getElementById("mobile-install-nav-btn");
  const nativeCtaBox = document.getElementById("native-install-cta-box");
  const triggerNativeInstallBtn = document.getElementById("trigger-native-install");

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event;
    if (nativeCtaBox) {
      nativeCtaBox.classList.remove("hidden");
    }
    if (installBtn) {
      installBtn.querySelector("span").textContent = "Install App";
    }
  });

  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    if (nativeCtaBox) nativeCtaBox.classList.add("hidden");
    closeModal("install-modal");
    showToast("App installed on your device!", "success");
  });

  async function handleInstallClick() {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      if (nativeCtaBox) nativeCtaBox.classList.add("hidden");
      if (choice && choice.outcome === "accepted") {
        showToast("Installing app...", "success");
      }
    } else {
      openModal("install-modal");
    }
  }

  if (installBtn) installBtn.addEventListener("click", handleInstallClick);
  if (mobileInstallBtn) mobileInstallBtn.addEventListener("click", handleInstallClick);
  if (triggerNativeInstallBtn) triggerNativeInstallBtn.addEventListener("click", handleInstallClick);

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

  window.MotoRide = {
    get shop() {
      return shopConfig;
    },
    escapeHtml,
    formatMoney,
    paymentStatusLabel,
    showToast,
    openModal,
    closeModal,
    saveRecentTrip,
    updateShopTextInDom,
  };
})();
