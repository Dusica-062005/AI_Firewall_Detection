import { HttpBackend, HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';

interface RuntimeConfig {
  apiBaseUrl: string;
}

/**
 * Loads /config.json at startup so service URLs are configured per environment
 * without rebuilding the application.
 */
@Injectable({ providedIn: 'root' })
export class RuntimeConfigService {
  // HttpBackend bypasses interceptors, which depend on this configuration.
  private readonly http = new HttpClient(inject(HttpBackend));
  private config: RuntimeConfig = { apiBaseUrl: '/api' };

  async load(): Promise<void> {
    try {
      const loaded = await firstValueFrom(this.http.get<RuntimeConfig>('config.json'));
      if (loaded?.apiBaseUrl) {
        this.config = { apiBaseUrl: loaded.apiBaseUrl.replace(/\/+$/, '') };
      }
    } catch {
      // Keep the relative default; the UI reports connectivity problems explicitly.
    }
  }

  get apiBaseUrl(): string {
    return this.config.apiBaseUrl;
  }

  url(path: string): string {
    return `${this.apiBaseUrl}${path.startsWith('/') ? path : `/${path}`}`;
  }
}
