/** @jest-environment jsdom */

import React from 'react';
import { afterEach, beforeEach, describe, expect, it, jest } from '@jest/globals';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OpsTab } from '../components/OpsTab';

type MockJson = Record<string, unknown> | Array<unknown> | null;

function mockResponse(status: number, body: MockJson): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function queueOpsFetches(options?: {
  platformHealth?: MockJson;
  incidents?: MockJson;
  breaches?: MockJson;
  patternsStatus?: number;
  patternsBody?: MockJson;
}): void {
  const {
    platformHealth = {
      detection_pipeline_lag_seconds: null,
      auto_remediation_success_rate: null,
      noise_reduction_pct: null,
      slo_compliance_pct: null,
      automation_savings_count: 0,
      error_budget_portfolio: [],
      mttr_p50_minutes: null,
      mttr_p95_minutes: null,
    },
    incidents = [],
    breaches = [],
    patternsStatus = 404,
    patternsBody = null,
  } = options ?? {};

  const fetchMock = global.fetch as jest.MockedFunction<typeof fetch>;
  fetchMock
    .mockResolvedValueOnce(mockResponse(200, platformHealth))
    .mockResolvedValueOnce(mockResponse(200, incidents))
    .mockResolvedValueOnce(mockResponse(200, breaches))
    .mockResolvedValueOnce(mockResponse(patternsStatus, patternsBody));
}

