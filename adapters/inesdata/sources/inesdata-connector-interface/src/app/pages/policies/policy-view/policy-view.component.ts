import { Component, EventEmitter, OnInit, Output } from '@angular/core';
import { PolicyService } from "../../../shared/services/policy.service";
import { BehaviorSubject, Observer } from "rxjs";
import { MatDialog} from "@angular/material/dialog";
import { NotificationService } from "../../../shared/services/notification.service";
import { ConfirmationDialogComponent, ConfirmDialogModel } from "../../../shared/components/confirmation-dialog/confirmation-dialog.component";
import { PolicyDefinition, IdResponse, QuerySpec } from "../../../shared/models/edc-connector-entities";
import { PolicyRuleViewerComponent } from '../policy-rule-viewer/policy-rule-viewer.component';
import { PageEvent } from '@angular/material/paginator';import { PolicyCard } from '../../../shared/models/policy/policy-card';
import { PolicyCardBuilder } from '../../../shared/models/policy/policy-card-builder';
import { JsonDialogData } from '../../json-dialog/json-dialog/json-dialog.data';
import { JsonDialogComponent } from '../../json-dialog/json-dialog/json-dialog.component'
import { Router } from '@angular/router';

@Component({
  selector: 'app-policy-view',
  templateUrl: './policy-view.component.html',
  styleUrls: ['./policy-view.component.scss']
})
export class PolicyViewComponent implements OnInit {

  @Output()
  deleteDone = new EventEmitter();

  policies: PolicyDefinition[];
  policyCards: PolicyCard[] = [];
  private fetch$ = new BehaviorSubject(null);
  private readonly errorOrUpdateSubscriber: Observer<IdResponse>;

  // Pagination
  pageSize = 10;
  currentPage = 0;
  paginatorLength = 0;

  constructor(private policyService: PolicyService,
    private notificationService: NotificationService,
    private readonly dialog: MatDialog,
    private policyCardBuilder: PolicyCardBuilder,
    private router: Router) {
    this.errorOrUpdateSubscriber = {
      next: x => this.fetch$.next(null),
      error: err => this.showError(err, "An error occurred."),
      complete: () => {
        this.notificationService.showInfo("Successfully completed")
      },
    }

  }

  ngOnInit(): void {
    this.countPolicies();
    this.loadComplexPolicies(this.currentPage);
  }

  onCreate() {
    this.router.navigate(['policies/create'])
  }

  delete(policyId: string) {

    const dialogData = ConfirmDialogModel.forDelete("policy", policyId);

    const ref = this.dialog.open(ConfirmationDialogComponent, { maxWidth: '30%', data: dialogData });

    ref.afterClosed().subscribe({

      next: (res: any) => {
        if (res) {
          this.policyService.deletePolicy(policyId).subscribe(
            {
              next: (response: IdResponse) => this.errorOrUpdateSubscriber.next(response),
              error: (error: Error) => this.showError(error, "An error occurred while deleting the policy."),
              complete: () => {
                this.countPolicies();
                this.loadComplexPolicies(this.currentPage);
                this.notificationService.showInfo("Successfully deleted");
              }
            }
          );
        }
      }
    });
  }

  private showError(error: Error, errorMessage: string) {
    console.error(error);
    this.notificationService.showError(errorMessage);
  }

  viewRules(title: string, rules: any) {
    this.dialog.open(PolicyRuleViewerComponent, {
      disableClose: true,
      data: {
        title: title,
        rules: rules
      },
    });
  }

  changePage(event: PageEvent) {
    const offset = event.pageIndex * event.pageSize;
    this.pageSize = event.pageSize;
    this.currentPage = event.pageIndex;
    this.loadComplexPolicies(offset);
  }

  loadPolicies(offset: number) {

    const querySpec: QuerySpec = {
      offset: offset,
      limit: this.pageSize
    }

    this.policyService.queryAllPolicies(querySpec)
      .subscribe(results => {
        this.policies = results;
      });
  }

  countPolicies() {
    this.policyService.count()
      .subscribe(result => {
        this.paginatorLength = result;
      });
  }

  loadComplexPolicies(offset: number) {
    const querySpec: QuerySpec = {
      offset: offset,
      limit: this.pageSize
    }

    this.policyService.queryAllComplexPolicies(querySpec)
      .subscribe(result => {
        this.policyCards = this.policyCardBuilder.buildPolicyCardsFromPolicyDefinitions(result);
      });
  }

  onPolicyDetailClick(policyCard: PolicyCard) {
    const data: JsonDialogData = {
      title: policyCard.id,
      subtitle: 'Policy',
      icon: 'policy',
      objectForJson: policyCard.objectForJson
    };

    this.dialog.open(JsonDialogComponent, {data});
  }
}
