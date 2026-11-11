"use client";

import { ReactNode, useEffect } from "react";

export type DialogAction = {
  label: string;
  onClick: () => void;
  variant?: "primary" | "danger" | "plain";
};

type Props = {
  title: string;
  children: ReactNode;
  actions?: DialogAction[];
  onClose: () => void;
};

// In-app pop-up. Closes on ✕, Escape or a click outside, so a misclick
// never does anything.
export default function Dialog({ title, children, actions = [], onClose }: Props) {
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }

    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="dialog-head">
          <h3>{title}</h3>
          <button type="button" className="dialog-close" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </div>

        <div className="dialog-body">{children}</div>

        {actions.length > 0 && (
          <div className="dialog-actions">
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                className={`pill pill-small ${
                  action.variant === "danger"
                    ? "pill-danger"
                    : action.variant === "plain"
                      ? "pill-grey"
                      : "pill-blue"
                }`}
                onClick={action.onClick}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
