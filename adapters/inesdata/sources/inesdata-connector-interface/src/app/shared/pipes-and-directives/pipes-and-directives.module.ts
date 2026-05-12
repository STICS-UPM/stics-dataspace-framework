import {CommonModule} from '@angular/common';
import {NgModule} from '@angular/core';
import {MatIconModule} from '@angular/material/icon';
import {MatProgressSpinnerModule} from '@angular/material/progress-spinner';
import {CompareByFieldPipe} from './pipes/compare-by-field.pipe';
import {ValuesPipe} from './pipes/values.pipe';

@NgModule({
  imports: [
    // Angular
    CommonModule,

    // Angular Material
    MatIconModule,
    MatProgressSpinnerModule,
  ],
  declarations: [
    CompareByFieldPipe,
    ValuesPipe,
  ],
  exports: [
    CompareByFieldPipe,
    ValuesPipe,
  ],
})
export class PipesAndDirectivesModule {}
