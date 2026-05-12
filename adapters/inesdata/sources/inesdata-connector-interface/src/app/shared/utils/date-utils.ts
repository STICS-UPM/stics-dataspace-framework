import { OperatorDto } from "../models/policy/ui-policy-constraint";

export function adjustDate(date: Date, operator: OperatorDto): string | null {
  if (!date) {
    return null;
  }

  let adjustedDate: Date;

  switch (operator) {
    case 'LT':
    case 'GEQ':
      adjustedDate = new Date(Date.UTC(
        date.getFullYear(),
        date.getMonth(),
        date.getDate(),
        0, 0, 0, 0
      ));
      break;
    case 'LEQ':
    case 'GT':
      adjustedDate = new Date(Date.UTC(
        date.getFullYear(),
        date.getMonth(),
        date.getDate(),
        23, 59, 59, 999
      ));
      break;
    default:
      return null;
  }

  return adjustedDate.toISOString();
}

 export function convertUTCToLocalDate(utcISOString: string): Date {
  const utcDate = new Date(utcISOString);

  return new Date(
    utcDate.getUTCFullYear(),
    utcDate.getUTCMonth(),
    utcDate.getUTCDate(),
    utcDate.getUTCHours(),
    utcDate.getUTCMinutes(),
    utcDate.getUTCSeconds(),
    utcDate.getUTCMilliseconds()
  );
}
