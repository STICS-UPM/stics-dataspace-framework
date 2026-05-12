
import { NgModule } from '@angular/core';
import { Routes, RouterModule } from '@angular/router';
import { OntologyViewerComponent } from './ontology-viewer/ontology-viewer.component';


const routes: Routes = [
  { path: '', component: OntologyViewerComponent },

];

@NgModule({
  imports: [RouterModule.forChild(routes)],
  exports: [RouterModule]
})
export class OntologiesRoutingModule { }
