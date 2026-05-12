import { JsonLdObject } from "./edc-connector-entities";
export interface CriterionInput {
    operandLeft: string;
    operator: string;
    operandRight?: string[];
}
export declare class Criterion extends JsonLdObject {
    get operandLeft(): string;
    get operator(): string;
    get operandRight(): string[];
}
