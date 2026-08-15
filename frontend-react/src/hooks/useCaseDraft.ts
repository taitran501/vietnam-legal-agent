import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { resolveCaseForm, type CaseFormFactUpdate } from '@/api/caseForm';
import type { CaseFormState, CaseState, FactValue } from '@/types';
import { caseFormErrorMessage } from '@/lib/userCopy';

type DraftStatus = 'idle' | 'resolving' | 'editing' | 'ready' | 'submitting' | 'failed';
type ConfirmationStatus = 'user_confirmed' | 'document_verified' | 'unknown';
type DraftErrorPhase = 'resolve' | 'submit';

function plainFacts(caseState?: CaseState | CaseFormState | null): Record<string, string> {
  return Object.fromEntries(Object.entries(caseState?.facts || {}).map(([key, value]) => [
    key,
    typeof value === 'string' ? value : (value as FactValue)?.value || '',
  ]));
}

function statusesFor(caseState?: CaseState | CaseFormState | null): Record<string, ConfirmationStatus> {
  return Object.fromEntries(Object.entries(caseState?.facts || {}).map(([key, value]) => [
    key,
    typeof value === 'string' ? 'unknown' : (value as FactValue)?.confirmation_status || 'unknown',
  ])) as Record<string, ConfirmationStatus>;
}

function updatesFor(facts: Record<string, string>, statuses: Record<string, ConfirmationStatus>): Record<string, CaseFormFactUpdate> {
  return Object.fromEntries(Object.entries(facts).filter(([, value]) => value.trim()).map(([key, value]) => [key, {
    value,
    confirmation_status: statuses[key] || 'user_confirmed',
  }]));
}

export function useCaseDraft(
  taskType: CaseState['task_type'],
  initialCaseState: CaseState | CaseFormState | null | undefined,
  onSubmit: (facts: Record<string, string>, statuses: Record<string, ConfirmationStatus>, taskType: CaseState['task_type']) => Promise<void>,
) {
  const initialised = useRef(false);
  const requestSequence = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const [facts, setFacts] = useState<Record<string, string>>(() => plainFacts(initialCaseState));
  const [statuses, setStatuses] = useState<Record<string, ConfirmationStatus>>(() => statusesFor(initialCaseState));
  const [formState, setFormState] = useState<CaseFormState | null>(() => initialCaseState && 'form_version' in initialCaseState && 'fields' in initialCaseState
    ? initialCaseState as CaseFormState
    : null);
  const [status, setStatus] = useState<DraftStatus>(initialCaseState ? 'editing' : 'idle');
  const [error, setError] = useState('');
  const [errorPhase, setErrorPhase] = useState<DraftErrorPhase>('resolve');
  const [baseline, setBaseline] = useState(() => JSON.stringify({ facts: plainFacts(initialCaseState), statuses: statusesFor(initialCaseState), taskType }));

  const resolve = useCallback(async (signal?: AbortSignal) => {
    const sequence = ++requestSequence.current;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    if (signal) signal.addEventListener('abort', () => controller.abort(), { once: true });
    setStatus('resolving');
    try {
      const next = await resolveCaseForm(taskType, updatesFor(facts, statuses), controller.signal);
      if (sequence !== requestSequence.current) return;
      setFormState(next);
      setError('');
      setErrorPhase('resolve');
      setStatus(next.validation_errors && Object.keys(next.validation_errors).length ? 'editing' : next.status === 'ready' ? 'ready' : 'editing');
    } catch (cause) {
      if (controller.signal.aborted || sequence !== requestSequence.current) return;
      setError(caseFormErrorMessage(cause));
      setErrorPhase('resolve');
      setStatus('editing');
    }
  }, [facts, statuses, taskType]);

  useEffect(() => {
    if (!initialised.current) {
      initialised.current = true;
      if (!initialCaseState) void resolve();
      return;
    }
    const timer = window.setTimeout(() => void resolve(), 250);
    return () => window.clearTimeout(timer);
  }, [facts, statuses, taskType, initialCaseState, resolve]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const setFact = useCallback((key: string, value: string) => {
    setFacts((current) => ({ ...current, [key]: value }));
    setStatuses((current) => ({ ...current, [key]: 'user_confirmed' }));
    setError('');
  }, []);

  const submit = useCallback(async () => {
    if (!formState || formState.status !== 'ready' || Object.keys(formState.validation_errors || {}).length || formState.submission_blocked_reason) return false;
    setStatus('submitting');
    setError('');
    try {
      await onSubmit(facts, statuses, taskType);
      setBaseline(JSON.stringify({ facts, statuses, taskType }));
      setStatus('ready');
      return true;
    } catch (cause) {
      setError(caseFormErrorMessage(cause));
      setErrorPhase('submit');
      setStatus('failed');
      return false;
    }
  }, [facts, formState, onSubmit, statuses, taskType]);

  const retry = useCallback(() => {
    if (errorPhase === 'submit') return submit();
    return resolve();
  }, [errorPhase, resolve, submit]);

  const dirty = useMemo(() => JSON.stringify({ facts, statuses, taskType }) !== baseline, [baseline, facts, statuses, taskType]);
  const discard = useCallback(() => {
    if (initialCaseState) {
      setFacts(plainFacts(initialCaseState));
      setStatuses(statusesFor(initialCaseState));
    } else {
      setFacts({});
      setStatuses({});
    }
    setError('');
  }, [initialCaseState]);

  return {
    facts,
    statuses,
    formState,
    status,
    error,
    dirty,
    isReady: formState?.status === 'ready'
      && Object.keys(formState.validation_errors || {}).length === 0
      && !formState.submission_blocked_reason,
    errorPhase,
    setFact,
    submit,
    retry,
    resolve,
    discard,
  };
}
