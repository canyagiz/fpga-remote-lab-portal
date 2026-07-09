import { useNavigate } from "react-router-dom";
import { Dialog, DialogContent } from "@/components/ui/dialog";
import { useAuthDialog } from "../context/AuthDialogContext";
import LoginForm from "./LoginForm";
import RegisterForm from "./RegisterForm";

export default function AuthDialog() {
  const { mode, openLogin, openRegister, close } = useAuthDialog();
  const navigate = useNavigate();

  return (
    <Dialog open={mode !== null} onOpenChange={(open) => !open && close()}>
      <DialogContent>
        {mode === "login" && (
          <LoginForm
            onSuccess={() => {
              close();
              navigate("/dashboard");
            }}
            onSwitchToRegister={openRegister}
          />
        )}
        {mode === "register" && (
          <RegisterForm
            onSwitchToLogin={openLogin}
            onSuccess={() => {
              close();
              navigate("/");
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
