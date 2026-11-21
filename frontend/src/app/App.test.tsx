import { render, screen } from '@testing-library/react';
import { expect, test } from 'vitest';

import { App } from './App';

test('renders the placeholder home', () => {
  render(<App />);
  expect(
    screen.getByRole('heading', { name: 'Modern Life RPG' }),
  ).toBeInTheDocument();
});
