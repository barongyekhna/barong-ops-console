import { LoginScreen } from "@/components/login-screen";
import { PublicOnly } from "@/components/public-only";

export default function HomePage() {
  return (
    <PublicOnly>
      <LoginScreen />
    </PublicOnly>
  );
}
