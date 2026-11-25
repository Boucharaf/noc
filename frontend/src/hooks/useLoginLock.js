import { useCallback, useEffect, useState } from "react";

import { auth } from "../api/noc";

/**
 * Attente imposée après trop de tentatives de connexion.
 *
 * Le VRAI verrou est côté serveur (Redis) : il tient quel que soit le
 * navigateur. Ce module n'en garde que l'échéance, dans localStorage, pour
 * que le décompte reprenne après une actualisation ; il la revérifie auprès
 * du serveur au chargement, qui peut avoir levé le verrou entre-temps.
 */
const KEY = "noc-login-lock";

function read() {
  try {
    const lock = JSON.parse(localStorage.getItem(KEY) ?? "null");
    return lock?.username && lock.until > Date.now() ? lock : null;
  } catch {
    return null;
  }
}

function write(lock) {
  try {
    if (lock) localStorage.setItem(KEY, JSON.stringify(lock));
    else localStorage.removeItem(KEY);
  } catch {
    /* stockage refusé : le serveur bloque quand même */
  }
}

/** « 14:05 » */
export function clock(seconds) {
  return `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(seconds % 60).padStart(2, "0")}`;
}

export function useLoginLock() {
  const [lock, setLock] = useState(read);
  const [now, setNow] = useState(() => Date.now());

  const update = useCallback((next) => {
    write(next);
    setNow(Date.now());
    setLock(next);
  }, []);

  const start = useCallback(
    (username, mode, seconds) => update({ username, mode, until: Date.now() + seconds * 1000 }),
    [update],
  );

  // Au chargement : le serveur a le dernier mot.
  useEffect(() => {
    const stored = read();
    if (!stored) return undefined;
    let alive = true;
    auth
      .lockStatus(stored.username, stored.mode)
      .then(({ retry_after_seconds: seconds }) => {
        if (!alive) return;
        if (seconds > 0) start(stored.username, stored.mode, seconds);
        else update(null);
      })
      .catch(() => {
        /* serveur injoignable : on garde l'échéance connue */
      });
    return () => {
      alive = false;
    };
  }, [start, update]);

  useEffect(() => {
    if (!lock) return undefined;
    const timer = setInterval(() => {
      if (Date.now() >= lock.until) update(null);
      else setNow(Date.now());
    }, 1000);
    return () => clearInterval(timer);
  }, [lock, update]);

  return {
    lock,
    remaining: lock ? Math.max(0, Math.ceil((lock.until - now) / 1000)) : 0,
    start,
  };
}
