import React from "react";

/**
 * `variant="panel"` renders the flatter, sharp-cornered instrumentation style
 * (see .noc-panel in index.css) used across the dense dashboard grids — a
 * status-colored bar on top instead of a drop shadow. Default variant is
 * untouched, so every existing usage keeps its original look.
 */
const Card = ({
  title,
  subtitle,
  action,
  icon: Icon,
  children,
  className = "",
  bodyClassName = "",
  bodyStyle = {},
  variant = "surface",
  accent,
}) => {
  const isPanel = variant === "panel";
  return (
    <div
      className={`${isPanel ? "noc-panel" : "rounded-xl border"} ${className}`}
      style={{
        background: "var(--color-surface)",
        borderColor: isPanel ? undefined : "var(--color-border)",
        boxShadow: isPanel ? undefined : "var(--shadow-elevate)",
        ...(isPanel && accent ? { "--panel-accent": accent } : {}),
      }}
    >
      {(title || action) && (
        <div
          className="flex items-center justify-between gap-3 border-b px-4 py-3"
          style={{ borderColor: "var(--color-border)" }}
        >
          <div className="flex items-center gap-2 min-w-0">
            {Icon && (
              <Icon
                className="h-4 w-4 shrink-0"
                style={{ color: "var(--color-accent)" }}
              />
            )}
            <div className="min-w-0">
              <h3
                className="truncate text-[13px] font-semibold"
                style={{ color: "var(--color-text-primary)" }}
              >
                {title}
              </h3>
              {subtitle && (
                <p
                  className="truncate text-xs"
                  style={{ color: "var(--color-text-secondary)" }}
                >
                  {subtitle}
                </p>
              )}
            </div>
          </div>
          {action}
        </div>
      )}
      <div className={`p-4 ${bodyClassName}`} style={bodyStyle}>{children}</div>
    </div>
  );
};

export default Card;
