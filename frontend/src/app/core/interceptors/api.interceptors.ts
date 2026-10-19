import { HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { catchError, throwError } from 'rxjs';

import { ApiError, ApiErrorBody } from '../models/api.models';
import { AdminKeyService } from '../services/admin-key.service';
import { RuntimeConfigService } from '../services/runtime-config.service';

const MUTATING = new Set(['POST', 'PUT', 'DELETE']);

/** Attaches the admin key to policy, audit and compliance mutations sent to the configured API only. */
export const adminKeyInterceptor: HttpInterceptorFn = (req, next) => {
  const config = inject(RuntimeConfigService);
  const admin = inject(AdminKeyService);
  const isApi = req.url.startsWith(config.apiBaseUrl);
  const isAdminPath = /\/(policies|audit\/purge|compliance)/.test(req.url) && !req.url.endsWith('/policies/validate');
  if (isApi && isAdminPath && MUTATING.has(req.method) && admin.hasKey()) {
    return next(req.clone({ setHeaders: { 'X-Admin-Key': admin.value() } }));
  }
  return next(req);
};

/** Converts any HTTP failure into a consistent ApiError without exposing internals. */
export const errorInterceptor: HttpInterceptorFn = (req, next) =>
  next(req).pipe(catchError((error: unknown) => throwError(() => toApiError(error))));

export function toApiError(error: unknown): ApiError {
  if (!(error instanceof HttpErrorResponse)) {
    return { status: 0, code: 'CLIENT_ERROR', message: 'An unexpected client error occurred.', requestId: null, details: [] };
  }
  if (error.status === 0) {
    return {
      status: 0,
      code: 'BACKEND_UNREACHABLE',
      message: 'The firewall backend is not reachable. Check that it is running and that the API URL is correct.',
      requestId: null,
      details: [],
    };
  }
  const body = (error.error as { error?: ApiErrorBody } | null)?.error;
  return {
    status: error.status,
    code: body?.code ?? `HTTP_${error.status}`,
    message: body?.message ?? `The request failed with HTTP ${error.status}.`,
    requestId: body?.request_id ?? error.headers?.get('X-Request-ID') ?? null,
    details: (body?.details ?? []).map((d) => (d.loc?.length ? `${d.loc.filter((p) => p !== 'body').join('.')}: ${d.msg}` : d.msg)),
  };
}
