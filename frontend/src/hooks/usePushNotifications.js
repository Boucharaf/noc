import { useCallback, useEffect, useState } from "react";
import { getVapidPublicKey, subscribePush, unsubscribePush } from "../api/notifications";

const urlBase64ToUint8Array = (base64String) => {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
};

const isSupported = () =>
  "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

// Browser push for critical incidents: registers this device's subscription
// with the backend so notification_service can reach it even when the tab
// isn't focused. Permission is only requested on explicit user action (the
// bell toggle in Header), never on load — browsers throttle/ignore
// auto-prompted permission requests anyway.
export const usePushNotifications = () => {
  const [permission, setPermission] = useState(
    isSupported() ? Notification.permission : "unsupported",
  );
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!isSupported()) return;
    navigator.serviceWorker.ready.then(async (registration) => {
      const sub = await registration.pushManager.getSubscription();
      setSubscribed(!!sub);
    });
  }, []);

  const enable = useCallback(async () => {
    setLoading(true);
    try {
      const perm = await Notification.requestPermission();
      setPermission(perm);
      if (perm !== "granted") return;

      const registration = await navigator.serviceWorker.ready;
      let sub = await registration.pushManager.getSubscription();
      if (!sub) {
        const publicKey = await getVapidPublicKey();
        sub = await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: urlBase64ToUint8Array(publicKey),
        });
      }
      const json = sub.toJSON();
      await subscribePush({ endpoint: json.endpoint, keys: json.keys });
      setSubscribed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  const disable = useCallback(async () => {
    setLoading(true);
    try {
      const registration = await navigator.serviceWorker.ready;
      const sub = await registration.pushManager.getSubscription();
      if (sub) {
        await unsubscribePush(sub.endpoint);
        await sub.unsubscribe();
      }
      setSubscribed(false);
    } finally {
      setLoading(false);
    }
  }, []);

  const toggle = useCallback(
    () => (subscribed ? disable() : enable()),
    [subscribed, enable, disable],
  );

  return { supported: isSupported(), permission, subscribed, loading, toggle };
};
