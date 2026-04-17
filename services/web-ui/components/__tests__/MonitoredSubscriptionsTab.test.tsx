/**
 * @jest-environment jsdom
 */
// services/web-ui/components/__tests__/MonitoredSubscriptionsTab.test.tsx
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MonitoredSubscriptionsTab } from '../MonitoredSubscriptionsTab'

// Mock fetch
beforeEach(() => {
  global.fetch = jest.fn()
})

const mockSubscriptions = [
  {
    subscription_id: '4c727b88-12f4-4c91-9c2b-372aab3bbae9',
    display_name: 'Production',
    credential_type: 'mi',
    client_id: null,
    permission_status: { reader: 'granted', monitoring_reader: 'granted' },
    secret_expires_at: null,
    days_until_expiry: null,
    last_validated_at: '2026-04-17T00:00:00Z',
    monitoring_enabled: true,
    environment: 'prod',
  },
]

test('renders subscription list from API', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: mockSubscriptions, total: 1 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() => expect(screen.getByText('Production')).toBeInTheDocument())
  expect(screen.getByText('1')).toBeInTheDocument() // total badge
})

test('shows info banner collapsed by default', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: [], total: 0 }),
  })

  render(<MonitoredSubscriptionsTab />)

  expect(screen.getByText(/How to onboard/i)).toBeInTheDocument()
  // Banner content should be hidden initially
  expect(screen.queryByText(/Step 1: Create an App Registration/i)).not.toBeInTheDocument()
})

test('shows Add Subscription button', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: [], total: 0 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() => expect(screen.getByRole('button', { name: /Add/i })).toBeInTheDocument())
})

test('shows MI badge for platform-managed subscriptions', async () => {
  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({ subscriptions: mockSubscriptions, total: 1 }),
  })

  render(<MonitoredSubscriptionsTab />)

  await waitFor(() =>
    expect(screen.getByText(/Platform MI/i)).toBeInTheDocument()
  )
})
