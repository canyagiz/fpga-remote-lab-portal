import { Eye, EyeOff } from "lucide-react";
import { KeyboardEvent, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface PasswordInputProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  autoComplete?: string;
  minLength?: number;
  required?: boolean;
}

export default function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  minLength,
  required,
}: PasswordInputProps) {
  const [visible, setVisible] = useState(false);
  const [capsLockOn, setCapsLockOn] = useState(false);

  function handleKeyEvent(e: KeyboardEvent<HTMLInputElement>) {
    // getModifierState needs a real KeyboardEvent, available on both
    // keydown and keyup - checking on both catches toggling Caps Lock
    // itself, not just typing while it's already on.
    setCapsLockOn(e.getModifierState("CapsLock"));
  }

  return (
    <div>
      <div className="relative">
        <Input
          id={id}
          type={visible ? "text" : "password"}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyEvent}
          onKeyUp={handleKeyEvent}
          autoComplete={autoComplete}
          minLength={minLength}
          required={required}
          className="pr-10"
        />
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="absolute right-0 top-0 h-9 w-9 text-muted-foreground hover:bg-transparent"
          onClick={() => setVisible((v) => !v)}
          aria-label={visible ? "Hide password" : "Show password"}
          tabIndex={-1}
        >
          {visible ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
        </Button>
      </div>
      {capsLockOn && (
        <p className="mt-1.5 inline-block rounded-full bg-warning-muted px-2.5 py-0.5 text-xs font-semibold text-warning-muted-foreground">
          Caps Lock is on
        </p>
      )}
    </div>
  );
}
