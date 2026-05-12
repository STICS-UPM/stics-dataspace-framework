import {HttpClient} from '@angular/common/http';
import {Injectable} from '@angular/core';
import {Location} from '@angular/common';

export interface AppConfig {
  theme: string;
}

@Injectable({
  providedIn: 'root'
})
export class AppConfigService {
  config?: AppConfig;

  constructor(private http: HttpClient, private location: Location) {}

  loadConfig(): Promise<void> {
    return this.http
      .get<AppConfig>(this.location.prepareExternalUrl('/assets/config/app.config.json'))
      .toPromise()
      .then(data => {
        this.config = data;
      });
  }

  getConfig(): AppConfig | undefined {
    return this.config;
  }
}
