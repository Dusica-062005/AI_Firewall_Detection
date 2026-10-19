import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { ApplicationConfig, inject, provideAppInitializer, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideLucideConfig, provideLucideIcons } from '@lucide/angular';

import { routes } from './app.routes';
import { adminKeyInterceptor, errorInterceptor } from './core/interceptors/api.interceptors';
import { RuntimeConfigService } from './core/services/runtime-config.service';
import { APP_ICONS } from './shared/icons';

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes, withComponentInputBinding()),
    provideHttpClient(withInterceptors([adminKeyInterceptor, errorInterceptor])),
    provideAppInitializer(() => inject(RuntimeConfigService).load()),
    provideLucideIcons(...APP_ICONS),
    provideLucideConfig({ size: 16, strokeWidth: 1.75 }),
  ],
};
