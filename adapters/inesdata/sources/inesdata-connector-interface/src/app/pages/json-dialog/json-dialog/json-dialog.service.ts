import {Injectable} from '@angular/core';
import {MatDialog} from '@angular/material/dialog';
import {NEVER, Observable} from 'rxjs';
import {JsonDialogComponent} from './json-dialog.component';
import {JsonDialogData} from './json-dialog.data';
import { showDialogUntil } from '../../../shared/utils/mat-dialog-utils';

@Injectable()
export class JsonDialogService {
  constructor(private dialog: MatDialog) {}

  /**
   * Shows JSON Detail Dialog until until$ emits / completes
   * @param data json detail dialog data
   * @param until$ observable that controls the lifetime of the dialog
   */
  showJsonDetailDialog(
    data: JsonDialogData,
    until$: Observable<any> = NEVER,
  ): Observable<unknown> {
    return showDialogUntil(
      this.dialog,
      JsonDialogComponent,
      {data, autoFocus: 'first-tabbable'},
      until$,
    );
  }
}
