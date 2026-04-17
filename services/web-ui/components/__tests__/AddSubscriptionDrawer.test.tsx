/**
 * @jest-environment jsdom
 */
// services/web-ui/components/__tests__/AddSubscriptionDrawer.test.tsx
import React from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AddSubscriptionDrawer } from '../AddSubscriptionDrawer'

beforeEach(() => {
  global.fetch = jest.fn()
})

test('Validate button calls preview-validate endpoint', async () => {
  const user = userEvent.setup()
  const onSuccess = jest.fn()

  ;(global.fetch as jest.Mock).mockResolvedValueOnce({
    ok: true,
    json: async () => ({
      auth_ok: true,
      permission_status: { reader: 'granted', monitoring_reader: 'granted' },
    }),
  })

  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={onSuccess} />)

  await user.type(screen.getByLabelText(/Subscription ID/i), '4c727b88-12f4-4c91-9c2b-372aab3bbae9')
  await user.type(screen.getByLabelText(/Tenant ID/i), '11111111-2222-3333-4444-555555555555')
  await user.type(screen.getByLabelText(/Client ID/i), 'aaaabbbb-cccc-dddd-eeee-ffffffffffff')
  await user.type(screen.getByLabelText(/Client Secret/i), 's3cr3t')

  await user.click(screen.getByRole('button', { name: /Validate/i }))

  await waitFor(() =>
    expect(global.fetch).toHaveBeenCalledWith(
      '/api/proxy/subscriptions/onboard/preview-validate',
      expect.objectContaining({ method: 'POST' }),
    )
  )
  expect(screen.getAllByText(/reader/i).length).toBeGreaterThan(0)
})

test('Save button is disabled until Reader permission is confirmed', async () => {
  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={jest.fn()} />)
  expect(screen.getByRole('button', { name: /Save/i })).toBeDisabled()
})

test('Save button calls onboard endpoint on click', async () => {
  const user = userEvent.setup()
  const onSuccess = jest.fn()

  // First call: preview-validate
  ;(global.fetch as jest.Mock)
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        auth_ok: true,
        permission_status: { reader: 'granted' },
      }),
    })
    // Second call: onboard
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ subscription_id: '4c727b88-12f4-4c91-9c2b-372aab3bbae9' }),
    })

  render(<AddSubscriptionDrawer open={true} onClose={() => {}} onSuccess={onSuccess} />)

  await user.type(screen.getByLabelText(/Subscription ID/i), '4c727b88-12f4-4c91-9c2b-372aab3bbae9')
  await user.type(screen.getByLabelText(/Tenant ID/i), '11111111-2222-3333-4444-555555555555')
  await user.type(screen.getByLabelText(/Client ID/i), 'aaaabbbb-cccc-dddd-eeee-ffffffffffff')
  await user.type(screen.getByLabelText(/Client Secret/i), 's3cr3t')
  await user.click(screen.getByRole('button', { name: /Validate/i }))

  await waitFor(() => screen.getByRole('button', { name: /Save/i }))
  const saveBtn = screen.getByRole('button', { name: /Save/i })
  expect(saveBtn).not.toBeDisabled()
  await user.click(saveBtn)

  await waitFor(() => expect(onSuccess).toHaveBeenCalled())
})
