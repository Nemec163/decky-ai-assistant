import { DialogButton, Focusable, TextField, Toggle, staticClasses } from "@decky/ui";
import { type ComponentType, type ReactNode } from "react";
import { FaExclamationTriangle } from "react-icons/fa";
import {
  dangerNoteStyle,
  errorBannerStyle,
  emptyStateStyle,
  inlineRowStyle,
  mutedTextStyle,
  settingFieldStyle,
  toggleControlStyle,
} from "./styles";

/**
 * Minimal contract for the hidden Decky `TextField` instances we drive
 * imperatively. We only ever reach for the private `m_elInput` element; typing
 * it here means a Decky rename surfaces as a compile error instead of a runtime
 * `undefined`. Props are intentionally permissive because the field is also used
 * as a plain controlled input in some places.
 */
export interface DeckyTextFieldHandle {
  m_elInput?: HTMLInputElement;
}

/**
 * Single typed wrapper around Decky's `TextField`. The component's own prop
 * types do not expose `ref`, `onKeyDown`, or `style`, so we widen them here once
 * rather than scattering `TextField as ComponentType<any>` casts.
 */
export const DeckyTextField = TextField as ComponentType<any>;

export function IconLabel({ icon, label }: { icon: ReactNode; label: string }) {
  return (
    <span style={{ alignItems: "center", display: "inline-flex", gap: "8px" }}>
      {icon}
      <span>{label}</span>
    </span>
  );
}

export function StatusLine({ label, value }: { label: string; value: string }) {
  return (
    <div style={inlineRowStyle}>
      <span style={{ flexShrink: 0 }}>{label}</span>
      <span style={{ ...mutedTextStyle, minWidth: 0, textAlign: "right" }}>{value}</span>
    </div>
  );
}

export function SectionHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div style={{ minWidth: 0, paddingTop: "2px" }}>
      <div className={staticClasses.Text}>{title}</div>
      {description ? <div className={staticClasses.Label}>{description}</div> : null}
    </div>
  );
}

export function ErrorBanner({ message }: { message?: string | null }) {
  if (!message) {
    return null;
  }
  return (
    <div role="alert" style={errorBannerStyle}>
      <span style={{ flexShrink: 0, marginTop: "2px" }}><FaExclamationTriangle /></span>
      <span style={{ minWidth: 0 }}>{message}</span>
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
}) {
  return (
    <div style={emptyStateStyle}>
      {icon ? <div style={{ fontSize: "20px", opacity: 0.7 }}>{icon}</div> : null}
      <div className={staticClasses.Text}>{title}</div>
      {description ? <div className={staticClasses.Label}>{description}</div> : null}
    </div>
  );
}

export function SettingRow({
  title,
  description,
  control,
}: {
  title: string;
  description?: string;
  control: ReactNode;
}) {
  return (
    <Focusable style={inlineRowStyle}>
      <div style={{ minWidth: 0 }}>
        <div className={staticClasses.Text}>{title}</div>
        {description ? <div className={staticClasses.Label}>{description}</div> : null}
      </div>
      <div style={{ flexShrink: 0, minWidth: "160px" }}>{control}</div>
    </Focusable>
  );
}

/**
 * Toggle row that reuses the bare `Toggle` switch instead of `ToggleField`.
 * `ToggleField` ships its own `Field` chrome, which rendered a heavy dark box
 * around the switch once nested inside our own row layout. The plain `Toggle`
 * keeps the label/description owned by `SettingRow` and shows only the switch.
 */
export function SettingToggle({
  title,
  description,
  checked,
  disabled,
  onChange,
}: {
  title: string;
  description?: string;
  checked: boolean;
  disabled?: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <SettingRow
      title={title}
      description={description}
      control={
        <div style={toggleControlStyle}>
          <Toggle value={checked} disabled={disabled} onChange={onChange} />
        </div>
      }
    />
  );
}

/**
 * Stacked label-over-control field. Text inputs need the full panel width,
 * which the side-by-side `SettingRow` cannot give them (it pins controls to a
 * narrow right column and truncates long values like API URLs).
 */
export function SettingField({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Focusable style={settingFieldStyle}>
      <div style={{ minWidth: 0 }}>
        <div className={staticClasses.Text}>{title}</div>
        {description ? <div className={staticClasses.Label}>{description}</div> : null}
      </div>
      <div style={{ width: "100%" }}>{children}</div>
    </Focusable>
  );
}

export function DangerNote({ message }: { message?: string | null }) {
  if (!message) {
    return null;
  }
  return (
    <div style={dangerNoteStyle}>
      <span style={{ flexShrink: 0, marginTop: "2px" }}><FaExclamationTriangle /></span>
      <span style={{ minWidth: 0 }}>{message}</span>
    </div>
  );
}

export function TinyButton({
  children,
  disabled,
  focusable,
  onClick,
  title,
}: {
  children: ReactNode;
  disabled?: boolean;
  focusable?: boolean;
  onClick: (event: MouseEvent) => void;
  title?: string;
}) {
  return (
    <div title={title} style={{ display: "flex" }}>
      <DialogButton
        disabled={disabled}
        focusable={focusable}
        onClick={onClick}
        style={{
          alignItems: "center",
          display: "flex",
          height: "38px",
          justifyContent: "center",
          minWidth: "42px",
          padding: "8px 10px",
        }}
      >
        {children}
      </DialogButton>
    </div>
  );
}

export function ActionButton({
  disabled,
  focusable,
  icon,
  label,
  minWidth = "76px",
  onClick,
}: {
  disabled?: boolean;
  focusable?: boolean;
  icon: ReactNode;
  label: string;
  minWidth?: string;
  onClick: () => void;
}) {
  return (
    <DialogButton
      disabled={disabled}
      focusable={focusable}
      onClick={onClick}
      style={{
        alignItems: "center",
        display: "flex",
        height: "38px",
        justifyContent: "center",
        minWidth,
        padding: "8px 10px",
        whiteSpace: "nowrap",
      }}
    >
      <IconLabel icon={icon} label={label} />
    </DialogButton>
  );
}
