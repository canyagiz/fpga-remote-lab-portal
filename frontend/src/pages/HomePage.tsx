import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import HeroVideo from "../components/HeroVideo";
import { useAuth } from "../context/AuthContext";
import { partners } from "../config/partners";

export default function HomePage() {
  const { user } = useAuth();

  return (
    <div className="mx-auto max-w-5xl px-6">
      <section className="py-16 text-center sm:py-24">
        <HeroVideo />
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">FPGA Remote Lab</h1>
        <p className="mx-auto mt-3 max-w-md text-muted-foreground">
          Reserve real FPGA hardware and run your experiments remotely - no need to be on campus.
        </p>
        {user && (
          <div className="mt-8 flex justify-center gap-3">
            <Button asChild size="lg">
              <Link to="/dashboard">Go to dashboard</Link>
            </Button>
            <Button asChild size="lg" variant="secondary">
              <Link to="/calendar">View calendar</Link>
            </Button>
          </div>
        )}

        {/* LICENSE (Branding & Attribution Requirement, item 2): entries here
            are additive only - see src/config/partners.ts. */}
        <div className="mt-16 flex flex-wrap items-center justify-center gap-5">
          <span className="text-base uppercase tracking-wide text-muted-foreground">In partnership with</span>
          {partners.map((partner) => (
            <a key={partner.name} href={partner.url} target="_blank" rel="noopener noreferrer">
              <img
                src={partner.logo}
                alt={partner.name}
                className={partner.logoClassName ?? "h-20 w-auto"}
              />
            </a>
          ))}
        </div>
      </section>

      {/* Placeholder content - to be replaced once the hardware-access
          layer and lab catalog (Faz 4/5) land. */}
      <section className="grid gap-5 pb-16 sm:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Reserve a slot</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Book a lab for a specific time, or join the queue for immediate access.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Work from anywhere</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Access lab hardware from your browser - on campus or off.
            </p>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle>Secure by default</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Email verification on signup and session-based authentication protect every account.
            </p>
          </CardContent>
        </Card>
      </section>
    </div>
  );
}
