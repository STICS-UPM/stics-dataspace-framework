import { NgModule } from '@angular/core';
import {OntologiesRoutingModule} from "./ontologies-routing.module"
import { OntologyViewerComponent } from './ontology-viewer/ontology-viewer.component';
import { SharedModule } from 'src/app/shared/shared.module';


@NgModule({
  declarations: [
    OntologyViewerComponent,
  ],
  imports: [
    OntologiesRoutingModule,
    SharedModule
  ]
})
export class OntologiesModule {
  

 }
