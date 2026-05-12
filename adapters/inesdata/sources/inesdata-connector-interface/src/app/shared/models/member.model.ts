/**
 * Member model
 */
export interface Member {
  id: string;
  name: string;
  username: string;
  firstName?: string;
  lastName?: string;
  email: string;
  roles: Array<string>;
}
