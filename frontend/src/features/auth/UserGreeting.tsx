import { useTranslation } from 'react-i18next';

import { useCurrentUser } from './context';

/** "Hi, <Telegram name>" for the signed-in user (render below <AuthGate>). */
export function UserGreeting() {
  const { t } = useTranslation();
  const user = useCurrentUser();
  return (
    <p data-testid="user-greeting" className="text-lg">
      {t('auth.greeting', { name: user.display_name })}
    </p>
  );
}
