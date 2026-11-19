/* Web Push Notifications client helper for Motorbike Rentals Camiguin */
(function () {
  "use strict";

  const MotoRide = (window.MotoRide = window.MotoRide || {});
  const toast = (msg, type) => {
    if (MotoRide.showToast) MotoRide.showToast(msg, type);
    else alert(msg);
  };

  function urlB64ToUint8Array(base64String) {
    const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
    const base64 = (base64String + padding).replace(/\-/g, "+").replace(/_/g, "/");
    const rawData = window.atob(base64);
    const outputArray = new Uint8Array(rawData.length);
    for (let i = 0; i < rawData.length; ++i) {
      outputArray[i] = rawData.charCodeAt(i);
    }
    return outputArray;
  }

  function isSupported() {
    return (
      "serviceWorker" in navigator &&
      "PushManager" in window &&
      "Notification" in window
    );
  }

  async function getRegistration() {
    if (!isSupported()) return null;
    return await navigator.serviceWorker.ready;
  }

  async function getSubscription() {
    const reg = await getRegistration();
    if (!reg) return null;
    return await reg.pushManager.getSubscription();
  }

  async function subscribe(options = {}) {
    if (!isSupported()) {
      toast("Push notifications are not supported on this browser.", "error");
      return null;
    }

    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      toast("Notification permission was not granted.", "error");
      updateUi(false);
      return null;
    }

    try {
      const res = await fetch("/api/push/vapid-public-key");
      const { publicKey } = await res.json();
      if (!publicKey) throw new Error("Could not retrieve notification keys.");

      const reg = await getRegistration();
      let sub = await reg.pushManager.getSubscription();
      if (!sub) {
        sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlB64ToUint8Array(publicKey),
        });
      }

      const subData = sub.toJSON ? sub.toJSON() : sub;
      await fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: sub.endpoint,
          keys: subData.keys,
          phone: options.phone || "",
          booking_code: options.booking_code || "",
        }),
      });

      toast("🔔 Push alerts enabled on this device!", "success");
      updateUi(true);
      return sub;
    } catch (err) {
      console.warn("Push subscription failed:", err);
      toast("Could not enable notifications: " + err.message, "error");
      updateUi(false);
      return null;
    }
  }

  async function unsubscribe() {
    try {
      const sub = await getSubscription();
      if (sub) {
        await sub.unsubscribe();
        await fetch("/api/push/unsubscribe", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ endpoint: sub.endpoint }),
        }).catch(() => {});
      }
      toast("Push notifications disabled.", "success");
      updateUi(false);
    } catch (err) {
      toast("Error disabling notifications: " + err.message, "error");
    }
  }

  async function sendTest() {
    try {
      const res = await fetch("/api/push/test", { method: "POST" });
      const data = await res.json();
      if (res.ok) {
        toast(`Test push sent to ${data.sent_count || 1} device(s)!`, "success");
      } else {
        toast(data.error || "Could not send test push.", "error");
      }
    } catch (err) {
      toast("Failed to trigger test push.", "error");
    }
  }

  function updateUi(isSubscribed) {
    document.querySelectorAll("[data-push-toggle]").forEach((btn) => {
      btn.dataset.subscribed = isSubscribed ? "1" : "0";
      if (isSubscribed) {
        btn.classList.remove("btn-primary");
        btn.classList.add("btn-outline");
        btn.innerHTML = "🔔 Notifications Active";
      } else {
        btn.classList.remove("btn-outline");
        btn.classList.add("btn-primary");
        btn.innerHTML = "🔔 Enable Push Alerts";
      }
    });
  }

  async function init() {
    if (!isSupported()) return;
    const sub = await getSubscription();
    const isSubscribed = Boolean(sub && Notification.permission === "granted");
    updateUi(isSubscribed);

    // If already granted, sync quiet update to server so session changes update subscription role
    if (isSubscribed && sub) {
      const subData = sub.toJSON ? sub.toJSON() : sub;
      fetch("/api/push/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          endpoint: sub.endpoint,
          keys: subData.keys,
        }),
      }).catch(() => {});
    }

    document.addEventListener("click", async (e) => {
      const btn = e.target.closest("[data-push-toggle]");
      if (btn) {
        e.preventDefault();
        const currentSub = await getSubscription();
        if (currentSub && Notification.permission === "granted") {
          if (confirm("Push notifications are currently active on this browser. Turn them off?")) {
            await unsubscribe();
          }
        } else {
          await subscribe({
            phone: btn.dataset.pushPhone || "",
            booking_code: btn.dataset.pushBooking || "",
          });
        }
        return;
      }

      const testBtn = e.target.closest("[data-push-test]");
      if (testBtn) {
        e.preventDefault();
        await sendTest();
      }
    });
  }

  MotoRide.push = {
    isSupported,
    subscribe,
    unsubscribe,
    getSubscription,
    sendTest,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
