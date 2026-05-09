import {NgModule} from '@angular/core';
import {RouterModule, Routes} from '@angular/router';
import { AuthUserGuard } from "./auth/auth-user.guard";

export const routes: Routes = [
  {
    path: 'catalog',
    data: {title: 'Catalog Browser', icon: 'sim_card'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/catalog/catalog.module').then(m => m.CatalogModule)
  },
  {
    path: 'contracts',
    data: {title: 'Contracts', icon: 'attachment'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/contracts/contracts.module').then(m => m.ContractsModule)
  },
  {
    path: 'transfer-history',
    data: {title: 'Transfer History', icon: 'assignment'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/transfer-history/transfer-history.module').then(m => m.TransferHistoryModule)
  },
  {
    path: 'contract-definitions',
    data: {title: 'Contract Definitions', icon: 'rule'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/contract-definitions/contract-definitions.module').then(m => m.ContractDefinitionsModule)
  },
  {
    path: 'policies',
    data: {title: 'Policies', icon: 'policy'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/policies/policies.module').then(m => m.PoliciesModule)
  },
  {
    path: 'assets',
    data: {title: 'Assets', icon: 'upload'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/assets/assets.module').then(m => m.AssetsModule)
  },
  {
    path: 'vocabularies',
    data: {title: 'Vocabularies', icon: 'book'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/vocabularies/vocabularies.module').then(m => m.VocabulariesModule)
  },
  {
    path: 'ai-model-browser',
    data: {title: 'AI Model Browser', icon: 'smart_toy'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/ai-model-browser/ai-model-browser.module').then(m => m.AiModelBrowserModule)
  },
  {
    path: 'ai-model-execution',
    data: {title: 'AI Model Execution', icon: 'play_circle'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/ai-model-execution/ai-model-execution.module').then(m => m.AiModelExecutionModule)
  },
  {
    path: 'ai-model-benchmarking',
    data: {title: 'AI Model Benchmarking', icon: 'leaderboard'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/ai-model-benchmarking/ai-model-benchmarking.module').then(m => m.AiModelBenchmarkingModule)
  },
  {
    path: 'ai-model-observer',
    data: {title: 'AI Model Observer', icon: 'monitoring'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/ai-model-observer/ai-model-observer.module').then(m => m.AiModelObserverModule)
  },
  {
    path: 'ontologies',
    data: {title: 'Ontologies', icon: 'schema'},
    canActivate: [AuthUserGuard],
    loadChildren: () => import('./pages/ontologies/ontologies.module').then(m => m.OntologiesModule)
  },
  {
    path: '', redirectTo: 'catalog', pathMatch: 'full'
  }
];

@NgModule({
  imports: [RouterModule.forRoot(routes, {})],
  exports: [RouterModule]
})
export class AppRoutingModule { }
