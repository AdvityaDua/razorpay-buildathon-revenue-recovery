/**
 * API client hooks using TanStack Query.
 *
 * Reads from saved eval report artifact — does NOT recompute metrics live
 * (eval-harness-conventions).
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8001';

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Types
export interface AuditEntry {
  mandate_id: string;
  customer_id: string;
  amount: number;
  diagnosis: {
    cause_evaluations: Array<{
      cause: string;
      verdict: string;
      reason: string;
    }>;
    root_cause: string;
    confidence: number;
    evidence: string;
  } | null;
  diagnosis_error: string | null;
  policy_check_passed: boolean;
  policy_stop_reason: string | null;
  proposed_action: {
    action: string;
    reasoning: string;
    retry_delay_days: number | null;
  } | null;
  allowed_action: {
    action: string;
    reasoning: string;
    retry_delay_days: number | null;
    was_overridden: boolean;
    override_rule: string | null;
    original_proposed_action: string | null;
  } | null;
  simulated_outcome: string | null;
  amount_recovered: number;
  was_held: boolean;
  hold_reason: string | null;
}

export interface PrecisionRecallClass {
  precision: number;
  recall: number;
  f1: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
}

export interface Metrics {
  batch_size: number;
  diagnosis_precision_recall: Record<string, PrecisionRecallClass | { accuracy: number; total_evaluated: number; total_correct: number }>;
  self_consistency_rate: {
    rate: number;
    consistent: number;
    inconsistent: number;
    total_evaluated: number;
  };
  confidence_calibration: Array<{
    bin: string;
    count: number;
    accuracy: number;
    avg_confidence: number;
  }>;
  system_recovered_inr: number;
  baseline_recovered_inr: number;
  total_recoverable_inr: number;
  system_recovery_rate_pct: number;
  baseline_recovery_rate_pct: number;
  unnecessary_retries_avoided: {
    system_correctly_stopped: number;
    baseline_unnecessary_retries: number;
  };
  false_diagnoses: {
    total_false: number;
    by_true_class: Record<string, number>;
  };
  correctly_stopped_pct: {
    correctly_stopped: number;
    total_hard_stop_cases: number;
    percentage: number;
  };
  policy_override_count: number;
  n_errors: number;
  n_held: number;
}

export interface RecordsResponse {
  records: AuditEntry[];
  metadata: {
    timestamp: string;
    batch_size: number;
    n_errors: number;
  };
}

export interface MetricsResponse {
  metrics: Metrics;
  metadata: {
    timestamp: string;
    batch_size: number;
    n_errors: number;
  };
}

// Hooks

export function useRecords() {
  return useQuery<RecordsResponse>({
    queryKey: ['records'],
    queryFn: () => fetchJSON('/api/records'),
    staleTime: 5 * 60 * 1000, // 5 min — data is from saved report
  });
}

export function useMetrics() {
  return useQuery<MetricsResponse>({
    queryKey: ['metrics'],
    queryFn: () => fetchJSON('/api/metrics'),
    staleTime: 5 * 60 * 1000,
  });
}

export function useTriggerBatch() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () =>
      fetch(`${API_BASE}/api/batch/run`, { method: 'POST' }).then((r) => r.json()),
    onSuccess: () => {
      // Invalidate queries so they refresh after batch completes
      queryClient.invalidateQueries({ queryKey: ['records'] });
      queryClient.invalidateQueries({ queryKey: ['metrics'] });
    },
  });
}

export function useSimulate() {
  return useMutation({
    mutationFn: async (record: any) => {
      const res = await fetch(`${API_BASE}/api/simulate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(record),
      });
      if (!res.ok) throw new Error('Simulation failed');
      return res.json() as Promise<AuditEntry>;
    },
  });
}
