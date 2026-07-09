import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "../context/AuthContext";

export default function HomePage() {
  const { user } = useAuth();

  return (
    <div className="mx-auto max-w-5xl px-6">
      <section className="py-16 text-center sm:py-24">
        <img src="/logo.png" alt="FPGA Vision" className="mx-auto mb-4 h-72 w-auto sm:h-80" />
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">FPGA Remote Lab</h1>
        <p className="mx-auto mt-3 max-w-md text-muted-foreground">
          Reserve real FPGA hardware and run your experiments remotely - no need to be on campus.
        </p>
        <div className="mt-8 flex justify-center gap-3">
          {user ? (
            <Button asChild size="lg">
              <Link to="/dashboard">Go to dashboard</Link>
            </Button>
          ) : (
            <>
              <Button asChild size="lg">
                <Link to="/register">Get started</Link>
              </Button>
              <Button asChild size="lg" variant="secondary">
                <Link to="/login">Sign in</Link>
              </Button>
            </>
          )}
        </div>

        <div className="mt-16 flex items-center justify-center gap-5">
          <span className="text-base uppercase tracking-wide text-muted-foreground">In partnership with</span>
          <a href="https://www.h-brs.de/de" target="_blank" rel="noopener noreferrer">
            <img src="/bonn-logo.png" alt="Hochschule Bonn-Rhein-Sieg" className="h-20 w-auto" />
          </a>
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
