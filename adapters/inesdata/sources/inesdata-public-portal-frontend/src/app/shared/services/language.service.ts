import { Injectable } from '@angular/core';
import { TranslateService } from '@ngx-translate/core';
import { NGXLogger } from 'ngx-logger';
import { AVAILABLE_LANGUAGES, DEFAULT_LANGUAGE, LANGUAGE_STORAGE_NAME } from '../utils/app.constants';

/**
 * Language service management
 */
@Injectable({
  providedIn: 'root'
})
export class LanguageService {
  /**
   * Language service constructor
   *
   * @param translateService Translate service
   */
  constructor(private translateService: TranslateService, private logger: NGXLogger) {
    this.logger.info('START translateService');
    translateService.addLangs(AVAILABLE_LANGUAGES);

    if (localStorage.getItem(LANGUAGE_STORAGE_NAME)) {
      // Get language stored in localStorage and use it
      translateService.setDefaultLang(localStorage.getItem(LANGUAGE_STORAGE_NAME));
      translateService.use(localStorage.getItem(LANGUAGE_STORAGE_NAME));
    } else {
      // Use default language
      translateService.setDefaultLang(DEFAULT_LANGUAGE);
      translateService.use(DEFAULT_LANGUAGE);
      localStorage.setItem(LANGUAGE_STORAGE_NAME, DEFAULT_LANGUAGE);
    }
  }

  /**
   * Gets the list of available languages
   *
   * @returns Languages list
   */
  getLanguages() {
    return this.translateService.langs;
  }

  /**
   * Set the selected language to the service and store in localStorage
   *
   * @param lang Language to use
   */
  setLanguage(lang: string) {
    this.translateService.use(lang);
    this.translateService.setDefaultLang(lang);
    localStorage.setItem(LANGUAGE_STORAGE_NAME, lang);
  }

  /**
   * Gets the current selected language
   *
   * @returns Current language
   */
  getCurrentLanguage() {
    return this.translateService.currentLang;
  }

  /**
   * Translates the key using the service
   *
   * @param key the value
   * @param [params] the parameters to interpolate
   * @returns Translation
   */
  translateValue(key: string, params?: any) {
    return this.translateService.instant(key, params);
  }
}
