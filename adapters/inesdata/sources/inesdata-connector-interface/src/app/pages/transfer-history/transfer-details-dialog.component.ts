import { Component, Inject } from '@angular/core';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';

@Component({
  selector: 'app-transfer-details-dialog',
  templateUrl: './transfer-details-dialog.component.html',
  styles: [`
    .details-pre {
      margin: 0;
      max-height: 60vh;
      overflow: auto;
      white-space: pre-wrap;
      word-break: break-word;
    }
  `]
})
export class TransferDetailsDialogComponent {
  constructor(
    public dialogRef: MatDialogRef<TransferDetailsDialogComponent>,
    @Inject(MAT_DIALOG_DATA) public data: { title: string; content: string }
  ) {
    dialogRef.disableClose = false;
  }

  close() {
    this.dialogRef.close();
  }
}
