export interface Ontology {
  uri: string
  nsp: string
  prefix: string
  titles: OntologyTitle[]
  versions: OntologyVersion[]
  artifacts: OntologyArtifacts
}

export interface OntologyTitle {
  value: string
  lang: string
  _id: string
}


export interface OntologyVersion {
  name: string
  issued: string
  isReviewed: boolean
}

export interface OntologyArtifacts {
  shapes: string[]
}
