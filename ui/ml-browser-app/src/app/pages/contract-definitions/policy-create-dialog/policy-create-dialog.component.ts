import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ReactiveFormsModule, FormsModule } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatDatepickerModule } from '@angular/material/datepicker';
import { MatNativeDateModule } from '@angular/material/core';

import { PolicyService } from '../../../shared/services/policy.service';
import { NotificationService } from '../../../shared/services/notification.service';

export interface PolicyConstraint {
  leftOperand: string;
  operator: string;
  rightOperand: string;
}

export interface PolicyPermission {
  action: string;
  constraints: PolicyConstraint[];
}

@Component({
  selector: 'app-policy-create-dialog',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatDatepickerModule,
    MatNativeDateModule
  ],
  templateUrl: './policy-create-dialog.component.html',
  styleUrl: './policy-create-dialog.component.scss'
})
export class PolicyCreateDialogComponent {
  private readonly policyService = inject(PolicyService);
  private readonly notificationService = inject(NotificationService);
  private readonly dialogRef = inject(MatDialogRef<PolicyCreateDialogComponent>);

  policyId = '';
  templateType: 'open' | 'action' = 'open';
  action = 'USE';
  
  // Constraint fields
  constraints: PolicyConstraint[] = [];
  currentConstraint: PolicyConstraint = {
    leftOperand: '',
    operator: 'EQ',
    rightOperand: ''
  };
  currentDate: Date | null = null;

  // Supported values
  supportedActions = ['USE', 'TRANSFER', 'DELETE'];
  readonly policyTemplates = [
    { value: 'open', label: 'Open Policy (Template)', hint: 'Matches create-policy.json with empty permission/prohibition/obligation' },
    { value: 'action', label: 'Action Policy', hint: 'Adds one permission with optional constraints' }
  ] as const;
  
  supportedLeftOperands = [
    { value: 'BusinessPartnerNumber', label: 'Business Partner Number', hint: 'Partner identification number' },
    { value: 'DataspaceIdentifier', label: 'Dataspace Identifier', hint: 'Dataspace where connector belongs' },
    { value: 'REFERRING_CONNECTOR', label: 'Referring Connector', hint: 'URL of the connector making the request' },
    { value: 'POLICY_EVALUATION_TIME', label: 'Policy Evaluation Time', hint: 'Time when policy is evaluated' },
    { value: 'PURPOSE', label: 'Purpose', hint: 'Intended purpose of data usage' }
  ];

  supportedOperators = [
    { value: 'EQ', label: '= (Equal)', hint: 'Equal to' },
    { value: 'NEQ', label: '≠ (Not Equal)', hint: 'Not equal to' },
    { value: 'GT', label: '> (Greater Than)', hint: 'Greater than' },
    { value: 'GEQ', label: '≥ (Greater or Equal)', hint: 'Greater than or equal to' },
    { value: 'LT', label: '< (Less Than)', hint: 'Less than' },
    { value: 'LEQ', label: '≤ (Less or Equal)', hint: 'Less than or equal to' },
    { value: 'IN', label: 'IN', hint: 'Value is in list' }
  ];

  addConstraint(): void {
    if (!this.currentConstraint.leftOperand || !this.currentConstraint.rightOperand) {
      this.notificationService.showError('Please fill all constraint fields');
      return;
    }

    this.constraints.push({ ...this.currentConstraint });
    
    // Reset for next constraint
    this.currentConstraint = {
      leftOperand: '',
      operator: 'EQ',
      rightOperand: ''
    };
    this.currentDate = null;
  }

  removeConstraint(index: number): void {
    this.constraints.splice(index, 1);
  }

  getLeftOperandLabel(value: string): string {
    return this.supportedLeftOperands.find(op => op.value === value)?.label || value;
  }

  getOperatorLabel(value: string): string {
    return this.supportedOperators.find(op => op.value === value)?.label || value;
  }

  isDateField(): boolean {
    return this.currentConstraint.leftOperand === 'POLICY_EVALUATION_TIME';
  }

  onDateChange(date: Date | null): void {
    if (date) {
      // Convert date to ISO string format
      this.currentConstraint.rightOperand = date.toISOString();
      this.currentDate = date;
    } else {
      this.currentConstraint.rightOperand = '';
      this.currentDate = null;
    }
  }

  onLeftOperandChange(): void {
    // Clear right operand when changing left operand
    this.currentConstraint.rightOperand = '';
    this.currentDate = null;
  }

  onCreate(): void {
    if (!this.policyId) {
      this.notificationService.showError('Policy ID is required');
      return;
    }

    // Build ODRL policy structure aligned with EDC templates.
    const policyDefinition: any = {
      '@id': this.policyId,
      policy: {
        '@context': 'http://www.w3.org/ns/odrl.jsonld',
        '@type': 'Set',
        permission: this.templateType === 'open'
          ? []
          : [{
              action: this.action,
              ...(this.constraints.length > 0 && {
                constraint: this.constraints.map(c => ({
                  leftOperand: c.leftOperand,
                  operator: c.operator,
                  rightOperand: c.rightOperand
                }))
              })
            }],
        prohibition: [],
        obligation: []
      }
    };

    console.log('[Policy Create Dialog] Creating policy:', policyDefinition);

    this.policyService.createPolicy(policyDefinition).subscribe({
      next: (result) => {
        this.notificationService.showInfo('Policy created successfully');
        this.dialogRef.close({ '@id': this.policyId });
      },
      error: (error) => {
        console.error('[Policy Create Dialog] Error creating policy:', error);
        const errorMsg = error?.error?.message || error?.message || 'Unknown error';
        this.notificationService.showError(`Failed to create policy: ${errorMsg}`);
      }
    });
  }

  onCancel(): void {
    this.dialogRef.close();
  }
}
