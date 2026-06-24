import { Focusable, staticClasses } from "@decky/ui";
import { FaCopy, FaExternalLinkAlt, FaTimes } from "react-icons/fa";
import { ActionButton } from "../../ui/primitives";
import { authLinkActionsStyle, authLinkPanelStyle } from "../../ui/styles";

export function AuthLinkPanel({
  link,
  onOpen,
  onCopy,
  onHide,
}: {
  link: string;
  onOpen: () => void;
  onCopy: () => void;
  onHide: () => void;
}) {
  return (
    <Focusable style={authLinkPanelStyle}>
      <div style={{ flex: "1 1 18rem", minWidth: 0 }}>
        <div className={staticClasses.Label}>Auth link</div>
        <div
          className={staticClasses.Text}
          style={{
            fontFamily: "Menlo, Consolas, monospace",
            fontSize: "12px",
            lineHeight: 1.35,
            maxHeight: "2.8em",
            overflow: "hidden",
            overflowWrap: "anywhere",
          }}
        >
          {link}
        </div>
      </div>
      <div style={authLinkActionsStyle}>
        <ActionButton
          focusable={false}
          icon={<FaExternalLinkAlt />}
          label="Open"
          minWidth="0"
          onClick={onOpen}
        />
        <ActionButton
          focusable={false}
          icon={<FaCopy />}
          label="Copy"
          minWidth="0"
          onClick={onCopy}
        />
        <ActionButton
          focusable={false}
          icon={<FaTimes />}
          label="Hide"
          minWidth="0"
          onClick={onHide}
        />
      </div>
    </Focusable>
  );
}
