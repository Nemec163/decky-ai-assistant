import { Focusable } from "@decky/ui";
import {
  FaArrowDown,
  FaArrowLeft,
  FaArrowRight,
  FaArrowUp,
} from "react-icons/fa";
import { TinyButton } from "../../ui/primitives";

export function ExtraKeysBar({ onKey }: { onKey: (data: string) => void }) {
  return (
    <Focusable
      style={{
        display: "flex",
        flexShrink: 0,
        gap: "8px",
        margin: "10px auto 0",
        maxWidth: "100%",
        overflowX: "auto",
        paddingBottom: "4px",
        width: "fit-content",
      }}
    >
      <TinyButton focusable={false} onClick={() => onKey("\r")}>Enter</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\t")}>Tab</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1b")}>Esc</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1b[D")}>
        <FaArrowLeft />
      </TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1b[A")}>
        <FaArrowUp />
      </TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1b[B")}>
        <FaArrowDown />
      </TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1b[C")}>
        <FaArrowRight />
      </TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x03")}>^C</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x04")}>^D</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x12")}>^R</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x1a")}>^Z</TinyButton>
      <TinyButton focusable={false} onClick={() => onKey("\x0c")}>^L</TinyButton>
    </Focusable>
  );
}
