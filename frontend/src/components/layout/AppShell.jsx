import React from "react";
import Header from "./Header";
import Sidebar from "./Sidebar";
import MobileTabBar from "./MobileTabBar";
import AlertTicker from "./AlertTicker";
import { useAuthStore } from "../../store/auth";

const AppShell = ({ children }) => {
  const role = useAuthStore((s) => s.user?.role);
  const showTicker = role !== "agent_terrain";

  return (
    <div className="flex h-screen flex-col overflow-hidden" style={{ background: "var(--color-page)" }}>
      <Header />
      {showTicker && <AlertTicker />}
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 overflow-y-auto p-3 md:p-5">{children}</main>
      </div>
      <MobileTabBar />
    </div>
  );
};

export default AppShell;
