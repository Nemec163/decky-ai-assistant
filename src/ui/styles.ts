import { type CSSProperties } from "react";

export const sidePanelStyle: CSSProperties = {
  boxSizing: "border-box",
  display: "flex",
  flexDirection: "column",
  gap: "12px",
  padding: "0 12px 12px",
  width: "100%",
};

export const inlineRowStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  gap: "10px",
  justifyContent: "space-between",
  minWidth: 0,
  width: "100%",
};

export const stackStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "10px",
  minWidth: 0,
};

export const settingFieldStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: "6px",
  minWidth: 0,
  width: "100%",
};

export const toggleControlStyle: CSSProperties = {
  display: "flex",
  justifyContent: "flex-end",
  width: "100%",
};

export const dangerNoteStyle: CSSProperties = {
  border: "1px solid rgba(255,176,84,0.45)",
  background: "rgba(255,176,84,0.12)",
  borderRadius: "6px",
  color: "#ffd9a8",
  display: "flex",
  alignItems: "flex-start",
  gap: "8px",
  overflowWrap: "anywhere",
  padding: "8px 10px",
  width: "100%",
};

export const mutedTextStyle: CSSProperties = {
  opacity: 0.72,
  overflowWrap: "anywhere",
};

export const terminalPageStyle: CSSProperties = {
  boxSizing: "border-box",
  color: "#f0f3f7",
  display: "flex",
  flexDirection: "column",
  height: "100dvh",
  minHeight: 0,
  overflow: "hidden",
  padding: "2.5rem 1rem 1rem",
  position: "relative",
  width: "100vw",
};

export const toolbarStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  flexShrink: 0,
  gap: "10px",
  justifyContent: "space-between",
  marginBottom: "12px",
  minWidth: 0,
};

export const toolbarActionsStyle: CSSProperties = {
  alignItems: "center",
  display: "flex",
  flexShrink: 0,
  gap: "8px",
};

export const authLinkPanelStyle: CSSProperties = {
  alignItems: "stretch",
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: "6px",
  boxSizing: "border-box",
  display: "flex",
  flexWrap: "wrap",
  flexShrink: 0,
  gap: "10px",
  justifyContent: "space-between",
  marginBottom: "10px",
  padding: "8px",
  width: "100%",
};

export const authLinkActionsStyle: CSSProperties = {
  display: "grid",
  flex: "0 0 auto",
  gap: "8px",
  gridTemplateColumns: "repeat(3, minmax(70px, 1fr))",
  width: "min(100%, 248px)",
};

export const voiceInputPanelStyle: CSSProperties = {
  ...authLinkPanelStyle,
  alignItems: "center",
};

export const voiceInputActionsStyle: CSSProperties = {
  display: "grid",
  flex: "0 0 auto",
  gap: "8px",
  gridTemplateColumns: "repeat(2, minmax(70px, 1fr))",
  width: "min(100%, 164px)",
};

export const terminalHostStyle: CSSProperties = {
  background: "#101418",
  border: "1px solid rgba(255,255,255,0.14)",
  borderRadius: "6px",
  boxSizing: "border-box",
  overflow: "hidden",
  padding: "6px",
  width: "100%",
};

export const errorBannerStyle: CSSProperties = {
  boxSizing: "border-box",
  display: "flex",
  alignItems: "flex-start",
  gap: "8px",
  padding: "8px 10px",
  borderRadius: "6px",
  border: "1px solid rgba(255,120,120,0.45)",
  background: "rgba(190,60,60,0.14)",
  color: "#ffd9d9",
  overflowWrap: "anywhere",
  width: "100%",
};

export const emptyStateStyle: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: "6px",
  textAlign: "center",
  padding: "18px 12px",
  opacity: 0.8,
  width: "100%",
};

export const buttonRowStyle: CSSProperties = {
  display: "flex",
  gap: "8px",
  flexWrap: "wrap",
  width: "100%",
};