describe('OpsTab', () => {
  beforeEach(() => {
    jest.resetAllMocks();
    global.fetch = jest.fn() as unknown as jest.MockedFunction<typeof fetch>;

    if (!('timeout' in AbortSignal)) {
      (globalThis.AbortSignal as typeof AbortSignal & { timeout?: (ms: number) => AbortSignal }).timeout =
        (() => undefined as unknown as AbortSignal);
    }
  });

  afterEach(() => {
    cleanup();
  });

  it('requests incidents without the unsupported open status filter', async () => {
    queueOpsFetches();

    render(<OpsTab subscriptions={[]} />);

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(4);
      expect((global.fetch as jest.Mock).mock.calls[1]?.[0]).toBe('/api/proxy/incidents?limit=50');
    });
  });

  it('shows unknown platform status when no health signals are present', async () => {
    queueOpsFetches();

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText('Platform Status Unknown')).toBeTruthy();
  });

  it('renders active Sev0 and Sev1 incidents while excluding closed and lower severities', async () => {
    queueOpsFetches({
      incidents: [
        {
          incident_id: 'inc-sev1-new',
          severity: 'Sev1',
          domain: 'compute',
          resource_name: 'jumphost',
          created_at: '2026-04-14T08:00:00Z',
          investigation_status: 'evidence_ready',
          status: 'new',
        },
        {
          incident_id: 'inc-sev0-ack',
          severity: 'Sev0',
          domain: 'security',
          resource_name: 'keyvault-prod',
          created_at: '2026-04-14T08:01:00Z',
          investigation_status: 'investigating',
          status: 'acknowledged',
        },
        {
          incident_id: 'inc-sev1-closed',
          severity: 'Sev1',
          domain: 'network',
          resource_name: 'nsg-edge',
          created_at: '2026-04-14T08:02:00Z',
          investigation_status: 'resolved',
          status: 'closed',
        },
        {
          incident_id: 'inc-sev2-new',
          severity: 'Sev2',
          domain: 'storage',
          resource_name: 'sa-prod',
          created_at: '2026-04-14T08:03:00Z',
          investigation_status: 'pending',
          status: 'new',
        },
      ],
    });

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText('jumphost')).toBeTruthy();
    expect(screen.getByText('keyvault-prod')).toBeTruthy();
    expect(screen.queryByText('nsg-edge')).toBeNull();
    expect(screen.queryByText('sa-prod')).toBeNull();
    expect(screen.queryByText('No active P1 or P2 incidents')).toBeNull();
  });

  it('renders imminent breaches when the API returns a bare array payload', async () => {
    queueOpsFetches({
      breaches: [
        {
          resource_id: '/subscriptions/sub-1/resourceGroups/rg/providers/Microsoft.Compute/virtualMachines/jumphost',
          metric: 'Percentage CPU',
          minutes_to_breach: 12,
          confidence: 0.84,
        },
      ],
    });

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText(/Percentage CPU/)).toBeTruthy();
    expect(screen.getByText('12m')).toBeTruthy();
    expect(screen.queryByText('No breaches predicted in next 60 minutes')).toBeNull();
  });

  it('renders recurring patterns from backend IncidentPattern fields', async () => {
    queueOpsFetches({
      patternsStatus: 200,
      patternsBody: {
        analysis_id: 'analysis-1',
        analysis_date: '2026-04-14',
        period_days: 7,
        total_incidents_analyzed: 25,
        top_patterns: [
          {
            pattern_id: 'compute:HighCPU:Sev1',
            domain: 'compute',
            resource_type: 'microsoft.compute/virtualmachines',
            detection_rule: 'HighCPU',
            incident_count: 12,
            frequency_per_week: 4.2,
            avg_severity_score: 3.0,
            top_title_words: ['cpu', 'spike'],
            first_seen: '2026-04-07T00:00:00Z',
            last_seen: '2026-04-14T00:00:00Z',
            operator_flagged: false,
            common_feedback: ['Tune CPU alert thresholds'],
          },
        ],
        finops_summary: {
          estimated_monthly_savings_usd: 1200,
          top_waste_resources: ['jumphost'],
        },
        mttr_summary: {},
        generated_at: '2026-04-14T08:00:00Z',
      },
    });

    render(<OpsTab subscriptions={[]} />);

    expect((await screen.findAllByText('compute')).length).toBeGreaterThan(0);
    expect(screen.getByText('HighCPU')).toBeTruthy();
    expect(screen.getByText('×12')).toBeTruthy();
    expect(screen.getByText(/Tune CPU alert thresholds/)).toBeTruthy();
  });

  it('shows backend remediation percentage without multiplying it again', async () => {
    queueOpsFetches({
      platformHealth: {
        detection_pipeline_lag_seconds: 1,
        auto_remediation_success_rate: 75,
        noise_reduction_pct: 82,
        slo_compliance_pct: 99.7,
        automation_savings_count: 5,
        error_budget_portfolio: [],
        mttr_p50_minutes: 10,
        mttr_p95_minutes: 20,
      },
    });

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText('75.0%')).toBeTruthy();
    expect(screen.queryByText('7500.0%')).toBeNull();
    expect(screen.getByText('Platform Healthy')).toBeTruthy();
  });

  it('normalizes decimal auto-remediation rates into percentages, including 100 percent', async () => {
    queueOpsFetches({
      platformHealth: {
        detection_pipeline_lag_seconds: 1,
        auto_remediation_success_rate: 0.82,
        noise_reduction_pct: 82,
        slo_compliance_pct: 99.7,
        automation_savings_count: 5,
        error_budget_portfolio: [],
        mttr_p50_minutes: 10,
        mttr_p95_minutes: 20,
      },
    });

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText('82.0%')).toBeTruthy();
    expect(screen.getByText('Platform Healthy')).toBeTruthy();

    cleanup();
    queueOpsFetches({
      platformHealth: {
        detection_pipeline_lag_seconds: 1,
        auto_remediation_success_rate: 1,
        noise_reduction_pct: 82,
        slo_compliance_pct: 99.7,
        automation_savings_count: 5,
        error_budget_portfolio: [],
        mttr_p50_minutes: 10,
        mttr_p95_minutes: 20,
      },
    });

    render(<OpsTab subscriptions={[]} />);

    expect(await screen.findByText('100.0%')).toBeTruthy();
    expect(screen.getByText('Platform Healthy')).toBeTruthy();
  });

  it('navigates to alerts through the provided callback when overflow is clicked', async () => {
    queueOpsFetches({
      incidents: Array.from({ length: 11 }, (_, index) => ({
        incident_id: `inc-${index}`,
        severity: 'Sev1',
        domain: 'compute',
        resource_name: `vm-${index}`,
        created_at: `2026-04-14T08:${String(index).padStart(2, '0')}:00Z`,
        investigation_status: 'evidence_ready',
        status: 'new',
      })),
    });

    const onNavigateToAlerts = jest.fn();
    render(<OpsTab subscriptions={[]} onNavigateToAlerts={onNavigateToAlerts} />);

    const button = await screen.findByRole('button', { name: /view 1 more in alerts tab/i });
    fireEvent.click(button);

    expect(onNavigateToAlerts).toHaveBeenCalledTimes(1);
  });
});