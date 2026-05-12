import { NgModule } from '@angular/core';
import {VocabulariesRoutingModule} from "./vocabularies-routing.module"
import { VocabularyViewerComponent } from './vocabulary-viewer/vocabulary-viewer.component';
import { SharedModule } from 'src/app/shared/shared.module';
import { VocabularyCreateComponent } from './vocabulary-create/vocabulary-create.component';

@NgModule({
  declarations: [
    VocabularyViewerComponent,
    VocabularyCreateComponent
  ],
  imports: [
    VocabulariesRoutingModule,
    SharedModule
  ]
})
export class VocabulariesModule { }
