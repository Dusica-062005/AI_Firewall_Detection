import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { EnvironmentProviders, Provider } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideLucideIcons } from '@lucide/angular';

import { adminKeyInterceptor, errorInterceptor } from '../app/core/interceptors/api.interceptors';
import { APP_ICONS } from '../app/shared/icons';

/** Providers matching app.config.ts, with the HTTP backend replaced by the testing controller. */
export function testProviders(): (Provider | EnvironmentProviders)[] {
  return [
    provideRouter([]),
    provideHttpClient(withInterceptors([adminKeyInterceptor, errorInterceptor])),
    provideHttpClientTesting(),
    provideLucideIcons(...APP_ICONS),
  ];
}
