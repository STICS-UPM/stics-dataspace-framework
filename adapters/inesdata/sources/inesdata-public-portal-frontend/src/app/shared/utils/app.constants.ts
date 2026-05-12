import { marker as translate } from '@colsen1991/ngx-translate-extract-marker';

/**
 * Global constants
 */

// Language
export const DEFAULT_LANGUAGE: string = 'es';
export const AVAILABLE_LANGUAGES: Array<string> = ['es', 'en'];
export const LANGUAGE_STORAGE_NAME: string = 'language';

// Messages
export const MESSAGES_SUCCESS: string = translate('messages.success');
export const MESSAGES_ERRORS: string = translate('messages.errors.title');
export const MESSAGES_ERRORS_GENERIC: string = translate('messages.errors.generic');
export const MESSAGES_ERRORS_INTERNET_CONNECTION: string = translate('messages.errors.internet.connection');
export const MESSAGES_ERRORS_LOGIN: string = translate('messages.errors.login');
export const MESSAGES_ERRORS_REQUIRED: string = translate('messages.errors.required');

// Labels
export const LABELS_YES: string = translate('labels.yes');
export const LABELS_NO: string = translate('labels.no');

export const ASSET_TYPES = {
  dataset: 'dataset',
  service: 'service',
  machineLearning: 'machineLearning'
}
