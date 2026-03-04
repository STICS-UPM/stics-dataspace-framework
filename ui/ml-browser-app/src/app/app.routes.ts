import { Routes } from '@angular/router';
import { MlAssetsBrowserComponent } from './pages/ml-assets-browser/ml-assets-browser.component';
import { AssetCreateComponent } from './pages/asset-create/asset-create.component';
import { AssetDetailComponent } from './pages/asset-detail/asset-detail.component';
import { CatalogComponent } from './pages/catalog/catalog.component';
import { CatalogDetailComponent } from './pages/catalog/catalog-detail/catalog-detail.component';
import { ContractsComponent } from './pages/contracts/contracts.component';
import { ContractDefinitionNewComponent } from './pages/contract-definitions/contract-definition-new/contract-definition-new.component';
import { LoginComponent } from './pages/login/login.component';
import { ModelExecutionComponent } from './pages/model-execution/model-execution.component';
import { authGuard } from './shared/guards/auth.guard';

export const routes: Routes = [
  {
    path: '',
    redirectTo: '/ml-assets',
    pathMatch: 'full'
  },
  {
    path: 'login',
    component: LoginComponent
  },
  {
    path: 'ml-assets',
    component: MlAssetsBrowserComponent,
    canActivate: [authGuard]
  },
  {
    path: 'assets/create',
    component: AssetCreateComponent,
    canActivate: [authGuard]
  },
  {
    path: 'assets/:id',
    component: AssetDetailComponent,
    canActivate: [authGuard]
  },
  {
    path: 'catalog',
    component: CatalogComponent,
    canActivate: [authGuard]
  },
  {
    path: 'catalog/view',
    component: CatalogDetailComponent,
    canActivate: [authGuard]
  },
  {
    path: 'contracts',
    component: ContractsComponent,
    canActivate: [authGuard]
  },
  {
    path: 'contract-definitions/create',
    component: ContractDefinitionNewComponent,
    canActivate: [authGuard]
  },
  {
    path: 'infer',
    component: ModelExecutionComponent,
    canActivate: [authGuard]
  },
  {
    path: '**',
    redirectTo: '/login'
  }
];

