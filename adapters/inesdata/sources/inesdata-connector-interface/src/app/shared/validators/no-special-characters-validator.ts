import {ValidatorFn, Validators} from '@angular/forms';

/**
 * Validates whether value contains whitespaces or special characters
 * @param control control
 */
export const noSpecialCharactersValidator: ValidatorFn =
  Validators.pattern(/^[a-zA-Z0-9_-]+$/);
