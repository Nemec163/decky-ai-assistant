export const XTERM_INLINE_CSS = `
.decky-ai-terminal .xterm { cursor: text; height: 100%; position: relative; user-select: none; }
.decky-ai-terminal .xterm.focus,
.decky-ai-terminal .xterm:focus { outline: none; }
.decky-ai-terminal .xterm .xterm-helpers { position: absolute; top: 0; z-index: 5; }
.decky-ai-terminal .xterm .xterm-helper-textarea {
  border: 0;
  height: 0;
  left: -9999em;
  margin: 0;
  opacity: 0;
  overflow: hidden;
  padding: 0;
  position: absolute;
  resize: none;
  top: 0;
  white-space: nowrap;
  width: 0;
  z-index: -5;
}
.decky-ai-terminal .xterm .composition-view {
  background: #101418;
  color: #d7dde8;
  display: none;
  position: absolute;
  white-space: nowrap;
  z-index: 1;
}
.decky-ai-terminal .xterm .composition-view.active { display: block; }
.decky-ai-terminal .xterm .xterm-viewport {
  background-color: #101418;
  bottom: 0;
  cursor: default;
  left: 0;
  overflow-y: auto;
  position: absolute;
  right: 0;
  top: 0;
}
.decky-ai-terminal .xterm .xterm-screen { position: relative; }
.decky-ai-terminal .xterm .xterm-screen canvas {
  left: 0;
  position: absolute;
  top: 0;
}
.decky-ai-terminal .xterm .xterm-scroll-area { visibility: hidden; }
.decky-ai-terminal .xterm-viewport::-webkit-scrollbar { width: 0; height: 0; }
.decky-ai-terminal .xterm-char-measure-element {
  display: inline-block;
  left: -9999em;
  line-height: normal;
  position: absolute;
  top: 0;
  visibility: hidden;
}
`;
