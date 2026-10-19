import { HttpClient, HttpErrorResponse, HttpHeaders } from '@angular/common/http';
import { HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { testProviders } from '../../../testing/test-providers';
import { ApiError } from '../models/api.models';
import { AdminKeyService } from '../services/admin-key.service';
import { toApiError } from './api.interceptors';

describe('toApiError', () => {
  it('reports an unreachable backend without internals', () => {
    const err = toApiError(new HttpErrorResponse({ status: 0, statusText: 'Unknown Error', url: '/api/health' }));
    expect(err.code).toBe('BACKEND_UNREACHABLE');
    expect(err.message).toContain('not reachable');
  });

  it('maps the backend error envelope and field details', () => {
    const err = toApiError(
      new HttpErrorResponse({
        status: 422,
        headers: new HttpHeaders({ 'X-Request-ID': 'header-id' }),
        error: {
          error: {
            code: 'VALIDATION_ERROR',
            message: 'The request failed validation.',
            request_id: 'req-12345678',
            details: [{ loc: ['body', 'transcript'], msg: 'Field required' }],
          },
        },
      }),
    );
    expect(err).toEqual({
      status: 422,
      code: 'VALIDATION_ERROR',
      message: 'The request failed validation.',
      requestId: 'req-12345678',
      details: ['transcript: Field required'],
    });
  });

  it('falls back to a generic message for non-JSON errors', () => {
    const err = toApiError(new HttpErrorResponse({ status: 502, error: '<html>bad gateway</html>' }));
    expect(err.code).toBe('HTTP_502');
    expect(err.message).not.toContain('<html>');
  });
});

describe('interceptors', () => {
  let http: HttpClient;
  let controller: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: testProviders() });
    http = TestBed.inject(HttpClient);
    controller = TestBed.inject(HttpTestingController);
    sessionStorage.clear();
  });

  afterEach(() => controller.verify());

  it('converts HTTP failures into ApiError', () => {
    let received: ApiError | undefined;
    http.get('/api/policies').subscribe({ error: (e: ApiError) => (received = e) });
    controller.expectOne('/api/policies').flush(
      { error: { code: 'POLICY_UNAVAILABLE', message: 'Policy configuration is not loaded.', request_id: null, details: [] } },
      { status: 503, statusText: 'Service Unavailable' },
    );
    expect(received?.code).toBe('POLICY_UNAVAILABLE');
    expect(received?.status).toBe(503);
  });

  it('attaches the admin key only to policy mutations', () => {
    TestBed.inject(AdminKeyService).set('secret-key');
    http.post('/api/policies', {}).subscribe();
    http.get('/api/policies').subscribe();
    http.post('/api/process', {}).subscribe();

    const mutation = controller.expectOne((r) => r.method === 'POST' && r.url === '/api/policies');
    expect(mutation.request.headers.get('X-Admin-Key')).toBe('secret-key');
    expect(controller.expectOne((r) => r.method === 'GET').request.headers.has('X-Admin-Key')).toBe(false);
    expect(controller.expectOne('/api/process').request.headers.has('X-Admin-Key')).toBe(false);
    controller.match(() => true).forEach((r) => r.flush({}));
  });
});
