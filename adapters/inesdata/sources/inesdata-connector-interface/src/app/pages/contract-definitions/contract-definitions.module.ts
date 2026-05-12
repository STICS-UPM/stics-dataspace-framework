import { NgModule } from '@angular/core';
import {ContractDefinitonsRoutingModule} from "./contract-definitions-routing.module"

import { ContractDefinitionViewerComponent } from './contract-definition-viewer/contract-definition-viewer.component';
import { SharedModule } from 'src/app/shared/shared.module';
import { ContractDefinitionNewComponent } from './contract-definition-new/contract-definition-new.component';
import { ReactiveFormsModule } from '@angular/forms';
import { MatAutocompleteModule } from '@angular/material/autocomplete';
import { MatChipsModule } from '@angular/material/chips';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

@NgModule({
  declarations: [
    ContractDefinitionViewerComponent,
    ContractDefinitionNewComponent
  ],
  imports: [
    ContractDefinitonsRoutingModule,
    SharedModule,
    MatChipsModule,
    MatAutocompleteModule,
    MatInputModule,
    MatFormFieldModule,
    MatIconModule,
    ReactiveFormsModule,
  ]
})
export class ContractDefinitionsModule { }
