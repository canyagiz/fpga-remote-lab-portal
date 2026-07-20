import { RefreshCw } from "lucide-react";

interface PuzzleCaptchaProps {
  backgroundImage: string;
  pieceImage: string;
  canvasWidth: number;
  canvasHeight: number;
  pieceWidth: number;
  pieceHeight: number;
  pieceTop: number;
  value: number;
  onChange: (x: number) => void;
  onReload?: () => void;
}

// A slide-the-piece-into-the-photo captcha: an <input type="range"> drives
// the piece's x position over the real background image, so dragging,
// clicking the track, and keyboard arrows (once focused) all work without
// custom pointer-event math. Unlike a plain "what's 6-1" question, the
// solution (target_x) is never sent to the client at all - see
// app/services/captcha.py - it's baked into where the hole and the piece
// sit in the two images' pixels, so actually looking at the photo is
// required to answer correctly.
export default function PuzzleCaptcha({
  backgroundImage,
  pieceImage,
  canvasWidth,
  canvasHeight,
  pieceWidth,
  pieceHeight,
  pieceTop,
  value,
  onChange,
  onReload,
}: PuzzleCaptchaProps) {
  return (
    <div style={{ width: canvasWidth }}>
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">Slide the piece into the gap</p>
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Load a new puzzle"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      <div
        className="relative mt-1.5 overflow-hidden rounded-md border border-border bg-muted"
        style={{ width: canvasWidth, height: canvasHeight }}
      >
        <img
          src={backgroundImage}
          alt=""
          draggable={false}
          className="absolute inset-0 h-full w-full select-none"
        />
        <img
          src={pieceImage}
          alt=""
          draggable={false}
          className="pointer-events-none absolute select-none drop-shadow-md"
          style={{ left: value, top: pieceTop, width: pieceWidth, height: pieceHeight }}
        />
        <input
          type="range"
          min={0}
          max={canvasWidth - pieceWidth}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          required
          className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
          aria-label="Slide the piece into the gap in the photo"
        />
      </div>
    </div>
  );
}
