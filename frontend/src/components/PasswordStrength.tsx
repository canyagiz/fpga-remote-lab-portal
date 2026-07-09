import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

interface Rule {
  label: string;
  test: (password: string) => boolean;
}

// The backend only requires length >= 8 (see backend/app/schemas.py -
// RegisterRequest.password). Composition rules like "must have a symbol"
// are shown here only as UI guidance/encouragement, not enforced server-
// side: current guidance (NIST 800-63B) favors length over forced
// character-class mixing, which tends to push people toward predictable
// substitutions ("password" -> "Passw0rd!") rather than real strength.
const rules: Rule[] = [
  { label: "At least 8 characters", test: (p) => p.length >= 8 },
  { label: "One uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "One lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "One number", test: (p) => /[0-9]/.test(p) },
  { label: "One symbol", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

const barColor = ["bg-destructive", "bg-destructive", "bg-warning", "bg-warning", "bg-success", "bg-success"];
const strengthLabel = ["Very weak", "Weak", "Fair", "Good", "Strong", "Excellent"];

export default function PasswordStrength({ password }: { password: string }) {
  if (!password) return null;

  const passed = rules.filter((rule) => rule.test(password)).length;

  return (
    <div className="mt-1.5 space-y-1.5">
      <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
        <div
          className={cn("h-full rounded-full transition-all", barColor[passed])}
          style={{ width: `${(passed / rules.length) * 100}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">{strengthLabel[passed]}</p>
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {rules.map((rule) => {
          const met = rule.test(password);
          return (
            <li key={rule.label} className={cn("flex items-center gap-1", met && "text-success")}>
              <Check className={cn("size-3", met ? "opacity-100" : "opacity-30")} />
              {rule.label}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
