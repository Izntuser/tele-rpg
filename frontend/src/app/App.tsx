import { useState } from 'react';
import { RouterProvider } from 'react-router';

import { createAppRouter, type AppRouter } from './router';

/** The routed app. Render below <AuthGate>; tests pass a memory router. */
export function App({ router }: { router?: AppRouter }) {
  const [instance] = useState(() => router ?? createAppRouter());
  return <RouterProvider router={instance} />;
}
