import { useCurrentUser } from './context';

/** "Hi, <Telegram name>" for the signed-in user (render below <AuthGate>). */
export function UserGreeting() {
  const user = useCurrentUser();
  return (
    <p data-testid="user-greeting" className="text-lg">
      Hi, {user.display_name}
    </p>
  );
}
