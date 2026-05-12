
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { VocabularyViewerComponent } from './vocabulary-viewer/vocabulary-viewer.component';
import { VocabularyCreateComponent } from './vocabulary-create/vocabulary-create.component';

const routes: Routes = [
  { path: '', component: VocabularyViewerComponent },
  { path: 'create', component: VocabularyCreateComponent }
];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class VocabulariesRoutingModule { }
