import { Component, OnInit } from '@angular/core';
import { OntologyService } from 'src/app/shared/services/ontology.service';
import { Observable } from 'rxjs';
import { Ontology } from 'src/app/shared/models/ontology';

@Component({
  selector: 'app-ontology-viewer',
  templateUrl: './ontology-viewer.component.html',
  styleUrls: ['./ontology-viewer.component.scss']
})
export class OntologyViewerComponent implements OnInit {
  baseUrl: string = '';
  ontologies: Ontology[] = [];

  constructor(private ontologyService: OntologyService) {

  }

  ngOnInit(): void {
    this.baseUrl = this.ontologyService.ontologyBaseUrl;
    this.ontologyService.getOntologyLists().subscribe( (data:Ontology[]) => {
      this.ontologies = data;
    });
  }
}
