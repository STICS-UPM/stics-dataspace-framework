import { enableProdMode } from '@angular/core';
import { platformBrowserDynamic } from '@angular/platform-browser-dynamic';

import { AppModule } from './app/app.module';
import { environment } from './environments/environment';

import { runtimeEnvLoader as runtimeEnvLoaderPromise } from './assets/config/runtimeEnvLoader';

function isCssColor(value: unknown): value is string {
  if (typeof value !== 'string') {
    return false;
  }
  const normalized = value.trim();
  return /^#[0-9a-fA-F]{3}([0-9a-fA-F]{3})?$/.test(normalized)
    || /^rgb(a)?\([^)]+\)$/.test(normalized)
    || /^hsl(a)?\([^)]+\)$/.test(normalized);
}

function applyRuntimeBranding(runtimeEnv: any): void {
  const branding = runtimeEnv?.branding || {};
  const root = document.documentElement;
  const primaryColor = `${branding.primaryColor || ''}`.trim();
  const secondaryColor = `${branding.secondaryColor || ''}`.trim();

  if (isCssColor(primaryColor)) {
    root.style.setProperty('--brand-500', primaryColor);
    root.style.setProperty('--mdc-linear-progress-active-indicator-color', primaryColor);
  }

  if (isCssColor(secondaryColor)) {
    root.style.setProperty('--secondary-500', secondaryColor);
    root.style.setProperty('--secondary-600', secondaryColor);
    root.style.setProperty('--mdc-list-list-item-label-text-color', secondaryColor);
    root.style.setProperty('--mdc-list-list-item-hover-label-text-color', secondaryColor);
    root.style.setProperty('--mdc-list-list-item-focus-label-text-color', secondaryColor);
    root.style.setProperty('--mat-mdc-button-persistent-ripple-color', secondaryColor);
  }
}

runtimeEnvLoaderPromise.then(runtimeEnv => {

  if (environment.production) {
    enableProdMode();

    window.console.log = () => { }
    window.console.error = () => { }
    window.console.trace = () => { }
    window.console.debug = () => { }
  }

  if (runtimeEnv) {
    environment.runtime = runtimeEnv;
    applyRuntimeBranding(runtimeEnv);
  }

  platformBrowserDynamic().bootstrapModule(AppModule)
    .catch(err => console.error(err));

});
