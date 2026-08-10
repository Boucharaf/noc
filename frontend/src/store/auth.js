import { create } from "zustand";
import { persist } from "zustand/middleware";

export const useAuthStore = create(
  persist(
    (set) => ({
      token: null,
      user: null,
      // Epoch ms at which `token` stops being accepted, from the server's
      // expires_in. Kept in the store so useSessionKeepAlive can renew before
      // that moment instead of finding out through a 401.
      expiresAt: null,
      // Why the session ended, when it was not the user's doing. Read once by
      // the login page so an operator who comes back to a login screen is told
      // the session lapsed rather than left wondering what they did wrong.
      logoutReason: null,
      login: (token, user, expiresIn) =>
        set({
          token,
          user,
          expiresAt: expiresIn ? Date.now() + expiresIn * 1000 : null,
          logoutReason: null,
        }),
      logout: (reason = null) =>
        set({ token: null, user: null, expiresAt: null, logoutReason: reason }),
      clearLogoutReason: () => set({ logoutReason: null }),
    }),
    { name: "noc-auth" },
  ),
);
