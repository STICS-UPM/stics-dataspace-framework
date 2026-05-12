import {Component, Inject} from '@angular/core';
import { MAT_DIALOG_DATA } from '@angular/material/dialog';

export interface DialogData {
  title: string;
  rules: any;
}

@Component({
  selector: 'policy-rules',
  templateUrl: './policy-rule-viewer.component.html'
})
export class PolicyRuleViewerComponent {

  constructor(@Inject(MAT_DIALOG_DATA) public data: DialogData) {}
}
